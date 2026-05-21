"""
Fetch and normalize external IoC feeds into `lookups/<feed>.txt`.

Why "normalize"
---------------
Sigma rules with our `lookup:` extension expect a flat text file: one
value per line, comments allowed via `#`, case-folded at match time.
The wild internet ships IoCs in CSV / JSON / TSV / pipe-separated /
god-knows-what. This module reads the manifest at lookups/feeds.yml and
collapses everything down to that single uniform text shape.

Design rules
------------
* No third-party dependencies. We rely on urllib + csv + a tiny YAML
  parser (no PyYAML — single-file deployment matters more than YAML
  expressiveness).
* Network is the failure mode. A 5 s connect timeout and 60 s read
  timeout keep the GUI responsive when a feed is down. On any failure
  we DO NOT touch the existing on-disk file — analysts keep matching
  against the last-known-good list instead of getting blank coverage.
* Each feed write is atomic (.tmp + replace) so a partial run can
  never leave a half-written file that produces silent false negatives.
* A sibling `<output>.meta.json` records when each feed was fetched,
  how many entries landed, and any error from the most recent attempt.
  The GUI surfaces these to the analyst.
"""

from __future__ import annotations

import csv
import io
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

# We don't ship PyYAML to keep stdlib-only. This parser handles the
# narrow subset our feeds.yml uses (top-level list, scalar fields,
# optional pipe-style block scalars). It's deliberately not a YAML
# implementation — if someone hand-edits feeds.yml with anchors or
# flow mappings, the failure is loud (no values).
def _load_feeds_yaml(path: Path) -> list[dict[str, Any]]:
    feeds: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_block: str | None = None
    block_lines: list[str] = []
    in_list_field: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)

        # Close any open block-scalar on a top-level line.
        if in_block is not None and (indent == 0 or stripped.startswith("- ")):
            if cur is not None:
                cur[in_block] = "\n".join(block_lines).strip()
            in_block = None; block_lines = []

        if not stripped or stripped.startswith("#"):
            if in_block is not None:
                block_lines.append(line[indent:])
            continue

        # Inline list item: "- name: foo"
        if stripped.startswith("- "):
            if cur is not None:
                feeds.append(cur)
            cur = {}
            stripped = stripped[2:]
            indent += 2  # treat the "- " prefix as indentation for the kv below

        if cur is None:
            # Top-level keys like "feeds:" — we recognise but ignore them.
            continue

        if in_list_field is not None:
            if stripped.startswith("- "):
                cur.setdefault(in_list_field, []).append(
                    stripped[2:].strip().strip("'\""))
                continue
            in_list_field = None

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip(); val = val.strip()
            if val == "":
                # Could be block scalar opening, or a list-valued key.
                # Look ahead: if next non-empty line starts with "- ",
                # it's a list. We can't peek here cleanly, so we set a
                # flag and resolve on the next iteration.
                in_list_field = key
                continue
            if val in ("|", ">", "|+", "|-"):
                in_block = key
                block_lines = []
                continue
            cur[key] = _coerce(val)
    if in_block is not None and cur is not None:
        cur[in_block] = "\n".join(block_lines).strip()
    if cur is not None:
        feeds.append(cur)
    # Filter to dicts that look like feeds (must have url + output).
    return [f for f in feeds if f.get("url") and f.get("output")]


def _coerce(v: str):
    """Convert a YAML scalar string to its likely Python type."""
    # Strip trailing inline comment when the value is not entirely quoted.
    # For quoted values, look for the closing quote first and only consider
    # `#` content past that as a comment.
    if v.startswith(("'", '"')):
        q = v[0]
        end = v.find(q, 1)
        if end >= 0:
            v = v[:end + 1]   # discard anything past closing quote (incl. # ...)
    else:
        hash_pos = v.find(" #")
        if hash_pos >= 0:
            v = v[:hash_pos].rstrip()
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        return v[1:-1]
    if v.lower() in ("true", "yes"): return True
    if v.lower() in ("false", "no"): return False
    if v.lower() in ("null", "~"):   return None
    try: return int(v)
    except ValueError: pass
    try: return float(v)
    except ValueError: pass
    return v


# -- HTTP -------------------------------------------------------------------

_USER_AGENT = "hayabusa-fx feed-fetcher/0.1 (+local DFIR tool)"


def _http_get(url: str, *, connect_timeout: float = 5.0,
              read_timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    # We override the global default timeout via socket so the connect
    # phase honours `connect_timeout`. urlopen's `timeout` covers the
    # whole transfer, set to the larger value.
    socket.setdefaulttimeout(connect_timeout)
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=read_timeout, context=ctx) as resp:
            return resp.read()
    finally:
        socket.setdefaulttimeout(None)


# -- parsers ----------------------------------------------------------------

def _parse_text(blob: bytes, *, skip_prefix: list[str] | None) -> Iterable[str]:
    skip = tuple(skip_prefix or [])
    for line in blob.decode("utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or (skip and s.startswith(skip)):
            continue
        # Drop any inline comment after `#` for `key  # note` style lines,
        # but keep `#` if it's inside a URL (URLs have them in fragments).
        # The split is safe because lookup-style feeds don't use shell
        # quoting; we just take the first whitespace-stripped token if
        # the line has multiple columns separated by space/tab.
        if "\t" in s:
            s = s.split("\t", 1)[0].strip()
        elif " " in s and not s.startswith("http"):
            s = s.split(" ", 1)[0].strip()
        if s:
            yield s


def _parse_csv(blob: bytes, *, column: str | None) -> Iterable[str]:
    if not column:
        return []
    reader = csv.DictReader(io.StringIO(blob.decode("utf-8", errors="replace")))
    # CSV headers can be case-inconsistent across feeds. Match
    # case-insensitively but emit the value verbatim.
    lookup_key = None
    for row in reader:
        if lookup_key is None:
            for k in row.keys():
                if k and k.strip().lower() == column.lower():
                    lookup_key = k
                    break
            if lookup_key is None:
                return  # column not found; abort cleanly
        v = (row.get(lookup_key) or "").strip()
        if v:
            yield v


def _parse_json(blob: bytes, *, column: str | None) -> Iterable[str]:
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return
    items = data if isinstance(data, list) else data.get("data") or []
    for entry in items:
        if isinstance(entry, dict) and column:
            v = entry.get(column)
            if isinstance(v, str) and v.strip():
                yield v.strip()
        elif isinstance(entry, str) and entry.strip():
            yield entry.strip()


# -- fetch + write ----------------------------------------------------------

def fetch_one(feed: dict[str, Any], lookups_dir: Path) -> dict[str, Any]:
    """
    Fetch a single feed; return a metadata dict that the caller can drop
    into `<output>.meta.json`. NEVER raises — failures are reported via
    the `error` field so the orchestrating CLI / endpoint can continue.
    """
    out_path = lookups_dir / feed["output"]
    meta = {
        "name": feed.get("name"),
        "url": feed.get("url"),
        "output": feed["output"],
        "fetched_at": time.time(),
        "entries": None,
        "bytes_in": None,
        "error": None,
        "elapsed_sec": None,
    }
    started = time.monotonic()
    try:
        blob = _http_get(feed["url"])
        meta["bytes_in"] = len(blob)
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
        meta["error"] = f"network: {exc}"
        meta["elapsed_sec"] = round(time.monotonic() - started, 2)
        return meta

    parser = feed.get("parser", "text")
    try:
        if parser == "csv":
            raw_values = _parse_csv(blob, column=feed.get("column"))
        elif parser == "json":
            raw_values = _parse_json(blob, column=feed.get("column"))
        else:
            raw_values = _parse_text(blob, skip_prefix=feed.get("skip_prefix"))
        # Some feeds pack multiple values into one cell (LOLDrivers CSV
        # puts the per-driver sample hashes into KnownVulnerableSamples_SHA256
        # as comma-separated strings). We support a per-feed `split:` option
        # to break those out.
        splitter = feed.get("split")
        # De-dupe + normalise.
        seen: set[str] = set()
        cleaned: list[str] = []
        min_len = int(feed.get("min_len") or 0)
        lowercase = bool(feed.get("lowercase"))
        for raw_v in raw_values:
            chunks = [c.strip() for c in raw_v.split(splitter)] if splitter \
                     else [raw_v.strip()]
            for v in chunks:
                if not v:
                    continue
                if lowercase:
                    v = v.lower()
                if len(v) < min_len:
                    continue
                if v not in seen:
                    seen.add(v)
                    cleaned.append(v)
        # Sort for stable diffs on disk.
        cleaned.sort()
    except Exception as exc:  # noqa: BLE001
        meta["error"] = f"parse: {exc}"
        meta["elapsed_sec"] = round(time.monotonic() - started, 2)
        return meta

    # Write atomically: tmp + replace so a crashed run never leaves a
    # truncated lookup file. We also leave the existing file untouched
    # if the new contents would be empty — empty feed = probable bug
    # upstream, not a real "no IoCs known" state.
    if not cleaned:
        meta["error"] = "empty result; existing file untouched"
        meta["entries"] = 0
        meta["elapsed_sec"] = round(time.monotonic() - started, 2)
        return meta

    header = [
        f"# {feed.get('name', feed['output'])}",
        f"# Source: {feed['url']}",
        f"# Fetched: {time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(meta['fetched_at']))}",
        f"# Entries: {len(cleaned)}",
        "",
    ]
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text("\n".join(header + cleaned) + "\n", encoding="utf-8")
    tmp.replace(out_path)

    meta["entries"] = len(cleaned)
    meta["elapsed_sec"] = round(time.monotonic() - started, 2)
    return meta


def fetch_all(lookups_dir: Path, manifest: Path | None = None,
              filter_names: list[str] | None = None) -> list[dict[str, Any]]:
    manifest = manifest or (lookups_dir / "feeds.yml")
    if not manifest.exists():
        return [{"error": f"no manifest at {manifest}"}]
    feeds = _load_feeds_yaml(manifest)
    if filter_names:
        feeds = [f for f in feeds if f.get("name") in filter_names]
    lookups_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for feed in feeds:
        result = fetch_one(feed, lookups_dir)
        results.append(result)
        # Persist meta sidecar.
        try:
            meta_path = lookups_dir / (feed["output"] + ".meta.json")
            meta_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError:
            pass
    return results


def load_meta(lookups_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {feed_name: meta_dict} by reading all sidecar files."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(lookups_dir.glob("*.meta.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            out[meta.get("name", p.stem.replace(".meta", ""))] = meta
        except (OSError, json.JSONDecodeError):
            continue
    return out
