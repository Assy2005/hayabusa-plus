"""hayabusa-plus extras: free-form event log search + Elasticsearch bridge.

Both features live outside `server.py` so the HTTP handler stays readable.
`server.Handler` calls `handle_get()` / `handle_post()` right before its own
404 fallbacks, passing a small context dict (workspace paths, engine binary,
SQLite store).  Nothing in here imports `server`, which keeps the module
importable on its own for tests.

Design notes
------------
* Log search shells out to the bundled Hayabusa engine (`search` command,
  JSONL output) instead of re-implementing EVTX parsing.  The engine already
  handles per-field decoding, provider names and timestamp maths; we only
  normalise its JSON into a shape the table can render.
* Every path that comes from the browser is validated to stay inside
  `workspace/` (same rule as the upload/scan endpoints).
* Elasticsearch talks plain HTTP(S) with urllib.  No `elasticsearch` pip
  package — the GUI still installs with zero third-party dependencies.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import re
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_SEARCH_SECONDS = 150          # engine wall clock for one search
MAX_SEARCH_EVENTS = 50_000        # stop parsing the JSONL after this many hits
MAX_RETURN_EVENTS = 2_000         # hard cap on one API response
MAX_JSONL_BYTES = 512 * 1024 * 1024
MAX_SOURCES = 500
ES_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _rel_under_workspace(ctx: dict, rel: str) -> Path:
    """Resolve a browser-supplied path, refusing anything outside workspace."""
    workspace = Path(ctx["workspace"]).resolve()
    target = (workspace / str(rel)).resolve()
    if target != workspace and workspace not in target.parents:
        raise ValueError("workspace の外は参照できません。")
    return target


def _fmt_size(n: int | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _json_error(handler, exc: Exception, status: int = 400):
    handler._send_json({"error": str(exc)}, status)


# ---------------------------------------------------------------------------
# Free log search
# ---------------------------------------------------------------------------

def _list_sources(ctx: dict) -> list[dict]:
    workspace = Path(ctx["workspace"])
    out: list[dict] = []
    for p in sorted(workspace.rglob("*")):
        try:
            if not p.is_file():
                continue
            suffix = p.suffix.lower()
            if suffix not in (".evtx", ".jsonl", ".json"):
                continue
            # Job output is analysis result, not a log source.
            rel = p.relative_to(workspace).as_posix()
            if rel.startswith("jobs/") or rel.startswith("results/"):
                continue
            # `.json` is only a log format inside uploads/; elsewhere it is
            # application state (elastic.json, saved configs, ...).
            if suffix == ".json" and not rel.startswith("uploads/"):
                continue
            st = p.stat()
        except OSError:
            continue
        out.append({
            "rel": rel,
            "name": p.name,
            "dir": str(Path(rel).parent).replace(".", "").replace("\\", "/"),
            "size": st.st_size,
            "size_h": _fmt_size(st.st_size),
            "mtime": st.st_mtime,
        })
        if len(out) >= MAX_SOURCES:
            break
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _parse_jsonl(text: str, limit: int) -> tuple[list[dict], bool]:
    """Parse concatenated / pretty-printed JSON objects until `limit`."""
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    objs: list[dict] = []
    while i < n:
        while i < n and text[i] in " \r\n\t,":
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            # Truncated tail (engine still writing) — stop cleanly.
            break
        i = end
        if isinstance(obj, dict):
            objs.append(obj)
            if len(objs) >= limit:
                return objs, True
    return objs, False


def _norm_event(o: dict) -> dict:
    """Flatten one engine search record into the table's vocabulary."""
    eid = o.get("Event ID", o.get("EventID"))
    rid = o.get("Record ID", o.get("RecordID"))
    details = o.get("AllFieldInfo")
    if details is None:
        details = o.get("Details") or {}
    return {
        "Timestamp": o.get("Timestamp") or o.get("UtcTime") or "",
        "Computer": o.get("Hostname") or o.get("Computer") or "",
        "Channel": o.get("Channel") or "",
        "EventID": eid,
        "RecordID": rid,
        "Title": o.get("EventTitle") or o.get("RuleTitle") or "",
        "Details": details,
        "raw": o,
    }


def _filter_events(events: list[dict], *, event_ids: set[str], channel: str,
                   computer: str) -> list[dict]:
    out = []
    for ev in events:
        if event_ids and str(ev.get("EventID")) not in event_ids:
            continue
        if channel and channel.lower() not in str(ev.get("Channel", "")).lower():
            continue
        if computer and not fnmatch.fnmatch(str(ev.get("Computer", "")).lower(),
                                           computer.lower()):
            continue
        out.append(ev)
    return out


def _search_local_jsonl(path: Path, *, query: str, regex: bool,
                        ignore_case: bool) -> list[dict]:
    """Search a .jsonl/.json source without the engine (cheap text match)."""
    flags = re.IGNORECASE if ignore_case else 0
    pat = None
    terms: list[str] = []
    if query:
        if regex:
            pat = re.compile(query, flags)
        else:
            terms = [t.lower() for t in query.split() if t]
    objs: list[dict] = []
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise ValueError("このファイルは大きすぎます (512 MiB 超)。EVTX を直接指定してください。")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        blob = json.dumps(obj, ensure_ascii=False)
        if pat is not None:
            if not pat.search(blob):
                continue
        elif terms:
            low = blob.lower()
            if not all(t in low for t in terms):
                continue
        objs.append(obj)
        if len(objs) >= MAX_SEARCH_EVENTS:
            break
    return objs


def _run_engine_search(ctx: dict, src: Path, *, query: str, regex: bool,
                       ignore_case: bool, and_logic: bool,
                       start: str, end: str,
                       filters: list[str] | None = None,
                       normalize: bool = True
                       ) -> tuple[list[dict], str, bool]:
    """Run `hayabusa search` and return (events, stderr, truncated)."""
    tmp = Path(tempfile.mkstemp(prefix="hayfx-search-", suffix=".jsonl")[1])
    try:
        argv = [str(ctx["hayabusa"]), "search", "-f", str(src),
                "-L", "-o", str(tmp), "-q", "-K", "-b", "-C"]
        if src.is_dir():
            argv = [str(ctx["hayabusa"]), "search", "-d", str(src),
                    "-L", "-o", str(tmp), "-q", "-K", "-b", "-C"]
        for flt in filters or []:
            argv += ["-F", flt]
        if regex:
            pattern = ("(?i)" + query) if ignore_case else query
            argv += ["-r", pattern]
        else:
            terms = [t for t in query.split() if t]
            if not terms:
                # No query = every event. `-i` cannot be combined with `-r`,
                # so case folding has to ride inside the pattern.
                argv += ["-r", "(?i)." if ignore_case else "."]
            else:
                if ignore_case:
                    argv.append("-i")
                if and_logic:
                    argv.append("-a")
                for t in terms:
                    argv += ["-k", t]
        if start:
            argv += ["--timeline-start", start]
        if end:
            argv += ["--timeline-end", end]

        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=MAX_SEARCH_SECONDS,
                              cwd=str(ctx["root"]))
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0 and not tmp.exists():
            raise RuntimeError(stderr[-1200:] or f"engine exit {proc.returncode}")
        text = tmp.read_text(encoding="utf-8", errors="replace") if tmp.exists() else ""
        objs, truncated = _parse_jsonl(text, MAX_SEARCH_EVENTS)
        if normalize:
            return [_norm_event(o) for o in objs], stderr, truncated
        return objs, stderr, truncated
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


GRAPH_EIDS = ("1", "3", "11", "22", "4688", "5156",
              "5136", "4662", "4719", "4738", "4702", "1102", "4742")


def collect_graph_events(ctx: dict, rel: str, computer: str,
                         max_events: int = 30_000) -> dict:
    """Read raw events needed by the relationship graph from one evidence path.

    The engine is invoked once per EventID with `-F EventID:<n>` so we do not
    have to materialise every Application/System event just to find process,
    file and network activity. The source may be a single EVTX/JSONL file or a
    directory of extracted channels.
    """
    src = _rel_under_workspace(ctx, rel)
    if not src.exists():
        raise ValueError("証跡ファイルが見つかりません。")
    if not src.is_dir() and src.suffix.lower() not in (".evtx", ".jsonl", ".json"):
        raise ValueError("関係図の対象は .evtx / .jsonl / .json です。")

    # JSONL can be parsed directly; no need to invoke the EVTX engine.
    if not src.is_dir() and src.suffix.lower() in (".jsonl", ".json"):
        raw = _search_local_jsonl(src, query="", regex=False,
                                  ignore_case=True)
        events: list[dict] = []
        counts: Counter[str] = Counter()
        for obj in raw:
            if not isinstance(obj, dict):
                continue
            eid = str(obj.get("EventID", obj.get("Event ID", "")))
            ch = str(obj.get("Channel") or "(不明)")
            counts[f"{ch}|{eid}"] += 1
            if eid not in GRAPH_EIDS:
                continue
            host = str(obj.get("Hostname") or obj.get("Computer") or "")
            if computer and host and host.lower() != computer.lower():
                continue
            events.append(obj)
            if len(events) >= max_events:
                break
        return {"events": events, "truncated": len(events) >= max_events,
                "errors": [], "source": rel,
                "present": [{"channel": ch, "event_id": eid, "count": n}
                            for key, n in counts.most_common(10)
                            for ch, _, eid in [key.partition("|")]]}

    events: list[dict] = []
    errors: list[str] = []
    counts: Counter[str] = Counter()
    truncated = False
    seen: set[str] = set()
    # One search per channel is much cheaper than one search per EventID.
    channel_eids = (
        ("Microsoft-Windows-Sysmon/Operational",
         {"1", "3", "11", "22"}),
        ("Security",
         {"4688", "5156", "5136", "4662", "4719", "4738", "4702",
          "1102", "4742"}),
    )
    for channel, wanted in channel_eids:
        channel_unknown_eid = False

        def add_event(obj: dict, eid_hint: str = "") -> None:
            nonlocal truncated, channel_unknown_eid
            if len(events) >= max_events:
                return
            eid = str(obj.get("Event ID") or obj.get("EventID") or "")
            if eid in ("", "-", "?"):
                eid = eid_hint
                channel_unknown_eid = True
                if eid:
                    # Some synthetic/custom providers omit EventID in search
                    # output. The EventID filter still selected the right
                    # records, so restore the field for the graph builder.
                    obj["EventID"] = eid
                    obj["Event ID"] = eid
            ch = str(obj.get("Channel") or channel or "(不明)")
            counts[f"{ch}|{eid}"] += 1
            if eid not in wanted:
                return
            host = str(obj.get("Hostname") or obj.get("Computer") or "")
            if computer and host and host.lower() != computer.lower():
                return
            key = (str(obj.get("Record ID") or obj.get("RecordID") or "")
                   + "|" + eid
                   + "|" + str(obj.get("Timestamp") or ""))
            if key in seen:
                return
            seen.add(key)
            events.append(obj)
            if len(events) >= max_events:
                truncated = True

        raw, stderr, trunc = _run_engine_search(
            ctx, src, query="", regex=False, ignore_case=True,
            and_logic=False, start="", end="",
            filters=[f"Channel:{channel}"], normalize=False)
        if stderr and not raw:
            errors.append(f"Channel {channel}: {stderr[-500:]}")
        if trunc:
            truncated = True
        for obj in raw:
            if isinstance(obj, dict):
                add_event(obj)
        if len(events) >= max_events:
            break

        # A few providers (and our synthetic fixtures) do not expose EventID
        # in `hayabusa search` JSON. Fall back to one filtered search per EID
        # only for that channel; normal EVTX stays on the fast single pass.
        if channel_unknown_eid:
            for eid in sorted(wanted, key=lambda x: int(x)):
                raw, stderr, trunc = _run_engine_search(
                    ctx, src, query="", regex=False, ignore_case=True,
                    and_logic=False, start="", end="",
                    filters=[f"Channel:{channel}", f"EventID:{eid}"],
                    normalize=False)
                if stderr and not raw:
                    errors.append(
                        f"Channel {channel} / EventID {eid}: {stderr[-300:]}")
                if trunc:
                    truncated = True
                for obj in raw:
                    if isinstance(obj, dict):
                        add_event(obj, eid)
                if len(events) >= max_events:
                    break
        if len(events) >= max_events:
            break
    present = [
        {"channel": ch, "event_id": eid, "count": n}
        for key, n in counts.most_common(10)
        for ch, _, eid in [key.partition("|")]
    ]
    return {"events": events, "truncated": truncated, "errors": errors,
            "source": rel, "present": present}


def api_log_sources(ctx: dict) -> dict:
    return {"sources": _list_sources(ctx), "engine": str(ctx["hayabusa"])}


def api_log_search(ctx: dict, body: dict) -> dict:
    rel = (body.get("source") or "").strip()
    if not rel:
        raise ValueError("検索対象のファイルを選んでください。")
    src = _rel_under_workspace(ctx, rel)
    if not src.is_file():
        raise ValueError(f"ファイルが見つかりません: {rel}")
    if src.suffix.lower() not in (".evtx", ".jsonl", ".json"):
        raise ValueError("対応しているのは .evtx / .jsonl / .json です。")

    query = (body.get("query") or "").strip()
    regex = bool(body.get("regex"))
    ignore_case = body.get("ignore_case", True) is not False
    and_logic = bool(body.get("and_logic"))
    start = (body.get("start") or "").strip()
    end = (body.get("end") or "").strip()
    limit = max(1, min(int(body.get("limit") or 200), MAX_RETURN_EVENTS))
    event_ids = {s for s in re.split(r"[\s,]+", str(body.get("event_ids") or "")) if s}
    channel = (body.get("channel") or "").strip()
    computer = (body.get("computer") or "").strip()

    t0 = time.perf_counter()
    truncated = False
    if src.suffix.lower() == ".evtx":
        events, stderr, truncated = _run_engine_search(
            ctx, src, query=query, regex=regex, ignore_case=ignore_case,
            and_logic=and_logic, start=start, end=end)
    else:
        stderr = ""
        events = [_norm_event(o) for o in _search_local_jsonl(
            src, query=query, regex=regex, ignore_case=ignore_case)]
        events = _filter_events(events, event_ids=event_ids,
                                channel=channel, computer=computer)

    if src.suffix.lower() == ".evtx":
        events = _filter_events(events, event_ids=event_ids,
                                channel=channel, computer=computer)

    matched = len(events)
    shown = events[:limit]
    return {
        "source": rel,
        "query": query,
        "regex": regex,
        "matched": matched,
        "returned": len(shown),
        "truncated": truncated or matched > len(shown),
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "events": shown,
        "stderr": stderr[-2000:] if stderr else "",
    }


# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------

CONFIG_NAME = "elastic.json"
DEFAULT_INDEX = "hayabusa-detections"


def _config_path(ctx: dict) -> Path:
    return Path(ctx["workspace"]) / CONFIG_NAME


def _load_config(ctx: dict) -> dict:
    p = _config_path(ctx)
    cfg: dict[str, Any] = {"url": "", "index": DEFAULT_INDEX, "username": "",
                           "password": "", "api_key": "", "verify_tls": True,
                           "timeout": ES_TIMEOUT}
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update({k: v for k, v in saved.items() if k in cfg})
        except (OSError, json.JSONDecodeError):
            pass
    cfg["index"] = str(cfg.get("index") or DEFAULT_INDEX)
    return cfg


def _public_config(cfg: dict) -> dict:
    return {
        "configured": bool(cfg.get("url")),
        "url": cfg.get("url", ""),
        "index": cfg.get("index", DEFAULT_INDEX),
        "username": cfg.get("username", ""),
        "has_password": bool(cfg.get("password")),
        "has_api_key": bool(cfg.get("api_key")),
        "verify_tls": bool(cfg.get("verify_tls", True)),
    }


def _save_config(ctx: dict, body: dict) -> dict:
    cfg = _load_config(ctx)
    url = (body.get("url") or "").strip().rstrip("/")
    if url and not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL は http:// または https:// で始めてください。")
    cfg["url"] = url
    cfg["index"] = (body.get("index") or DEFAULT_INDEX).strip() or DEFAULT_INDEX
    cfg["username"] = (body.get("username") or "").strip()
    cfg["verify_tls"] = body.get("verify_tls", True) is not False
    # Empty password/api_key means "keep the stored secret".
    pw = body.get("password")
    if pw is not None and pw != "":
        cfg["password"] = pw
    if body.get("clear_password"):
        cfg["password"] = ""
    key = body.get("api_key")
    if key is not None and key != "":
        cfg["api_key"] = key
    if body.get("clear_api_key"):
        cfg["api_key"] = ""
    p = _config_path(ctx)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return _public_config(cfg)


def _http(cfg: dict, method: str, path: str, payload: Any = None,
          ndjson: str | None = None, timeout: int | None = None) -> tuple[int, Any]:
    base = (cfg.get("url") or "").rstrip("/")
    if not base:
        raise ValueError("Elasticsearch の URL が未設定です。")
    url = base + path
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if ndjson is not None:
        data = ndjson.encode("utf-8")
        headers["Content-Type"] = "application/x-ndjson"
    elif payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if cfg.get("api_key"):
        headers["Authorization"] = "ApiKey " + cfg["api_key"].strip()
    elif cfg.get("username"):
        token = base64.b64encode(
            f"{cfg['username']}:{cfg.get('password') or ''}".encode()).decode()
        headers["Authorization"] = "Basic " + token

    ctx_ssl = None
    if url.lower().startswith("https://"):
        ctx_ssl = ssl.create_default_context()
        if not cfg.get("verify_tls", True):
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or ES_TIMEOUT,
                                    context=ctx_ssl) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype and raw:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": body[:800]}
        return e.code, parsed
    except urllib.error.URLError as e:
        raise RuntimeError(f"接続できません: {e.reason}") from e


def _es_error(status: int, body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            err = err.get("reason") or err.get("type") or err
        if err:
            return f"HTTP {status}: {err}"
    return f"HTTP {status}"


def api_elastic_config_get(ctx: dict) -> dict:
    return _public_config(_load_config(ctx))


def api_elastic_config_post(ctx: dict, body: dict) -> dict:
    return _save_config(ctx, body)


def api_elastic_test(ctx: dict) -> dict:
    cfg = _load_config(ctx)
    if not cfg.get("url"):
        raise ValueError("先に接続先 URL を保存してください。")
    status, body = _http(cfg, "GET", "/")
    if status >= 400:
        raise RuntimeError(_es_error(status, body))
    info = body if isinstance(body, dict) else {}
    version = (info.get("version") or {}).get("number", "")
    return {
        "ok": True,
        "cluster_name": info.get("cluster_name", ""),
        "tagline": info.get("tagline", ""),
        "version": version,
        "index": cfg.get("index"),
    }


def api_elastic_status(ctx: dict) -> dict:
    cfg = _load_config(ctx)
    if not cfg.get("url"):
        return {"configured": False}
    status, body = _http(cfg, "GET", f"/{urllib.parse.quote(cfg['index'])}/_count")
    if status == 404:
        return {"configured": True, "index": cfg["index"], "exists": False, "count": 0}
    if status >= 400:
        raise RuntimeError(_es_error(status, body))
    return {"configured": True, "index": cfg["index"], "exists": True,
            "count": int((body or {}).get("count", 0))}


def _ensure_index(cfg: dict, reset: bool) -> dict:
    idx = urllib.parse.quote(cfg["index"])
    if reset:
        st, _ = _http(cfg, "DELETE", f"/{idx}")
        if st not in (200, 404):
            raise RuntimeError(f"既存インデックスの削除に失敗しました (HTTP {st})")
    st, body = _http(cfg, "HEAD", f"/{idx}")
    if st == 200:
        return {"created": False}
    mapping = {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                "job_id": {"type": "keyword"},
                "line_no": {"type": "long"},
                "level": {"type": "keyword"},
                "rule_id": {"type": "keyword"},
                "rule_title": {"type": "text",
                               "fields": {"keyword": {"type": "keyword",
                                                      "ignore_above": 512}}},
                "computer": {"type": "keyword"},
                "channel": {"type": "keyword"},
                "event_id": {"type": "keyword"},
                "verdict": {"type": "keyword"},
                "event": {"type": "object", "enabled": True},
            }
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    }
    st, body = _http(cfg, "PUT", f"/{idx}", payload=mapping)
    if st >= 400:
        raise RuntimeError(_es_error(st, body))
    return {"created": True}


def _doc_for(row: Any) -> dict:
    try:
        raw = json.loads(row["raw_json"])
    except (TypeError, json.JSONDecodeError):
        raw = {"_raw": row["raw_json"]}
    return {
        "@timestamp": row["ts"],
        "job_id": row["job_id"],
        "line_no": row["line_no"],
        "level": row["level"],
        "rule_id": row["rule_id"],
        "rule_title": row["rule_title"],
        "computer": row["computer"],
        "channel": row["channel"],
        "event_id": row["event_id"],
        "verdict": row["verdict"],
        "event": raw,
    }


def api_elastic_index(ctx: dict, body: dict) -> dict:
    cfg = _load_config(ctx)
    if not cfg.get("url"):
        raise ValueError("先に Elasticsearch の接続先を設定してください。")
    reset = bool(body.get("reset"))
    job_id = (body.get("job_id") or "").strip() or None
    created = _ensure_index(cfg, reset)
    store = ctx["store"]
    idx = urllib.parse.quote(cfg["index"])

    indexed, errors, offset, page = 0, [], 0, 1000
    while True:
        rows = store.query_detections(job_id=job_id, include_suppressed=True,
                                      offset=offset, limit=page)
        if not rows:
            break
        lines: list[str] = []
        for row in rows:
            meta = {"index": {"_index": cfg["index"],
                              "_id": f"{row['job_id']}:{row['line_no']}"}}
            lines.append(json.dumps(meta, ensure_ascii=False))
            lines.append(json.dumps(_doc_for(row), ensure_ascii=False,
                                    default=str))
        ndjson = "\n".join(lines) + "\n"
        st, resp = _http(cfg, "POST", "/_bulk", ndjson=ndjson, timeout=60)
        if st >= 400:
            raise RuntimeError(_es_error(st, resp))
        if isinstance(resp, dict):
            if resp.get("errors"):
                for item in resp.get("items", []):
                    err = (item.get("index") or {}).get("error")
                    if err and len(errors) < 5:
                        errors.append(str(err.get("reason") or err))
            indexed += len(rows) - sum(1 for it in resp.get("items", [])
                                       if (it.get("index") or {}).get("error"))
        offset += page
        if len(rows) < page:
            break

    st, body2 = _http(cfg, "POST", f"/{idx}/_refresh")
    return {"indexed": indexed, "index": cfg["index"], "errors": errors,
            "created": created.get("created", False),
            "refresh": st < 400}


def api_elastic_search(ctx: dict, body: dict) -> dict:
    cfg = _load_config(ctx)
    if not cfg.get("url"):
        raise ValueError("先に Elasticsearch の接続先を設定してください。")
    q = (body.get("query") or "").strip() or "*"
    size = max(1, min(int(body.get("size") or 50), 500))
    offset = max(0, int(body.get("from") or 0))

    must: list[dict] = [{
        "query_string": {"query": q, "default_operator": "AND", "lenient": True}
    }]
    filters: list[dict] = []
    for field, key in (("level", "level"), ("computer", "computer"),
                       ("job_id", "job_id")):
        val = (body.get(key) or "").strip()
        if val:
            filters.append({"term": {field: val}})

    query = {"bool": {"must": must}}
    if filters:
        query["bool"]["filter"] = filters

    payload = {
        "size": size,
        "from": offset,
        "track_total_hits": True,
        "query": query,
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "aggs": {"by_level": {"terms": {"field": "level", "size": 8}}},
        "highlight": {"pre_tags": ["<mark>"], "post_tags": ["</mark>"],
                      "fields": {"*": {"fragment_size": 160,
                                       "number_of_fragments": 1}}},
    }
    idx = urllib.parse.quote(cfg["index"])
    status, resp = _http(cfg, "POST", f"/{idx}/_search", payload=payload)
    if status >= 400:
        raise RuntimeError(_es_error(status, resp))
    resp = resp or {}
    hits = resp.get("hits", {})
    total = hits.get("total")
    if isinstance(total, dict):
        total = total.get("value", 0)
    rows = []
    for h in hits.get("hits", []):
        src = h.get("_source") or {}
        rows.append({
            "id": h.get("_id"),
            "index": h.get("_index"),
            "score": h.get("_score"),
            "highlight": h.get("highlight") or {},
            **src,
        })
    buckets = ((resp.get("aggregations") or {}).get("by_level") or {}).get("buckets", [])
    return {"total": total or 0, "took": resp.get("took", 0),
            "hits": rows, "by_level": buckets, "index": cfg["index"],
            "from": offset, "size": size}


# ---------------------------------------------------------------------------
# Routing entry points (called from server.Handler)
# ---------------------------------------------------------------------------

_POST_ROUTES = {
    "/api/logs/search": api_log_search,
    "/api/elastic/config": api_elastic_config_post,
    "/api/elastic/index": api_elastic_index,
    "/api/elastic/search": api_elastic_search,
}


def handle_get(handler, path: str, query: dict, ctx: dict) -> bool:
    if path == "/api/logs/sources":
        handler._send_json(api_log_sources(ctx))
        return True
    if path == "/api/elastic/config":
        handler._send_json(api_elastic_config_get(ctx))
        return True
    if path == "/api/elastic/status":
        try:
            handler._send_json(api_elastic_status(ctx))
        except Exception as exc:  # noqa: BLE001
            _json_error(handler, exc, 502)
        return True
    if path == "/api/elastic/test":
        try:
            handler._send_json(api_elastic_test(ctx))
        except Exception as exc:  # noqa: BLE001
            _json_error(handler, exc, 502)
        return True
    return False


def handle_post(handler, path: str, ctx: dict) -> bool:
    fn = _POST_ROUTES.get(path)
    if not fn:
        return False
    if path.startswith("/api/elastic/") and not handler._client_is_local():
        handler._send_json({"error": "Elasticsearch 設定はローカル操作のみ許可されています。"}, 403)
        return True
    try:
        body = handler._read_json()
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, 400)
        return True
    try:
        handler._send_json(fn(ctx, body))
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, 400)
    except RuntimeError as exc:
        handler._send_json({"error": str(exc)}, 502)
    except subprocess.TimeoutExpired:
        handler._send_json({"error": "検索がタイムアウトしました。条件を絞ってください。"}, 504)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
    return True
