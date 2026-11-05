"""
Append-only, hash-chained audit log for the hayabusa-plus console.

Why a separate file (not SQLite)
--------------------------------
The detection database is allowed to be rebuilt from JSONL evidence. An audit
trail must survive that rebuild, so it lives in its own append-only JSONL file
under the data root. Each entry commits to the previous entry's hash:

    hash = SHA-256(prev_hash + "\n" + canonical_json(payload))

Deleting or editing an entry in the middle therefore breaks the chain and is
reported by ``verify()``. This is a tamper-evident local log, not a replacement
for a remote SIEM/WORM archive: an actor with full control of the host can
rewrite the whole file. Export the chain to an external collector for real
retention requirements.

No third-party dependencies. Thread-safe for the single-process server.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


GENESIS = "GENESIS"


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _entry_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": record.get("ts"),
        "action": record.get("action"),
        "actor": record.get("actor"),
        "object_type": record.get("object_type"),
        "object_id": record.get("object_id"),
        "detail": record.get("detail") or {},
    }


def _entry_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    material = (prev_hash + "\n" + _canonical(payload)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


class AuditLog:
    """Hash-chained JSONL audit log."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._last_hash = GENESIS
        self._count = 0
        self._load()

    # ------------------------------------------------------------------ load

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        # Keep counting so verify() can point at the damage.
                        self._count += 1
                        continue
                    self._count += 1
                    h = rec.get("hash")
                    if isinstance(h, str) and h:
                        self._last_hash = h
        except OSError:
            self._last_hash = GENESIS
            self._count = 0

    # ----------------------------------------------------------------- write

    @staticmethod
    def actor_default() -> str:
        return (os.environ.get("HAYABUSA_ACTOR") or "local-analyst").strip()[:80]

    def append(self, action: str, *, actor: str | None = None,
               object_type: str = "", object_id: str = "",
               detail: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append one entry and fsync it before returning."""
        action = (action or "").strip()[:80]
        if not action:
            raise ValueError("audit action is required")
        payload = {
            "ts": time.time(),
            "action": action,
            "actor": (actor or self.actor_default())[:80],
            "object_type": (object_type or "")[:40],
            "object_id": str(object_id or "")[:200],
            "detail": detail or {},
        }
        with self._lock:
            prev = self._last_hash
            digest = _entry_hash(prev, payload)
            record = dict(payload)
            record["prev_hash"] = prev
            record["hash"] = digest
            line = json.dumps(record, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n"
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # Some network/FUSE filesystems reject fsync; the append
                    # still succeeded and verify() continues to work.
                    pass
            self._last_hash = digest
            self._count += 1
            return record

    # ------------------------------------------------------------------ read

    def tail(self, limit: int = 200, *, case_id: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit or 200), 5000))
        out: deque[dict] = deque(maxlen=limit)
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if case_id:
                        detail = rec.get("detail") or {}
                        if (detail.get("case_id") != case_id
                                and rec.get("object_id") != case_id):
                            continue
                    out.append(rec)
        except OSError:
            return []
        return list(out)

    def count(self) -> int:
        return self._count

    def verify(self) -> dict[str, Any]:
        """Recompute the full chain and report the first broken entry."""
        prev = GENESIS
        n = 0
        if not self.path.exists():
            return {"ok": True, "entries": 0, "message": "監査ログはまだありません。"}
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    n += 1
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        return {"ok": False, "entries": n, "bad_line": line_no,
                                "message": f"{line_no} 行目が JSON として壊れています。"}
                    payload = _entry_payload(rec)
                    if rec.get("prev_hash") != prev:
                        return {"ok": False, "entries": n, "bad_line": line_no,
                                "message": f"{line_no} 行目の prev_hash が一致しません。"}
                    expected = _entry_hash(prev, payload)
                    if rec.get("hash") != expected:
                        return {"ok": False, "entries": n, "bad_line": line_no,
                                "message": f"{line_no} 行目のハッシュが一致しません。"}
                    prev = expected
        except OSError as exc:
            return {"ok": False, "entries": n, "message": f"監査ログを読めません: {exc}"}
        return {"ok": True, "entries": n, "last_hash": prev,
                "message": "監査ログのハッシュチェーンは正常です。"}
