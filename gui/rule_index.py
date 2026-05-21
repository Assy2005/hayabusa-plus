"""
Rule YAML lookup — RuleID → file path + parsed metadata.

The Hayabusa rule tree contains ~5000 YAML files. We walk it once on demand,
build an in-memory index keyed by `id:` field, and serve enriched metadata
(description, level, tags, falsepositives, references) to the detail view.

Why not PyYAML?
---------------
We deliberately avoid an external dependency. The rules we care about have
a flat-ish top-level: scalar fields like `title`, `level`, `description`,
plus a few list-typed fields (`tags`, `falsepositives`, `references`). A
small line-based parser covers that subset cleanly. For pathological rules
that don't parse, we fall back to "raw text" mode and surface the file as-is.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

# Scalar fields we extract verbatim.
SCALAR_FIELDS = {"title", "id", "level", "status", "author", "date",
                 "description"}
# Fields whose values are YAML lists of strings.
LIST_FIELDS = {"tags", "falsepositives", "references"}

_RULE_ID_RE = re.compile(r"^\s*id\s*:\s*(?P<v>[\"']?)([0-9a-fA-F\-]{8,}|[A-Za-z0-9_\-]{6,})(?P=v)\s*$")


class RuleIndex:
    """Lazy, thread-safe index of rule YAML files under one or more roots."""

    def __init__(self, *roots: Path, ttl_seconds: float = 30.0):
        self.roots = [Path(r) for r in roots if Path(r).exists()]
        self.ttl = ttl_seconds
        self._by_id: dict[str, Path] = {}
        self._loaded_at: float = 0.0
        self._lock = threading.Lock()

    # --------------------------------------------------------- index build

    def _maybe_refresh(self):
        with self._lock:
            now = time.time()
            if self._by_id and (now - self._loaded_at) < self.ttl:
                return
            new_index: dict[str, Path] = {}
            for root in self.roots:
                for path in root.rglob("*.yml"):
                    rid = self._sniff_id(path)
                    if rid:
                        # First definition wins; this means custom rules
                        # placed earlier on the rule path can NOT shadow
                        # built-in ones with the same id. That is the
                        # right policy for an analyst lookup tool.
                        new_index.setdefault(rid, path)
            self._by_id = new_index
            self._loaded_at = now

    @staticmethod
    def _sniff_id(path: Path) -> str | None:
        """Read just the head of a YAML file looking for an `id:` line."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for _ in range(40):
                    line = f.readline()
                    if not line:
                        break
                    m = _RULE_ID_RE.match(line)
                    if m:
                        return m.group(2)
        except OSError:
            return None
        return None

    # --------------------------------------------------------- public API

    def lookup(self, rule_id: str) -> dict | None:
        """Return parsed metadata for a rule, or None if not found."""
        self._maybe_refresh()
        path = self._by_id.get(rule_id)
        if not path:
            return None
        return self._parse(path)

    def _parse(self, path: Path) -> dict:
        meta: dict[str, object] = {"path": str(path),
                                   "filename": path.name,
                                   "raw_yaml": ""}
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            meta["error"] = str(exc)
            return meta
        meta["raw_yaml"] = raw
        # Cheap top-level parser. Stops descending into nested mappings;
        # that's intentional — we only surface header metadata.
        current_list: str | None = None
        current_list_acc: list[str] = []
        current_multiline: str | None = None
        multiline_acc: list[str] = []

        def flush_multiline():
            if current_multiline is not None:
                meta[current_multiline] = "\n".join(multiline_acc).rstrip()

        def flush_list():
            if current_list is not None:
                meta[current_list] = list(current_list_acc)

        for raw_line in raw.splitlines():
            line = raw_line.rstrip()
            indent = len(line) - len(line.lstrip(" "))

            # Inside a multi-line block scalar (description: |), keep
            # eating indented lines.
            if current_multiline is not None:
                if line and indent == 0 and ":" in line:
                    flush_multiline(); current_multiline = None
                else:
                    multiline_acc.append(line.lstrip(" ") if line else "")
                    continue

            # Inside a list (tags: \n  - x), eat - items.
            if current_list is not None:
                stripped = line.lstrip(" ")
                if stripped.startswith("- "):
                    current_list_acc.append(stripped[2:].strip())
                    continue
                else:
                    flush_list(); current_list = None
                    current_list_acc = []

            if indent != 0:
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key in SCALAR_FIELDS:
                if val in ("|", ">", "|+", "|-"):
                    current_multiline = key
                    multiline_acc = []
                else:
                    meta[key] = val.strip('"').strip("'")
            elif key in LIST_FIELDS:
                if val:
                    # Inline list `tags: [a, b]` (rare in the wild but supported).
                    if val.startswith("[") and val.endswith("]"):
                        meta[key] = [s.strip(" \"'")
                                     for s in val[1:-1].split(",") if s.strip()]
                else:
                    current_list = key
                    current_list_acc = []
        # Flush trailing state.
        flush_multiline()
        flush_list()
        return meta


def attack_tags(meta: dict) -> list[str]:
    """Pull ATT&CK technique tags out of a parsed rule's `tags:` field."""
    out = []
    for t in (meta.get("tags") or []):
        if isinstance(t, str) and t.lower().startswith("attack."):
            out.append(t)
    return out
