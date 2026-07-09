"""
Process-tree builder for the detection detail view.

Given a focal detection, we collect every Sysmon EID 1 (Process Create)
event that fired on the same host within a configurable time window, then
stitch them into a parent-child graph keyed on ProcessGuid.

Why ProcessGuid and not ProcessId
---------------------------------
Windows recycles PIDs aggressively — within a 10-minute window the same
PID can refer to multiple processes. ProcessGuid is unique per process
lifetime and is what every Sysmon-aware tool keys off. We fall back to
PID-based linking when ProcessGuid is missing (older Sysmon configs,
or non-Sysmon channels).

Data sources
------------
Hayabusa's JSON output gives us either:
  * `Details` — a `¦`-separated key:value string (always present)
  * `ExtraFieldInfo` — a nested dict with raw EventData (present when the
    scan ran with `-p verbose`; absent on older `standard` scans)

We parse both, merge their values, and prefer ExtraFieldInfo when keys
collide because it's the unparsed truth from EvtRender.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

# Sysmon EID 1 = Process Create. The other process-related EID worth
# folding in is 5 (Process Terminated) but we skip it here — it doesn't
# carry parent info and would just inflate the tree.
PROCESS_CREATE_EID = "1"
PROCESS_CHANNEL = "Microsoft-Windows-Sysmon/Operational"
# Windows Security "A new process has been created". Has no ProcessGuid, only
# PIDs (hex). Fields: NewProcessName / NewProcessId / ProcessId (parent) /
# ParentProcessName / SubjectUserName / CommandLine (if audited).
SECURITY_PROC_EID = "4688"

# Maximum nodes returned. A busy host can produce hundreds of process
# creates in 10 minutes; rendering thousands of HTML nodes hangs the
# browser without adding analyst value.
MAX_NODES = 400


def _coerce_details(d: Any) -> dict[str, Any]:
    """
    Hayabusa's `Details` field can come back as either:

      * A dict — when the rule's `details:` template was structured, OR
        when the scan used `-p verbose` / `-p all-field-info`. Most
        modern process_creation rules emit dicts.
      * A string with `¦`-separated `key: value` fragments — older
        profiles or rules that explicitly stringify everything.

    We accept both and return a flat dict.
    """
    if isinstance(d, dict):
        return d
    out: dict[str, Any] = {}
    if not isinstance(d, str) or not d:
        return out
    sep = "¦" if "¦" in d else None
    if not sep:
        return out
    for seg in d.split(sep):
        if ":" not in seg:
            continue
        k, _, v = seg.partition(":")
        out[k.strip()] = v.strip()
    return out


# These are the EventData field names Sysmon emits — case-sensitive,
# stable across versions. We declare the full set so the tree can show
# anything useful that's available.
SYSMON_FIELDS = (
    "ProcessGuid", "ProcessId", "Image", "CommandLine", "CurrentDirectory",
    "User", "LogonId", "IntegrityLevel", "Hashes", "OriginalFileName",
    "Description", "Product", "Company", "FileVersion",
    "ParentProcessGuid", "ParentProcessId", "ParentImage", "ParentCommandLine",
    "ParentUser", "TerminalSessionId",
)


def _merge_fields(*sources: dict[str, Any]) -> dict[str, Any]:
    """Union the relevant Sysmon fields across multiple dicts. Later
    sources win — pass ExtraFieldInfo last so it overrides Details."""
    out: dict[str, Any] = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in SYSMON_FIELDS:
            v = src.get(k)
            if v is not None and v != "":
                out[k] = v
    return out


def _extract_process_record(raw_json_str: str) -> dict[str, Any] | None:
    """Pull a process-create record out of one Hayabusa JSON line."""
    try:
        ev = json.loads(raw_json_str)
    except (TypeError, json.JSONDecodeError):
        return None
    if str(ev.get("EventID", "")) != PROCESS_CREATE_EID:
        return None
    # Channel check is forgiving: some EID 1 sources (CarbonBlack, etc.)
    # use a different channel name. If Channel is missing we still try.
    channel = ev.get("Channel") or ""
    if channel and channel != PROCESS_CHANNEL:
        return None
    # Merge from all available shape options. Order is important: later
    # sources win on key collision. ExtraFieldInfo last because it's the
    # raw EvtRender truth when present.
    detail_dict = _coerce_details(ev.get("Details"))
    extra = ev.get("ExtraFieldInfo") or {}
    eventdata = ev.get("EventData") or {}
    allfield = ev.get("AllFieldInfo") or {}
    merged = _merge_fields(detail_dict, eventdata, allfield, extra)
    if not merged:
        return None
    merged["_ts"] = ev.get("Timestamp")
    merged["_computer"] = ev.get("Computer")
    return merged


_TS_PATTERNS = [
    "%Y-%m-%d %H:%M:%S.%f %z",
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
]


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in _TS_PATTERNS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def build_tree(store, job_id: str, line_no: int,
               window_minutes: int = 10) -> dict[str, Any]:
    """
    Assemble the process tree for the host of the focal detection.

    Returns a JSON-friendly dict::

        {
          "focal":     {...focal detection summary...},
          "host":      "WS-ALICE-01",
          "window":    {"from": "...", "to": "..."},
          "nodes_seen": 42,
          "truncated": false,
          "roots":     [ <node>, ... ],   # forest if multiple disconnected
          "focal_guid":  "..." or null,
        }

    Each node has shape::

        {
          "guid": "...", "pid": "...", "image": "...", "cmdline": "...",
          "user": "...", "integrity": "...", "hashes": "...",
          "ts": "...", "is_focal": bool,
          "children": [ ... ],
          "detection": { "job_id": ..., "line_no": ..., "level": ..., "rule_title": ... } or null
        }

    The detection link is present only when one of our rules fired on that
    process create — that's the bridge from a Sysmon record to a Hayabusa
    detection, and it's what lets the analyst click straight through.
    """
    focal = store.get_detection(job_id, line_no)
    if not focal:
        return {"error": "focal detection not found"}

    host = focal["computer"]
    if not host:
        return {"error": "focal detection has no computer name; cannot scope tree"}

    ts0 = _parse_ts(focal["ts"])
    if ts0 is None:
        # Fall back: query the whole job rather than refuse — better
        # than returning nothing.
        ts_from = ts_to = None
    else:
        # CRITICAL: SQLite compares timestamps as strings (lexicographic).
        # The DB stores whatever Hayabusa emitted — typically with a SPACE
        # between date and time ("2020-10-18 01:27:10.464 +09:00"), but
        # some events use "T". We sniff the focal's format and reproduce
        # it so the >=/<= range comparisons actually overlap.
        sep = "T" if (focal["ts"] and "T" in focal["ts"][:11]) else " "
        ts_from = (ts0 - timedelta(minutes=window_minutes)).strftime(f"%Y-%m-%d{sep}%H:%M:%S")
        ts_to   = (ts0 + timedelta(minutes=window_minutes)).strftime(f"%Y-%m-%d{sep}%H:%M:%S.999999")

    # Pull all detections on this host in the window. We don't restrict
    # by channel/EID at the store layer because the `event_id` column is
    # populated from the JSON's EventID field — querying for "1" would
    # exclude alternative channels (Defender, CarbonBlack) that also
    # log process creates. Better to over-fetch and filter in Python.
    candidates = store.query_detections(
        computer=host, ts_from=ts_from, ts_to=ts_to,
        include_suppressed=True,        # the focal might itself be suppressed
        limit=5000,
        order_by="ts_asc",
    )

    by_guid: dict[str, dict[str, Any]] = {}
    by_pid: dict[str, dict[str, Any]] = {}     # fallback when no GUIDs
    detection_of_guid: dict[str, dict[str, Any]] = {}
    detection_of_pid: dict[str, dict[str, Any]] = {}
    truncated = False

    for row in candidates:
        rec = _extract_process_record(row["raw_json"])
        if not rec:
            continue
        guid = rec.get("ProcessGuid") or ""
        pid = str(rec.get("ProcessId") or "")
        parent_guid = rec.get("ParentProcessGuid") or ""
        parent_pid = str(rec.get("ParentProcessId") or "")

        if not guid and not pid:
            continue

        node = {
            "guid": guid,
            "pid": pid,
            "image": rec.get("Image") or "",
            "cmdline": rec.get("CommandLine") or "",
            "user": rec.get("User") or "",
            "integrity": rec.get("IntegrityLevel") or "",
            "hashes": rec.get("Hashes") or "",
            "parent_guid": parent_guid,
            "parent_pid": parent_pid,
            "parent_image": rec.get("ParentImage") or "",
            "ts": rec.get("_ts") or row["ts"],
            "is_focal": (row["job_id"] == job_id and row["line_no"] == line_no),
            "detection": {
                "job_id":    row["job_id"],
                "line_no":   row["line_no"],
                "level":     row["level"],
                "rule_title": row["rule_title"],
                "rule_id":   row["rule_id"],
            } if row["rule_id"] else None,
            "children": [],
        }
        # We keep the most-detailed record per GUID; the same process
        # may show up across multiple rules (each row a separate hit).
        if guid:
            existing = by_guid.get(guid)
            if not existing or len(node["cmdline"]) > len(existing.get("cmdline") or ""):
                by_guid[guid] = node
            # Preserve focal + detection link from the rule-firing row.
            if node["is_focal"]:
                by_guid[guid]["is_focal"] = True
            if node["detection"] and not by_guid[guid].get("detection"):
                by_guid[guid]["detection"] = node["detection"]
        elif pid:
            by_pid.setdefault(pid, node)

        if len(by_guid) + len(by_pid) >= MAX_NODES:
            truncated = True
            break

    # Stitch parent-child links.
    roots: list[dict[str, Any]] = []
    for guid, node in by_guid.items():
        pg = node["parent_guid"]
        if pg and pg in by_guid:
            by_guid[pg]["children"].append(node)
        else:
            roots.append(node)
    # PID-only fallback: only if we have ZERO GUIDs (mixed mode is too
    # error-prone to bother with).
    if not by_guid and by_pid:
        for pid, node in by_pid.items():
            pp = node["parent_pid"]
            if pp and pp in by_pid:
                by_pid[pp]["children"].append(node)
            else:
                roots.append(node)

    # Sort each level deterministically by timestamp ascending.
    def _sort(node):
        node["children"].sort(key=lambda c: c.get("ts") or "")
        for child in node["children"]:
            _sort(child)
    roots.sort(key=lambda r: r.get("ts") or "")
    for r in roots:
        _sort(r)

    focal_guid = None
    for guid, node in by_guid.items():
        if node.get("is_focal"):
            focal_guid = guid
            break

    return {
        "focal": {
            "job_id": focal["job_id"],
            "line_no": focal["line_no"],
            "ts": focal["ts"],
            "rule_title": focal["rule_title"],
            "level": focal["level"],
            "computer": focal["computer"],
            "channel": focal["channel"],
            "event_id": focal["event_id"],
        },
        "host": host,
        "window": {"from": ts_from, "to": ts_to, "minutes": window_minutes},
        "nodes_seen": len(by_guid) + len(by_pid),
        "truncated": truncated,
        "roots": roots,
        "focal_guid": focal_guid,
        "key_mode": "guid" if by_guid else ("pid" if by_pid else "empty"),
    }


def _basename(path: str) -> str:
    """`"C:\\dir\\app.exe" --flag` → `app.exe`。実行ファイル名だけ抜く。"""
    s = str(path or "").strip()
    if not s:
        return ""
    if s[0] in "\"'":
        end = s.find(s[0], 1)
        s = s[1:end] if end > 0 else s[1:]
    else:
        s = s.split(" ")[0]
    s = s.replace("\\", "/").rstrip("/")
    return s.rsplit("/", 1)[-1] or s


def _proc_record_any(raw_json_str: str) -> dict[str, Any] | None:
    """Extract a process-create record from a Sysmon EID 1 *or* a Windows
    Security EID 4688 event. Returns a normalised dict or None.

    Unlike `_extract_process_record` (Sysmon-only, used by the focal tree),
    this also understands 4688 so the host-level tree works on machines that
    only have Security-log process auditing (no Sysmon)."""
    try:
        ev = json.loads(raw_json_str)
    except (TypeError, json.JSONDecodeError):
        return None
    eid = str(ev.get("EventID", ""))
    combo: dict[str, Any] = {}
    for src in (_coerce_details(ev.get("Details")),
                ev.get("EventData") or {}, ev.get("AllFieldInfo") or {},
                ev.get("ExtraFieldInfo") or {}):
        if isinstance(src, dict):
            for k, v in src.items():
                if v not in (None, ""):
                    combo[k] = v

    if eid == PROCESS_CREATE_EID:
        rec = {
            "guid": combo.get("ProcessGuid") or "",
            "pid": str(combo.get("ProcessId") or ""),
            "parent_guid": combo.get("ParentProcessGuid") or "",
            "parent_pid": str(combo.get("ParentProcessId") or ""),
            "image": combo.get("Image") or "",
            "cmdline": combo.get("CommandLine") or "",
            "user": combo.get("User") or "",
            "integrity": combo.get("IntegrityLevel") or "",
            "parent_image": combo.get("ParentImage") or "",
        }
    elif eid == SECURITY_PROC_EID:
        rec = {
            "guid": "",
            "pid": str(combo.get("NewProcessId") or ""),
            "parent_guid": "",
            "parent_pid": str(combo.get("ProcessId") or ""),
            "image": combo.get("NewProcessName") or "",
            "cmdline": combo.get("CommandLine") or combo.get("Proc") or "",
            "user": combo.get("SubjectUserName") or combo.get("TargetUserName") or "",
            "integrity": combo.get("MandatoryLabel") or combo.get("TokenElevationType") or "",
            "parent_image": combo.get("ParentProcessName") or "",
        }
    else:
        return None

    if not rec["pid"] and not rec["guid"]:
        return None
    rec["_ts"] = ev.get("Timestamp")
    # ATT&CK タグ/戦術（あれば）— 検知ノードの日本語説明生成に使う。
    rec["_tags"] = ev.get("MitreTags") or []
    rec["_tactics"] = ev.get("MitreTactics") or []
    return rec


def build_host_tree(store, computer: str, job_id: str | None = None,
                    include_suppressed: bool = False) -> dict[str, Any]:
    """Build the whole-host process tree from every process-create *detection*
    on a computer (Sysmon EID 1 and/or Security EID 4688).

    Because Hayabusa only emits events a rule matched, the tree covers the
    flagged processes and their flagged relatives — enough to see "what
    launched what" during the incident. Nodes carry a `detection` link when a
    rule fired on that process. Returns a forest ({roots:[...]})."""
    if not computer:
        return {"error": "no computer specified", "roots": []}

    rows = store.query_detections(
        computer=computer, job_id=job_id,
        include_suppressed=include_suppressed,
        limit=8000, order_by="ts_asc",
    )

    by_guid: dict[str, dict[str, Any]] = {}
    by_pid: dict[str, dict[str, Any]] = {}
    truncated = False

    for row in rows:
        rec = _proc_record_any(row["raw_json"])
        if not rec:
            continue
        guid = rec["guid"]
        pid = rec["pid"]
        # 検知プロセスは「何をしたか」の平易な日本語1文を付ける（ストーリーと同じ）。
        narrative = ""
        if row["rule_id"]:
            actor = {
                "program": _basename(rec["image"]), "program_full": rec["image"],
                "command": rec["cmdline"], "user": rec["user"],
                "parent": _basename(rec["parent_image"]), "pid": pid, "service": "",
            }
            tactics = rec.get("_tactics") or []
            try:
                narrative = store._narrative(
                    tactics[0] if tactics else "", rec.get("_tags") or [], actor)
            except Exception:
                narrative = ""
        node = {
            "guid": guid, "pid": pid,
            "image": rec["image"], "cmdline": rec["cmdline"],
            "user": rec["user"], "integrity": rec["integrity"],
            "parent_guid": rec["parent_guid"], "parent_pid": rec["parent_pid"],
            "parent_image": rec["parent_image"],
            "ts": rec.get("_ts") or row["ts"],
            "detection": {
                "job_id": row["job_id"], "line_no": row["line_no"],
                "level": row["level"], "rule_title": row["rule_title"],
                "rule_id": row["rule_id"], "narrative": narrative,
            } if row["rule_id"] else None,
            "children": [],
        }
        # Prefer the record with the most command-line detail per key.
        if guid:
            ex = by_guid.get(guid)
            if not ex or len(node["cmdline"]) > len(ex.get("cmdline") or ""):
                node["children"] = ex["children"] if ex else []
                by_guid[guid] = node
            if node["detection"] and not by_guid[guid].get("detection"):
                by_guid[guid]["detection"] = node["detection"]
        elif pid:
            ex = by_pid.get(pid)
            if not ex or len(node["cmdline"]) > len(ex.get("cmdline") or ""):
                node["children"] = ex["children"] if ex else []
                by_pid[pid] = node
            if node["detection"] and not by_pid[pid].get("detection"):
                by_pid[pid]["detection"] = node["detection"]
        if len(by_guid) + len(by_pid) >= MAX_NODES:
            truncated = True
            break

    # Stitch parent -> child. Hayabusa only emits *detected* process-creates,
    # so a flagged child's parent is usually NOT itself in the map (e.g.
    # w3wp.exe spawns the flagged powershell.exe, but w3wp.exe wasn't a
    # detection). Without help the child would float as a root and you'd lose
    # the crucial "what launched it" context. So when the real parent is
    # missing we synthesise a lightweight placeholder node from the child's
    # Parent* fields and group siblings under it. Result: the ancestry chain
    # (w3wp.exe -> powershell.exe -> appcmd.exe) is visible even though only
    # the two leaf processes were flagged.
    roots: list[dict[str, Any]] = []
    synth: dict[str, dict[str, Any]] = {}

    def _synth_parent(key: str, image: str, guid: str, pid: str,
                      ts: str) -> dict[str, Any]:
        sp = synth.get(key)
        if sp is None:
            sp = {
                "guid": guid, "pid": pid,
                "image": image or "(記録されていない親プロセス)",
                "cmdline": "", "user": "", "integrity": "",
                "parent_guid": "", "parent_pid": "", "parent_image": "",
                "ts": ts, "detection": None, "synthetic": True,
                "children": [],
            }
            synth[key] = sp
            roots.append(sp)
        return sp

    if by_guid:
        for guid, node in by_guid.items():
            pg = node["parent_guid"]
            if pg and pg in by_guid:
                by_guid[pg]["children"].append(node)
            elif pg or node["parent_image"]:
                key = "g:" + pg if pg else "pi:" + (node["parent_image"] or "")
                _synth_parent(key, node["parent_image"], pg,
                              node["parent_pid"], node["ts"])["children"].append(node)
            else:
                roots.append(node)
    elif by_pid:
        for pid, node in by_pid.items():
            pp = node["parent_pid"]
            if pp and pp in by_pid and pp != pid:
                by_pid[pp]["children"].append(node)
            elif (pp and pp != pid) or node["parent_image"]:
                key = "p:" + pp if pp else "pi:" + (node["parent_image"] or "")
                _synth_parent(key, node["parent_image"], "",
                              pp, node["ts"])["children"].append(node)
            else:
                roots.append(node)

    def _sort(node):
        node["children"].sort(key=lambda c: c.get("ts") or "")
        for ch in node["children"]:
            _sort(ch)
    roots.sort(key=lambda r: r.get("ts") or "")
    for r in roots:
        _sort(r)

    nodes = len(by_guid) + len(by_pid)
    return {
        "computer": computer,
        "roots": roots,
        "nodes_seen": nodes,
        "truncated": truncated,
        "key_mode": "guid" if by_guid else ("pid" if by_pid else "empty"),
        "has_data": nodes > 0,
    }
