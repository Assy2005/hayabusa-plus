from __future__ import annotations
"""
Hayabusa GUI — localhost web frontend for the Hayabusa DFIR scanner.

Pure Python stdlib (no external deps). Wraps the Hayabusa CLI binary as a
subprocess and exposes a small JSON API plus a static SPA on http://127.0.0.1:8787.

Design notes
------------
* Subprocess isolation: each scan is a `hayabusa json-timeline` invocation. The
  GUI never parses EVTX itself; Hayabusa remains the trust boundary for parsing
  and Sigma matching. This keeps the GUI a thin telemetry/control plane.
* JSONL streaming: Hayabusa is invoked with `--JSONL-output`, which emits one
  detection per line. We tail the file while the job runs so the frontend can
  display detections progressively over SSE.
* No write access outside the workspace: uploads land in ./workspace/uploads,
  results in ./workspace/results. Paths are validated against the workspace
  root to defeat path-traversal from the UI.
* Localhost-only bind by default. Treat this process as the local-admin
  console — there is no authentication.
"""

import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Local module — pure-stdlib SQLite layer.
sys_path_anchor = Path(__file__).resolve().parent
sys.path.insert(0, str(sys_path_anchor))
import store as _store  # noqa: E402
import rule_index as _rule_index  # noqa: E402
import process_tree as _process_tree  # noqa: E402
import behavioral as _behavioral  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = ROOT / "gui"
STATIC_DIR = GUI_DIR / "static"
WORKSPACE = ROOT / "workspace"
UPLOAD_DIR = WORKSPACE / "uploads"
RESULTS_DIR = WORKSPACE / "results"
JOBS_DIR = WORKSPACE / "jobs"
LOOKUPS_DIR = ROOT / "lookups"
FP_HISTORY_DIR = LOOKUPS_DIR / "fp_history"
BIN_DIR = ROOT / "bin"
DB_PATH = WORKSPACE / "hayabusa-gui.sqlite"

for d in (UPLOAD_DIR, RESULTS_DIR, JOBS_DIR, FP_HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

STORE = _store.Store(DB_PATH, FP_HISTORY_DIR)
RULES_DIR_FOR_INDEX = BIN_DIR / "rules"
CUSTOM_RULES_DIR = ROOT / "rules-custom"
RULE_INDEX = _rule_index.RuleIndex(RULES_DIR_FOR_INDEX, CUSTOM_RULES_DIR)

# System-EVTX inspection root on Windows. We only attempt to read this when
# the user explicitly asks via /api/system/* — never automatically.
SYSTEM_EVTX_ROOT = Path("C:/Windows/System32/winevt/Logs")
SYSTEM_SNAPSHOT_DIR = UPLOAD_DIR / "system-snapshot"


def _is_admin_windows() -> bool:
    """Return True when the current process holds elevated rights.

    Uses the official shell32!IsUserAnAdmin call rather than checking for
    membership in BUILTIN\\Administrators, because UAC-restricted tokens
    return False even for users in the Administrators group — which is the
    behaviour we want (we can't open System32\\winevt\\Logs from a
    restricted token).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


# Channels we always surface first in the UI — they're the high-signal
# DFIR sources. Anything else is grouped under "その他" by category.
PRIORITY_CHANNELS = [
    "Security",
    "System",
    "Application",
    "Microsoft-Windows-Sysmon%4Operational",
    "Microsoft-Windows-PowerShell%4Operational",
    "Windows PowerShell",
    "Microsoft-Windows-WMI-Activity%4Operational",
    "Microsoft-Windows-TaskScheduler%4Operational",
    "Microsoft-Windows-Windows Defender%4Operational",
    "Microsoft-Windows-CodeIntegrity%4Operational",
    "Microsoft-Windows-AppLocker%4EXE and DLL",
    "Microsoft-Windows-Bits-Client%4Operational",
]
PRIORITY_SET = {name.lower() for name in PRIORITY_CHANNELS}


def _list_system_channels() -> list[dict]:
    """Inventory every .evtx file under the Windows event-log directory.

    We tolerate per-file failures: it's common for a non-admin process to
    enumerate the directory but fail to stat individual privileged files.
    We always emit a row so the analyst sees which channel was unreachable.
    """
    out: list[dict] = []
    if not SYSTEM_EVTX_ROOT.exists():
        return out
    try:
        entries = sorted(SYSTEM_EVTX_ROOT.glob("*.evtx"),
                         key=lambda p: p.name.lower())
    except OSError:
        return out
    for p in entries:
        readable = False
        size = None
        mtime = None
        try:
            st = p.stat()
            size = st.st_size
            mtime = st.st_mtime
            # Cheap readability probe — open + close.
            with open(p, "rb"):
                readable = True
        except OSError:
            pass
        nice = p.stem.replace("%4", "/")
        out.append({
            "name": p.name,
            "channel": nice,
            "size": size,
            "mtime": mtime,
            "readable": readable,
            "priority": p.stem.lower() in PRIORITY_SET,
        })
    return out


def find_hayabusa() -> Path:
    """Locate the hayabusa binary inside ./bin.

    Prefers our forked build (`hayabusa-fx-*.exe`) over the upstream
    release zip's binary because the fork ships the `lookup:` Sigma
    extension and a few related modifiers. Falls back to any other
    `hayabusa*.exe` when the fork isn't present.
    """
    all_candidates = sorted(BIN_DIR.glob("hayabusa*.exe")) + sorted(BIN_DIR.glob("hayabusa"))
    if not all_candidates:
        raise SystemExit(
            f"Hayabusa binary not found in {BIN_DIR}. "
            "Drop hayabusa-*.exe (Windows) or hayabusa (Linux/macOS) there."
        )
    fx = [c for c in all_candidates if "-fx-" in c.name]
    return fx[0] if fx else all_candidates[0]


HAYABUSA_BIN = find_hayabusa()
RULES_DIR = BIN_DIR / "rules"
CONFIG_DIR = BIN_DIR / "config"


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------

class Job:
    """One Hayabusa scan invocation, tracked with progress + detections."""

    __slots__ = (
        "id", "kind", "args", "started_at", "finished_at", "status", "exit_code",
        "stdout_log", "stderr_log", "result_jsonl", "result_summary",
        "subscribers", "lock", "detection_count", "last_event_at",
        "_indexed_lines_at_start",
    )

    def __init__(self, kind: str, args: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.args = args
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.status = "queued"          # queued | running | done | failed | cancelled
        self.exit_code: int | None = None
        job_dir = JOBS_DIR / self.id
        job_dir.mkdir(parents=True, exist_ok=True)
        self.stdout_log = job_dir / "stdout.log"
        self.stderr_log = job_dir / "stderr.log"
        self.result_jsonl = job_dir / "timeline.jsonl"
        self.result_summary = job_dir / "summary.html"
        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.detection_count = 0
        self.last_event_at = self.started_at
        self._indexed_lines_at_start = 0

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "detection_count": self.detection_count,
            "args": self.args,
        }

    def persist(self):
        """Mirror the in-memory job to SQLite so it survives a restart."""
        try:
            STORE.upsert_job(self.to_dict())
        except Exception as exc:  # noqa: BLE001 — non-fatal
            sys.stderr.write(f"[store] upsert_job failed: {exc}\n")

    def publish(self, event: dict):
        self.last_event_at = time.time()
        payload = "data: " + json.dumps(event) + "\n\n"
        with self.lock:
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self.subscribers.remove(q)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.append(q)
        # Replay an initial state so a late subscriber gets context.
        q.put_nowait("data: " + json.dumps({"type": "state", "job": self.to_dict()}) + "\n\n")
        return q


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def register_job(job: Job):
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.persist()


# ---------------------------------------------------------------------------
# Hayabusa invocation
# ---------------------------------------------------------------------------

def safe_workspace_path(p: str) -> Path:
    """Reject paths that escape the workspace root."""
    candidate = (WORKSPACE / p).resolve()
    if WORKSPACE.resolve() not in candidate.parents and candidate != WORKSPACE.resolve():
        raise ValueError(f"Path escapes workspace: {p}")
    return candidate


def build_hayabusa_argv(job: Job, params: dict) -> list[str]:
    """
    Translate the GUI's scan request into a hayabusa argv.

    Only a vetted subset of CLI flags is exposed. We deliberately do NOT pass
    arbitrary user-supplied flags through — that would let the UI flip
    --live-analysis on hosts where it shouldn't run.
    """
    argv: list[str] = [str(HAYABUSA_BIN), "json-timeline", "--no-wizard",
                       "-L", "-o", str(job.result_jsonl),
                       "-C", "-q", "-K", "-s", "-b",
                       # -p verbose ensures ExtraFieldInfo (the raw EventData
                       # dict from EvtRender) is included with every detection.
                       # Without it we can't reliably reconstruct process
                       # trees from Sysmon EID 1, because ProcessGuid /
                       # ParentProcessGuid live outside the standard `Details`
                       # string. Verbose adds ~30% to the output size which is
                       # acceptable for a DFIR tool.
                       "-p", "verbose"]

    target = params.get("target", {})
    if target.get("type") == "file":
        resolved = safe_workspace_path(target["path"])
        argv += ["-f", str(resolved)]
        # Hayabusa needs an explicit -J flag for JSON/JSONL input or it
        # refuses with "only accepts .evtx files".
        if resolved.suffix.lower() in (".json", ".jsonl"):
            argv += ["-J"]
    elif target.get("type") == "directory":
        argv += ["-d", str(safe_workspace_path(target["path"]))]
    elif target.get("type") == "live" and params.get("allow_live"):
        argv += ["-l"]
    else:
        raise ValueError("Unknown or unauthorized target type")

    min_level = params.get("min_level")
    if min_level in {"informational", "low", "medium", "high", "critical"}:
        argv += ["-m", min_level]

    if params.get("eid_filter"):
        argv += ["-E"]
    if params.get("enable_all_rules"):
        argv += ["-A"]
    if params.get("proven_rules"):
        argv += ["-P"]
    if params.get("remove_duplicates"):
        argv += ["-X"]

    include_tags = params.get("include_tags") or []
    if include_tags:
        argv += ["--include-tag", ",".join(include_tags)]
    exclude_tags = params.get("exclude_tags") or []
    if exclude_tags:
        argv += ["--exclude-tag", ",".join(exclude_tags)]

    # Optional time window
    if params.get("timeline_start"):
        argv += ["--timeline-start", params["timeline_start"]]
    if params.get("timeline_end"):
        argv += ["--timeline-end", params["timeline_end"]]

    # HTML summary
    argv += ["-H", str(job.result_summary)]

    # Custom rules dir (live-response builds need this)
    argv += ["-r", str(RULES_DIR), "-c", str(RULES_DIR / "config")]

    return argv


SEVERITY_RANK = {"informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def tail_results(job: Job, stop_event: threading.Event):
    """
    Stream JSONL detections out of Hayabusa's output file as they appear, and
    mirror them into SQLite for cross-job querying.

    Hayabusa writes detections to disk during the scan. We tail the file with
    a small sleep — a polling tail is plenty fast for the volumes a single
    workstation produces, and it avoids needing inotify/ReadDirectoryChangesW.

    The line-number bookkeeping is kept in lockstep with the store's
    ``indexed_lines`` counter so reindex-on-boot is a no-op for jobs already
    fully indexed.
    """
    pos = 0
    line_no = job._indexed_lines_at_start  # set by run_job before we start
    while not stop_event.is_set():
        try:
            if job.result_jsonl.exists():
                with open(job.result_jsonl, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                    if chunk:
                        batch: list[tuple[int, str, dict]] = []
                        for raw in chunk.splitlines():
                            raw = raw.rstrip("\r")
                            if not raw.strip():
                                continue
                            try:
                                event = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            line_no += 1
                            batch.append((line_no, raw, event))
                            job.detection_count += 1
                            job.publish({"type": "detection", "event": event,
                                         "n": job.detection_count})
                        if batch:
                            inserted = STORE.insert_detections(job.id, batch)
                            STORE.bump_indexed_lines(job.id, inserted)
        except Exception as exc:  # noqa: BLE001 — best-effort tailer
            job.publish({"type": "error", "stage": "tail", "msg": str(exc)})
        time.sleep(0.4)


def run_job(job: Job, params: dict):
    try:
        argv = build_hayabusa_argv(job, params)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.exit_code = -1
        job.publish({"type": "error", "stage": "args", "msg": str(exc)})
        job.finished_at = time.time()
        job.persist()
        return

    job.status = "running"
    job.persist()
    job.publish({"type": "state", "job": job.to_dict()})

    stop_event = threading.Event()
    # Resume from wherever the indexer last left off — usually 0 for a fresh
    # job, nonzero only on the recovery path where a job restarted mid-scan.
    job._indexed_lines_at_start = STORE.indexed_lines(job.id)
    tailer = threading.Thread(target=tail_results, args=(job, stop_event), daemon=True)
    tailer.start()

    try:
        with open(job.stdout_log, "wb") as out, open(job.stderr_log, "wb") as err:
            # cwd=BIN_DIR so hayabusa finds its sibling rules/ + config/ dirs.
            proc = subprocess.Popen(argv, stdout=out, stderr=err, cwd=str(BIN_DIR))
            job.exit_code = proc.wait()
    except FileNotFoundError as exc:
        job.publish({"type": "error", "stage": "spawn", "msg": str(exc)})
        job.status = "failed"
        job.exit_code = -1
    finally:
        # Let the tailer drain anything written between the last poll and exit.
        time.sleep(0.6)
        stop_event.set()
        tailer.join(timeout=2)

    if job.status != "failed":
        job.status = "done" if job.exit_code == 0 else "failed"
    job.finished_at = time.time()
    job.persist()
    job.publish({"type": "state", "job": job.to_dict()})
    job.publish({"type": "complete"})


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "HayabusaGUI/0.1"

    # Quiet the default access logging on the console.
    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- helpers ----------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, status=200, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, ctype: str | None = None):
        if not path.exists() or not path.is_file():
            self._send_text("not found", 404)
            return
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Local dev tool: never let the browser hold an old snapshot of our
        # JS/CSS. The cost is one extra round-trip per page load on
        # localhost, which is essentially free.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    # ---------- routing ----------

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        path = u.path

        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self._send_text("forbidden", 403)
                return
            self._send_file(target)
            return

        if path == "/api/health":
            self._send_json({
                "ok": True,
                "hayabusa": str(HAYABUSA_BIN),
                "version": self._hayabusa_version(),
                "rules_dir": str(RULES_DIR),
                "workspace": str(WORKSPACE),
            })
            return

        if path == "/api/workspace":
            self._send_json(self._list_workspace())
            return

        if path == "/api/jobs":
            # Source of truth is SQLite — survives restarts. Live in-memory
            # jobs may not yet be in SQLite if upsert hasn't happened, so we
            # also splice them in.
            seen: set[str] = set()
            out: list[dict] = []
            for row in STORE.list_jobs():
                d = dict(row)
                d["args"] = json.loads(d.pop("args_json") or "[]")
                seen.add(d["id"])
                out.append(d)
            with JOBS_LOCK:
                for jid, j in JOBS.items():
                    if jid not in seen:
                        out.append(j.to_dict())
            out.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
            self._send_json(out)
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})$", path)
        if m:
            jid = m.group(1)
            job = JOBS.get(jid)
            row = STORE.get_job(jid)
            if not job and not row:
                self._send_json({"error": "not_found"}, 404)
                return
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["200"])[0]), 2000)
            level = (qs.get("level", [""])[0] or "").lower() or None
            text = qs.get("q", [""])[0] or None
            verdict = qs.get("verdict", [""])[0] or None
            include_suppressed = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(
                              job_id=jid, level=level, text=text,
                              verdict=verdict,
                              include_suppressed=include_suppressed,
                              offset=offset, limit=limit)]
            total = STORE.count_detections(
                job_id=jid, level=level, verdict=verdict,
                include_suppressed=include_suppressed)
            job_view = job.to_dict() if job else dict(row)
            if not job:
                job_view["args"] = json.loads(job_view.pop("args_json") or "[]")
            stderr_path = JOBS_DIR / jid / "stderr.log"
            stdout_path = JOBS_DIR / jid / "stdout.log"
            summary_path = JOBS_DIR / jid / "summary.html"
            self._send_json({
                "job": job_view,
                "detections": detections,
                "total": total,
                "stderr_tail": self._tail_text(stderr_path, 4000),
                "stdout_tail": self._tail_text(stdout_path, 4000),
                "summary_available": summary_path.exists(),
            })
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})/stream$", path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                self._send_json({"error": "not_found"}, 404)
                return
            self._stream_sse(job)
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})/summary$", path)
        if m:
            jid = m.group(1)
            summary_path = JOBS_DIR / jid / "summary.html"
            if not summary_path.exists():
                self._send_text("not found", 404)
                return
            self._send_file(summary_path, "text/html; charset=utf-8")
            return

        if path == "/api/rules":
            self._send_json(self._summarize_rules())
            return

        if path == "/api/detections":
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["200"])[0]), 2000)
            filters = {
                "job_id": qs.get("job", [""])[0] or None,
                "level": (qs.get("level", [""])[0] or "").lower() or None,
                "rule_id": qs.get("rule_id", [""])[0] or None,
                "verdict": qs.get("verdict", [""])[0] or None,
                "text": qs.get("q", [""])[0] or None,
                "include_suppressed": qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes"),
            }
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(offset=offset, limit=limit, **filters)]
            total = STORE.count_detections(**filters)
            self._send_json({"detections": detections, "total": total,
                             "offset": offset, "limit": limit})
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/process_tree$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            qs = parse_qs(u.query)
            window = int(qs.get("window", ["10"])[0])
            try:
                tree = _process_tree.build_tree(STORE, jid, line_no,
                                                window_minutes=window)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json(tree)
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/detail$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            row = STORE.get_detection(jid, line_no)
            if not row:
                self._send_json({"error": "not_found"}, 404)
                return
            event = self._row_to_detection(row)
            rule_meta = None
            if row["rule_id"] and not row["rule_id"].startswith("h:"):
                rule_meta = RULE_INDEX.lookup(row["rule_id"])
            attack = _rule_index.attack_tags(rule_meta) if rule_meta else []
            related = STORE.related_on_host(
                row["computer"], row["ts"],
                window_minutes=5,
                exclude=(jid, line_no), limit=30)
            history = STORE.rule_history(row["rule_id"],
                                         exclude=(jid, line_no), limit=20)
            self._send_json({
                "detection": event,
                "rule": rule_meta,
                "attack_tags": attack,
                "related": related,
                "rule_history": history,
            })
            return

        if path == "/api/behavioral/anomalies":
            qs = parse_qs(u.query)
            top = min(int(qs.get("top", ["50"])[0]), 500)
            try:
                rows = _behavioral.analyse(STORE, top=top)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json({"anomalies": rows, "total": len(rows)})
            return

        if path == "/api/hunt/facets":
            # Distinct values for the hunt form's dropdowns. Cheap because
            # SQLite indexes channel / level / computer / rule_id and the
            # cardinality is small.
            c = STORE._conn()
            rows_lvl = list(c.execute(
                "SELECT DISTINCT level FROM detections WHERE level IS NOT NULL "
                "ORDER BY CASE level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC"))
            rows_ch = list(c.execute(
                "SELECT channel, COUNT(*) AS n FROM detections "
                "WHERE channel IS NOT NULL GROUP BY channel "
                "ORDER BY n DESC LIMIT 50"))
            rows_host = list(c.execute(
                "SELECT computer, COUNT(*) AS n FROM detections "
                "WHERE computer IS NOT NULL GROUP BY computer "
                "ORDER BY n DESC LIMIT 50"))
            rows_eid = list(c.execute(
                "SELECT event_id, COUNT(*) AS n FROM detections "
                "WHERE event_id IS NOT NULL GROUP BY event_id "
                "ORDER BY n DESC LIMIT 50"))
            self._send_json({
                "levels": [r["level"] for r in rows_lvl],
                "channels": [{"name": r["channel"], "count": r["n"]} for r in rows_ch],
                "computers": [{"name": r["computer"], "count": r["n"]} for r in rows_host],
                "event_ids": [{"id": r["event_id"], "count": r["n"]} for r in rows_eid],
            })
            return

        if path == "/api/hunt/search":
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["500"])[0]), 5000)
            kw = self._hunt_filters(qs)
            order = qs.get("order", ["ts_desc"])[0]
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(offset=offset, limit=limit,
                                                 order_by=order, **kw)]
            total = STORE.count_detections(**kw)
            self._send_json({"detections": detections, "total": total,
                             "offset": offset, "limit": limit,
                             "filters": kw})
            return

        if path == "/api/hunt/pivot":
            qs = parse_qs(u.query)
            dim = qs.get("dim", ["rule_id"])[0]
            limit = min(int(qs.get("limit", ["50"])[0]), 500)
            kw = self._hunt_filters(qs)
            try:
                rows = STORE.pivot_detections(dim, limit=limit, **kw)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"dim": dim, "rows": rows, "filters": kw})
            return

        if path == "/api/hunt/export":
            # Streaming-ish CSV of the search result. We cap at 50k rows
            # to keep the response sane; analysts asking for more should
            # filter further.
            qs = parse_qs(u.query)
            kw = self._hunt_filters(qs)
            limit = min(int(qs.get("limit", ["50000"])[0]), 50000)
            rows = STORE.query_detections(offset=0, limit=limit, **kw)
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["timestamp", "level", "rule_id", "rule_title",
                        "computer", "channel", "event_id",
                        "verdict", "suppressed", "job_id", "line_no"])
            for r in rows:
                w.writerow([
                    r["ts"] or "", r["level"] or "",
                    r["rule_id"] or "", r["rule_title"] or "",
                    r["computer"] or "", r["channel"] or "",
                    r["event_id"] or "",
                    r["verdict"] or "",
                    "yes" if r["suppression_id"] else "no",
                    r["job_id"], r["line_no"],
                ])
            data = buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads JP
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition",
                             "attachment; filename=hunt-results.csv")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/system/info":
            channels = _list_system_channels()
            total = sum((c.get("size") or 0) for c in channels if c.get("readable"))
            unreadable = sum(1 for c in channels if not c.get("readable"))
            self._send_json({
                "platform": sys.platform,
                "evtx_root": str(SYSTEM_EVTX_ROOT),
                "admin": _is_admin_windows(),
                "channels": channels,
                "total_size": total,
                "unreadable_count": unreadable,
                "snapshot_dir": str(SYSTEM_SNAPSHOT_DIR.relative_to(WORKSPACE)).replace("\\", "/"),
            })
            return

        if path == "/api/lookups":
            # We can't reach into the forked engine's in-memory table
            # registry from out of process, so we reconstruct the
            # (table-name → file → referencing-rules) graph by parsing
            # every rule's `lookup:` block. The output is the analyst's
            # view of what tables exist and which rules need them.
            #
            # Returned items represent declared TABLE NAMES, not files —
            # a file may participate in multiple tables, or a table name
            # may be declared by multiple rules pointing to different
            # files (last-write-wins in the engine; we surface the
            # divergence so it's visible).
            bindings: dict[str, dict] = {}  # name → {file, referenced_by, conflicts}
            unbound_files: list[Path] = []
            for rule_path in (RULES_DIR / "hayabusa").rglob("*.yml"):
                try:
                    body = rule_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "lookup:" not in body:
                    continue
                in_lookup = False
                cur_name = None
                for line in body.splitlines():
                    s = line.strip()
                    if not in_lookup:
                        if s == "lookup:" or s.startswith("lookup:"):
                            in_lookup = True
                        continue
                    # Exit lookup block on dedent to column 0 with a key
                    if line and not line.startswith(" ") and not line.startswith("\t") \
                            and not s.startswith("- "):
                        in_lookup = False
                        cur_name = None
                        continue
                    if s.startswith("- name:"):
                        cur_name = s.split(":", 1)[1].strip().strip('"').strip("'")
                    elif s.startswith("name:") and cur_name is None:
                        cur_name = s.split(":", 1)[1].strip().strip('"').strip("'")
                    elif s.startswith("file:") and cur_name is not None:
                        file_str = s.split(":", 1)[1].strip().strip('"').strip("'")
                        cand = (rule_path.parent / file_str).resolve()
                        b = bindings.setdefault(cur_name, {
                            "file_paths": set(), "referenced_by": []
                        })
                        b["file_paths"].add(cand)
                        if rule_path.name not in b["referenced_by"]:
                            b["referenced_by"].append(rule_path.name)
                        cur_name = None  # ready for the next entry
            # Build response.
            items = []
            for name, b in sorted(bindings.items()):
                # Pick a canonical file path (first that exists).
                paths = list(b["file_paths"])
                primary = next((p for p in paths if p.exists()), paths[0] if paths else None)
                entries = -1
                size = 0
                if primary and primary.exists():
                    try:
                        entries = sum(
                            1 for line in primary.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                            if line.strip() and not line.lstrip().startswith("#")
                        )
                        size = primary.stat().st_size
                    except OSError:
                        pass
                items.append({
                    "name": name,
                    "filename": primary.name if primary else "",
                    "rel": str(primary.relative_to(ROOT)).replace("\\", "/")
                            if primary and ROOT in primary.parents else str(primary or ""),
                    "exists": bool(primary and primary.exists()),
                    "entries": entries,
                    "size": size,
                    "referenced_by": b["referenced_by"],
                    "binding_count": len(paths),
                })
            # Also report files in lookups/ that no rule references.
            referenced_paths = {p for b in bindings.values() for p in b["file_paths"]}
            for p in sorted(LOOKUPS_DIR.glob("*")) if LOOKUPS_DIR.exists() else []:
                if p.is_file() and p.resolve() not in referenced_paths:
                    unbound_files.append({
                        "filename": p.name,
                        "rel": str(p.relative_to(ROOT)).replace("\\", "/"),
                        "size": p.stat().st_size,
                    })
            self._send_json({"lookups": items, "unbound_files": unbound_files,
                             "dir": str(LOOKUPS_DIR)})
            return

        if path == "/api/rule_feedback":
            rows = STORE.rule_feedback()
            self._send_json([dict(r) for r in rows])
            return

        if path == "/api/stats":
            qs = parse_qs(u.query)
            job_id = qs.get("job", [""])[0] or None
            include_suppressed = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            bucket = qs.get("bucket", ["hour"])[0]
            if bucket not in ("minute", "hour", "day"):
                bucket = "hour"
            by_level = STORE.stats_by_level(job_id, include_suppressed)
            total = sum(by_level.values())
            crit_high = by_level.get("critical", 0) + by_level.get("high", 0)
            self._send_json({
                "scope": {"job_id": job_id, "include_suppressed": include_suppressed,
                          "bucket": bucket},
                "totals": {
                    "detections": total,
                    "critical_high": crit_high,
                    "unique_computers": STORE.stats_unique("computer", job_id, include_suppressed),
                    "unique_rules": STORE.stats_unique("rule_id", job_id, include_suppressed),
                },
                "by_level": by_level,
                "top_rules": STORE.stats_top_rules(job_id, 12, include_suppressed),
                "top_computers": STORE.stats_top_computers(job_id, 10, include_suppressed),
                "timeline": STORE.stats_timeline(job_id, bucket, include_suppressed),
            })
            return

        if path == "/api/suppressions":
            rows = STORE.list_suppressions()
            out = []
            for r in rows:
                d = dict(r)
                # Echo back the original glob shape so the UI can show a
                # human-friendly pattern rather than the LIKE-escaped form.
                d["computer"] = _store.Store._like_to_glob(d.get("computer_like"))
                out.append(d)
            self._send_json(out)
            return

        self._send_text("not found", 404)

    def do_DELETE(self):  # noqa: N802
        u = urlparse(self.path)
        m = re.match(r"^/api/suppressions/(\d+)$", u.path)
        if m:
            sid = int(m.group(1))
            if STORE.remove_suppression(sid):
                self._send_json({"deleted": sid})
            else:
                self._send_json({"error": "not_found"}, 404)
            return
        self._send_text("not found", 404)

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        path = u.path

        if path == "/api/scan":
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            job = Job("scan", [])
            register_job(job)
            threading.Thread(target=run_job, args=(job, params), daemon=True).start()
            self._send_json({"job_id": job.id}, 202)
            return

        if path == "/api/upload":
            self._handle_upload()
            return

        if path == "/api/suppressions":
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            try:
                sid = STORE.add_suppression(
                    rule_id=params.get("rule_id"),
                    computer_glob=params.get("computer"),
                    reason=params.get("reason"),
                    created_by=params.get("created_by") or "analyst",
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"id": sid}, 201)
            return

        if path == "/api/system/import":
            # Copy the selected system EVTX channels into
            # workspace/uploads/system-snapshot/. Two reasons we do this
            # rather than scanning System32 in place:
            #   * the analyst can re-run scans against the same point-in-time
            #     snapshot without re-elevating each time;
            #   * Hayabusa locks files briefly during scan, and we never
            #     want to hand it a path inside C:\Windows\System32.
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            names = params.get("channels") or []
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                self._send_json({"error": "channels must be a list of strings"}, 400)
                return
            if not names:
                self._send_json({"error": "no channels selected"}, 400)
                return
            SYSTEM_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            saved, errors = [], []
            for fname in names:
                # Defensive: file name only, no traversal, only known suffix.
                if "/" in fname or "\\" in fname or ".." in fname:
                    errors.append({"name": fname, "error": "invalid name"})
                    continue
                if not fname.lower().endswith(".evtx"):
                    errors.append({"name": fname, "error": "not an .evtx file"})
                    continue
                src = SYSTEM_EVTX_ROOT / fname
                if not src.exists():
                    errors.append({"name": fname, "error": "not found"})
                    continue
                dst = SYSTEM_SNAPSHOT_DIR / fname
                try:
                    shutil.copy2(src, dst)
                    saved.append({
                        "name": fname,
                        "size": dst.stat().st_size,
                        "rel": str(dst.relative_to(WORKSPACE)).replace("\\", "/"),
                    })
                except OSError as exc:
                    errors.append({"name": fname, "error": str(exc)})
            self._send_json({"saved": saved, "errors": errors,
                             "snapshot_dir": str(SYSTEM_SNAPSHOT_DIR.relative_to(WORKSPACE)).replace("\\", "/")})
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/feedback$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            verdict = params.get("verdict")
            if verdict not in (_store.VERDICT_TP, _store.VERDICT_FP, None, ""):
                self._send_json({"error": "invalid verdict"}, 400)
                return
            try:
                result = STORE.record_feedback(jid, line_no, verdict or None)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            if result is None:
                self._send_json({"error": "detection not found"}, 404)
                return
            self._send_json(result)
            return

        self._send_text("not found", 404)

    # ---------- domain helpers ----------

    def _hayabusa_version(self) -> str:
        try:
            out = subprocess.check_output([str(HAYABUSA_BIN), "help"],
                                          cwd=str(BIN_DIR), timeout=10,
                                          stderr=subprocess.STDOUT).decode("utf-8", "replace")
            for line in out.splitlines():
                if line.startswith("Hayabusa"):
                    return line.strip()
        except Exception:
            pass
        return "unknown"

    def _list_workspace(self):
        def walk(base: Path):
            out = []
            if not base.exists():
                return out
            for p in sorted(base.iterdir()):
                if p.is_dir():
                    out.append({"name": p.name, "type": "dir",
                                "rel": str(p.relative_to(WORKSPACE)).replace("\\", "/")})
                else:
                    out.append({"name": p.name, "type": "file",
                                "rel": str(p.relative_to(WORKSPACE)).replace("\\", "/"),
                                "size": p.stat().st_size})
            return out
        return {"uploads": walk(UPLOAD_DIR), "results": walk(RESULTS_DIR)}

    def _summarize_rules(self):
        """Walk the bundled rules dir and bucket by level + category."""
        if not RULES_DIR.exists():
            return {"total": 0, "by_level": {}, "by_category": {}}
        levels: dict[str, int] = {}
        cats: dict[str, int] = {}
        total = 0
        # Hayabusa bundles ~3000 rules; this scan is best-effort and only inspects YAML headers.
        for path in RULES_DIR.rglob("*.yml"):
            total += 1
            level = None
            category = path.parent.name
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for _ in range(60):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("level:"):
                            level = line.split(":", 1)[1].strip()
                            break
            except OSError:
                pass
            levels[level or "unknown"] = levels.get(level or "unknown", 0) + 1
            cats[category] = cats.get(category, 0) + 1
        return {"total": total, "by_level": levels, "by_category": cats}

    def _hunt_filters(self, qs: dict) -> dict:
        """Translate the hunt URL query string into store kwargs.

        Multi-valued params (level=critical&level=high) come through as
        lists; we forward them as `levels=[...]`. Empty strings are
        normalised to None so the store doesn't AND-in vacuous clauses.
        """
        def first(k):
            v = qs.get(k, [""])[0]
            return v if v else None
        def list_(k):
            vs = [v for v in qs.get(k, []) if v]
            return vs or None
        return {
            "computer": first("computer"),
            "computer_glob": first("host"),    # short alias for UI
            "channel": first("channel"),
            "event_id": first("eid"),
            "levels": list_("level"),
            "rule_id": first("rule_id"),
            "rule_ids": list_("rule_ids"),
            "ts_from": first("from"),
            "ts_to": first("to"),
            "verdict": first("verdict"),
            "text": first("q"),
            "include_suppressed":
                qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes"),
            "job_id": first("job"),
        }

    def _row_to_detection(self, row) -> dict:
        """
        Reify a sqlite row into the JSON shape the UI consumes.

        The full Hayabusa event is unpacked from raw_json so the existing
        detail pane keeps working unchanged. The verdict + line_no fields
        are injected so the UI can post feedback.
        """
        try:
            event = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            event = {}
        event["_job_id"] = row["job_id"]
        event["_line_no"] = row["line_no"]
        event["_verdict"] = row["verdict"]
        event["_rule_id"] = row["rule_id"]
        # Suppression columns are present when the query went through the
        # _SUPP_JOIN path (the only callers in production).
        try:
            sid = row["suppression_id"]
        except (IndexError, KeyError):
            sid = None
        if sid is not None:
            event["_suppressed"] = True
            event["_suppression_reason"] = row["suppression_reason"]
        else:
            event["_suppressed"] = False
        return event

    def _tail_text(self, path: Path, max_bytes: int) -> str:
        if not path.exists():
            return ""
        try:
            size = path.stat().st_size
            with open(path, "rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _stream_sse(self, job: Job):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = job.subscribe()
        try:
            # If the job is already done, deliver one snapshot and close.
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    if job.status in ("done", "failed", "cancelled"):
                        return
                    continue
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
                if json.loads(payload[6:].strip()).get("type") == "complete":
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_upload(self):
        """
        Minimal multipart parser for a single file field named 'file'.

        We avoid the cgi module (deprecated in 3.13) and only handle the one
        upload shape the UI produces.
        """
        ctype = self.headers.get("Content-Type", "")
        m = re.match(r"^multipart/form-data;\s*boundary=(.+)$", ctype)
        if not m:
            self._send_json({"error": "expected multipart/form-data"}, 400)
            return
        boundary = ("--" + m.group(1)).encode("ascii")
        body = self._read_body()
        if not body:
            self._send_json({"error": "empty body"}, 400)
            return
        parts = body.split(boundary)
        saved = []
        for part in parts:
            if not part or part in (b"--\r\n", b"--"):
                continue
            part = part.lstrip(b"\r\n")
            if part.endswith(b"\r\n"):
                part = part[:-2]
            try:
                head, payload = part.split(b"\r\n\r\n", 1)
            except ValueError:
                continue
            head_text = head.decode("utf-8", "replace")
            fn_match = re.search(r'filename="([^"]+)"', head_text)
            if not fn_match:
                continue
            filename = os.path.basename(unquote(fn_match.group(1)))
            if not filename or not re.match(r"^[A-Za-z0-9._\-]+$", filename):
                continue
            target = UPLOAD_DIR / filename
            with open(target, "wb") as f:
                f.write(payload)
            saved.append({"name": filename, "size": len(payload),
                          "rel": str(target.relative_to(WORKSPACE)).replace("\\", "/")})
        if not saved:
            self._send_json({"error": "no file part found"}, 400)
            return
        self._send_json({"saved": saved})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def pick_port(preferred: int) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port


def boot_reindex():
    """
    Replay any job timeline JSONLs on disk into SQLite, and fold in any
    suppression snapshots so a wiped DB can be restored from version
    control. Both operations are idempotent.
    """
    report = _store.reindex_jobs_dir(STORE, JOBS_DIR)
    if report:
        total = sum(report.values())
        print(f"  Reindex: {total} new detections across {len(report)} job(s)",
              flush=True)
    imported = STORE.import_suppression_snapshots()
    if imported:
        print(f"  Imported {imported} suppression(s) from snapshot files",
              flush=True)


def main():
    boot_reindex()
    port = pick_port(int(os.environ.get("HAYABUSA_GUI_PORT", "8787")))
    host = "127.0.0.1"
    print(f"\n  Hayabusa GUI")
    print(f"  Binary : {HAYABUSA_BIN}")
    print(f"  Rules  : {RULES_DIR}")
    print(f"  DB     : {DB_PATH}")
    print(f"  Listen : http://{host}:{port}\n", flush=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
