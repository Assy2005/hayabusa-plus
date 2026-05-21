"""
SQLite-backed store for jobs, detections, and analyst feedback (TP/FP).

Why SQLite
----------
The JSONL output from Hayabusa is already a serviceable archive, but it cannot
answer simple analyst questions cheaply ("show all critical detections from
rule X across all jobs"). A small SQLite file gives us indexed queries and
fast pagination at zero deployment cost.

Threading
---------
The HTTP server uses ThreadingHTTPServer, so each request lands on its own
thread. The Hayabusa tailer also runs on its own thread. We give each caller
its own short-lived connection and rely on SQLite's WAL mode for concurrency:
WAL allows one writer + many readers without blocking, which matches our
access pattern (one writer = the tailer; many readers = the UI).

Durability vs. throughput
-------------------------
We use `synchronous = NORMAL` and explicit `commit()` after each batch. A
power loss could lose the last few detection rows, which is acceptable: the
JSONL file on disk remains the source of truth and the indexer is idempotent
on restart.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

# Detection-feedback verdicts. Kept lowercase to match Sigma convention.
VERDICT_TP = "tp"
VERDICT_FP = "fp"
VALID_VERDICTS = {VERDICT_TP, VERDICT_FP, None, ""}

# Hayabusa's default output profile abbreviates the Level field (`crit`,
# `med`, `info`). We normalise on insert so every downstream consumer
# (dashboards, filters, scoring) sees the same canonical strings.
LEVEL_ALIASES = {
    "crit": "critical", "critical": "critical",
    "high": "high",
    "med":  "medium",   "medium":   "medium",
    "low":  "low",
    "info": "informational", "informational": "informational",
}

def normalize_level(level: str | None) -> str:
    if not level:
        return ""
    return LEVEL_ALIASES.get(level.lower(), level.lower())

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  exit_code       INTEGER,
  started_at      REAL NOT NULL,
  finished_at     REAL,
  args_json       TEXT,
  detection_count INTEGER NOT NULL DEFAULT 0,
  indexed_lines   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS detections (
  job_id     TEXT NOT NULL,
  line_no    INTEGER NOT NULL,
  ts         TEXT,
  level      TEXT,
  rule_id    TEXT,
  rule_title TEXT,
  computer   TEXT,
  channel    TEXT,
  event_id   TEXT,
  raw_json   TEXT NOT NULL,
  verdict    TEXT,
  verdict_at REAL,
  PRIMARY KEY(job_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_det_level    ON detections(level);
CREATE INDEX IF NOT EXISTS idx_det_rule     ON detections(rule_id);
CREATE INDEX IF NOT EXISTS idx_det_computer ON detections(computer);
CREATE INDEX IF NOT EXISTS idx_det_verdict  ON detections(verdict);

CREATE TABLE IF NOT EXISTS rule_feedback (
  rule_id    TEXT PRIMARY KEY,
  rule_title TEXT,
  tp_count   INTEGER NOT NULL DEFAULT 0,
  fp_count   INTEGER NOT NULL DEFAULT 0,
  last_at    REAL
);

-- Suppressions are non-destructive filters: matching detections stay in
-- `detections` but the UI hides them by default. A row matches a detection
-- when EVERY non-null pattern field matches the detection's field. The
-- `computer` field supports SQL LIKE-style globs (`*` is translated to `%`
-- at insert time so SQLite can use a normal LIKE).
CREATE TABLE IF NOT EXISTS suppressions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  scope         TEXT NOT NULL,    -- 'rule' | 'host' | 'rule+host'
  rule_id       TEXT,             -- nullable for host-only suppressions
  computer_like TEXT,             -- nullable for rule-only; SQL LIKE pattern
  reason        TEXT,
  created_at    REAL NOT NULL,
  created_by    TEXT,
  active        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_supp_rule ON suppressions(rule_id);
CREATE INDEX IF NOT EXISTS idx_supp_host ON suppressions(computer_like);
CREATE UNIQUE INDEX IF NOT EXISTS uq_supp_key
  ON suppressions(scope,
                  IFNULL(rule_id, ''),
                  IFNULL(computer_like, ''));
"""


class Store:
    """Thin wrapper around a SQLite file with per-thread connections."""

    def __init__(self, db_path: Path, fp_history_dir: Path):
        self.db_path = db_path
        self.fp_history_dir = fp_history_dir
        self.fp_history_dir.mkdir(parents=True, exist_ok=True)
        self._tls = threading.local()
        self._init_lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------ conn

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
            # WAL gives us concurrent readers; NORMAL syncs are durable enough
            # given the JSONL file on disk remains the source of truth.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._tls.conn = conn
        return conn

    def _init_schema(self):
        with self._init_lock:
            conn = self._conn()
            with conn:
                conn.executescript(SCHEMA)
            # One-shot data fix-up: align any rows inserted by older builds
            # that stored Hayabusa's abbreviated level values. Idempotent.
            for short, full in (("crit", "critical"), ("med", "medium"),
                                ("info", "informational")):
                conn.execute("UPDATE detections SET level=? WHERE level=?",
                             (full, short))

    @contextlib.contextmanager
    def transaction(self):
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------ jobs

    def upsert_job(self, job: dict[str, Any]):
        c = self._conn()
        c.execute(
            "INSERT INTO jobs(id, kind, status, exit_code, started_at, "
            "finished_at, args_json, detection_count, indexed_lines) "
            "VALUES(?,?,?,?,?,?,?,?,COALESCE((SELECT indexed_lines FROM jobs WHERE id=?), 0)) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  status=excluded.status, exit_code=excluded.exit_code, "
            "  finished_at=excluded.finished_at, args_json=excluded.args_json, "
            "  detection_count=excluded.detection_count",
            (job["id"], job["kind"], job["status"], job.get("exit_code"),
             job["started_at"], job.get("finished_at"),
             json.dumps(job.get("args") or []), job.get("detection_count", 0),
             job["id"]),
        )

    def list_jobs(self) -> list[sqlite3.Row]:
        c = self._conn()
        return list(c.execute(
            "SELECT id, kind, status, exit_code, started_at, finished_at, "
            "args_json, detection_count FROM jobs ORDER BY started_at DESC"
        ))

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        c = self._conn()
        return c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def bump_indexed_lines(self, job_id: str, by: int):
        c = self._conn()
        c.execute("UPDATE jobs SET indexed_lines=indexed_lines+?, "
                  "detection_count=detection_count+? WHERE id=?",
                  (by, by, job_id))

    def indexed_lines(self, job_id: str) -> int:
        c = self._conn()
        row = c.execute("SELECT indexed_lines FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["indexed_lines"] if row else 0

    # ------------------------------------------------------------ detections

    @staticmethod
    def stable_rule_id(event: dict[str, Any]) -> str:
        """
        Pick the most stable identifier we can find for the rule.

        Hayabusa's standard JSONL profile emits `RuleID` (a UUID). Older or
        custom profiles may omit it; in that case we fall back to a hash of
        (RuleTitle, Channel) so feedback is still partitioned reasonably.
        """
        rid = (event.get("RuleID") or "").strip()
        if rid:
            return rid
        seed = (event.get("RuleTitle") or "") + "|" + (event.get("Channel") or "")
        return "h:" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    def insert_detections(self, job_id: str,
                          rows: Iterable[tuple[int, str, dict]]) -> int:
        """
        Insert a batch of detections.

        rows: iterable of (line_no, raw_line, parsed_event_dict).
        Returns the count actually inserted (duplicates are ignored).
        """
        sql = ("INSERT OR IGNORE INTO detections(job_id, line_no, ts, level, "
               "rule_id, rule_title, computer, channel, event_id, raw_json) "
               "VALUES(?,?,?,?,?,?,?,?,?,?)")
        n = 0
        c = self._conn()
        with self.transaction():
            for line_no, raw_line, event in rows:
                level = normalize_level(event.get("Level"))
                rule_id = self.stable_rule_id(event)
                cur = c.execute(sql, (
                    job_id, line_no,
                    event.get("Timestamp"), level, rule_id,
                    event.get("RuleTitle"), event.get("Computer"),
                    event.get("Channel"),
                    None if event.get("EventID") is None else str(event.get("EventID")),
                    raw_line,
                ))
                n += cur.rowcount or 0
        return n

    # ------------------------------------- query builder shared by both APIs

    @staticmethod
    def _build_detection_where(*, job_id, level, rule_id, verdict, text,
                               include_suppressed,
                               # Hunting extensions:
                               computer=None, computer_glob=None,
                               channel=None, event_id=None,
                               levels=None,                # list[str] — OR
                               rule_ids=None,              # list[str] — OR
                               ts_from=None, ts_to=None):  # ISO strings
        """
        Build the WHERE clause shared by /api/detections and /api/hunt/*.

        New (hunt) parameters:
          * `computer_glob` — `*` and `?` translate to SQL LIKE wildcards.
            Used by the hunting UI to match "WS-ALICE-*" without dropping
            into regex.
          * `channel`, `event_id` — exact match on the indexed columns.
          * `levels`, `rule_ids` — multi-value OR sets, encoded as IN (..).
          * `ts_from`, `ts_to` — inclusive ISO-8601 string range. We rely
            on the lexicographic ordering of ISO timestamps so SQLite can
            use the `idx_det_ts`-equivalent path without parsing dates.
        """
        clauses, params = [], []
        if job_id:   clauses.append("d.job_id = ?");  params.append(job_id)
        if level:    clauses.append("d.level = ?");   params.append(level)
        if rule_id:  clauses.append("d.rule_id = ?"); params.append(rule_id)
        if levels:
            ph = ",".join(["?"] * len(levels))
            clauses.append(f"d.level IN ({ph})"); params.extend(levels)
        if rule_ids:
            ph = ",".join(["?"] * len(rule_ids))
            clauses.append(f"d.rule_id IN ({ph})"); params.extend(rule_ids)
        if computer:
            clauses.append("d.computer = ?"); params.append(computer)
        if computer_glob:
            # `*` → `%`, `?` → `_`. SQL LIKE metas in the input are escaped
            # so a glob like "WS-?*" works as expected.
            esc = computer_glob.replace("\\", "\\\\")\
                               .replace("%", r"\%")\
                               .replace("_", r"\_")\
                               .replace("*", "%")\
                               .replace("?", "_")
            clauses.append("d.computer LIKE ? ESCAPE '\\'"); params.append(esc)
        if channel:
            clauses.append("d.channel = ?"); params.append(channel)
        if event_id:
            clauses.append("d.event_id = ?"); params.append(str(event_id))
        if ts_from:
            clauses.append("d.ts >= ?"); params.append(ts_from)
        if ts_to:
            clauses.append("d.ts <= ?"); params.append(ts_to)
        if verdict in (VERDICT_TP, VERDICT_FP):
            clauses.append("d.verdict = ?"); params.append(verdict)
        elif verdict == "unverdicted":
            clauses.append("d.verdict IS NULL")
        if text:
            like = f"%{text}%"
            clauses.append("(d.rule_title LIKE ? OR d.computer LIKE ? OR d.raw_json LIKE ?)")
            params.extend([like, like, like])
        if not include_suppressed:
            clauses.append("s.id IS NULL")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    _SUPP_JOIN = (
        " LEFT JOIN suppressions s "
        "   ON s.active = 1 "
        "  AND (s.rule_id IS NULL OR s.rule_id = d.rule_id) "
        "  AND (s.computer_like IS NULL OR d.computer LIKE s.computer_like) "
    )

    def query_detections(self, *, job_id: str | None = None,
                         level: str | None = None,
                         rule_id: str | None = None,
                         verdict: str | None = None,
                         text: str | None = None,
                         include_suppressed: bool = False,
                         offset: int = 0, limit: int = 200,
                         # Hunt extensions:
                         computer: str | None = None,
                         computer_glob: str | None = None,
                         channel: str | None = None,
                         event_id: str | None = None,
                         levels: list[str] | None = None,
                         rule_ids: list[str] | None = None,
                         ts_from: str | None = None,
                         ts_to: str | None = None,
                         order_by: str = "ts_desc"):
        where, params = self._build_detection_where(
            job_id=job_id, level=level, rule_id=rule_id, verdict=verdict,
            text=text, include_suppressed=include_suppressed,
            computer=computer, computer_glob=computer_glob,
            channel=channel, event_id=event_id,
            levels=levels, rule_ids=rule_ids,
            ts_from=ts_from, ts_to=ts_to)
        order_sql = {
            "ts_desc":  " ORDER BY d.ts DESC, d.line_no DESC ",
            "ts_asc":   " ORDER BY d.ts ASC, d.line_no ASC ",
            "level_desc": " ORDER BY CASE d.level "
                          " WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                          " WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END "
                          " DESC, d.ts DESC ",
        }.get(order_by, " ORDER BY d.ts DESC, d.line_no DESC ")
        sql = (
            "SELECT d.job_id, d.line_no, d.ts, d.level, d.rule_id, "
            "       d.rule_title, d.computer, d.channel, d.event_id, "
            "       d.raw_json, d.verdict, d.verdict_at, "
            "       s.id AS suppression_id, s.reason AS suppression_reason "
            "FROM detections d" + self._SUPP_JOIN +
            where +
            " GROUP BY d.job_id, d.line_no " +
            order_sql +
            " LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        return list(self._conn().execute(sql, params))

    def count_detections(self, *, job_id=None, level=None, rule_id=None,
                         verdict=None, text=None,
                         include_suppressed: bool = False,
                         computer=None, computer_glob=None,
                         channel=None, event_id=None,
                         levels=None, rule_ids=None,
                         ts_from=None, ts_to=None,
                         **_ignored) -> int:
        where, params = self._build_detection_where(
            job_id=job_id, level=level, rule_id=rule_id, verdict=verdict,
            text=text, include_suppressed=include_suppressed,
            computer=computer, computer_glob=computer_glob,
            channel=channel, event_id=event_id,
            levels=levels, rule_ids=rule_ids,
            ts_from=ts_from, ts_to=ts_to)
        sql = ("SELECT COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n "
               "FROM detections d" + self._SUPP_JOIN + where)
        return self._conn().execute(sql, params).fetchone()["n"]

    # ------------------------------------------------------------ pivots

    def pivot_detections(self, dim: str, *, limit: int = 50, **filters):
        """
        Return aggregate counts of detections grouped by one of:
          'computer', 'rule_id', 'level', 'channel', 'event_id', 'hour'.
        Filters are the same as query_detections — useful for "show me
        the noisiest hosts in the last 24h" kind of hunts.
        """
        col_map = {
            "computer": "d.computer",
            "rule_id":  "d.rule_id",
            "level":    "d.level",
            "channel":  "d.channel",
            "event_id": "d.event_id",
            "hour":     "substr(d.ts, 1, 13)",
            "day":      "substr(d.ts, 1, 10)",
        }
        if dim not in col_map:
            raise ValueError(f"unknown dim: {dim}")
        col = col_map[dim]
        where, params = self._build_detection_where(
            job_id=filters.get("job_id"),
            level=filters.get("level"),
            rule_id=filters.get("rule_id"),
            verdict=filters.get("verdict"),
            text=filters.get("text"),
            include_suppressed=filters.get("include_suppressed", False),
            computer=filters.get("computer"),
            computer_glob=filters.get("computer_glob"),
            channel=filters.get("channel"),
            event_id=filters.get("event_id"),
            levels=filters.get("levels"),
            rule_ids=filters.get("rule_ids"),
            ts_from=filters.get("ts_from"),
            ts_to=filters.get("ts_to"),
        )
        sql = (
            f"SELECT {col} AS k, "
            f"       COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n, "
            f"       SUM(CASE WHEN d.level IN ('critical','high') THEN 1 ELSE 0 END) AS sev_count, "
            f"       MAX(d.rule_title) AS sample_title "
            f"FROM detections d{self._SUPP_JOIN}{where} "
            f"GROUP BY {col} ORDER BY n DESC LIMIT ?")
        params.append(limit)
        return [dict(r) for r in self._conn().execute(sql, params)]

    # ------------------------------------------------------------- feedback

    def record_feedback(self, job_id: str, line_no: int,
                        verdict: str | None) -> dict | None:
        """
        Set or clear a verdict on a single detection.

        Returns the updated detection row as a dict, or None if the target
        does not exist. Also keeps the rule_feedback materialised view in
        sync and rewrites the rule's fp_history JSON snapshot.
        """
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"invalid verdict: {verdict!r}")
        norm = verdict or None  # treat "" as clear
        now = time.time()
        c = self._conn()
        with self.transaction():
            row = c.execute(
                "SELECT rule_id, rule_title, verdict FROM detections "
                "WHERE job_id=? AND line_no=?", (job_id, line_no)
            ).fetchone()
            if not row:
                return None
            old = row["verdict"]
            rule_id = row["rule_id"]
            rule_title = row["rule_title"]

            c.execute("UPDATE detections SET verdict=?, verdict_at=? "
                      "WHERE job_id=? AND line_no=?",
                      (norm, now if norm else None, job_id, line_no))

            # Re-derive the per-rule counters from scratch — cheaper than
            # juggling deltas and immune to drift.
            counts = c.execute(
                "SELECT verdict, COUNT(*) AS n FROM detections "
                "WHERE rule_id=? AND verdict IS NOT NULL GROUP BY verdict",
                (rule_id,)
            ).fetchall()
            tp = sum(r["n"] for r in counts if r["verdict"] == VERDICT_TP)
            fp = sum(r["n"] for r in counts if r["verdict"] == VERDICT_FP)
            c.execute(
                "INSERT INTO rule_feedback(rule_id, rule_title, tp_count, "
                "fp_count, last_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(rule_id) DO UPDATE SET "
                "rule_title=excluded.rule_title, tp_count=excluded.tp_count, "
                "fp_count=excluded.fp_count, last_at=excluded.last_at",
                (rule_id, rule_title, tp, fp, now))

        self._write_fp_history(rule_id, rule_title, tp, fp, now)
        return {"job_id": job_id, "line_no": line_no, "old": old, "new": norm,
                "rule_id": rule_id, "tp": tp, "fp": fp}

    # ----------------------------------------------------------- statistics

    def _stats_where(self, job_id: str | None, include_suppressed: bool):
        clauses, params = ["1=1"], []
        if job_id:
            clauses.append("d.job_id = ?")
            params.append(job_id)
        join = self._SUPP_JOIN
        if not include_suppressed:
            clauses.append("s.id IS NULL")
        return join, " AND ".join(clauses), params

    def stats_by_level(self, job_id=None, include_suppressed=False) -> dict[str, int]:
        join, where, params = self._stats_where(job_id, include_suppressed)
        rows = self._conn().execute(
            f"SELECT d.level AS k, COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n "
            f"FROM detections d{join} WHERE {where} GROUP BY d.level", params)
        return {row["k"] or "unknown": row["n"] for row in rows}

    def stats_top_rules(self, job_id=None, limit=10, include_suppressed=False):
        join, where, params = self._stats_where(job_id, include_suppressed)
        sql = (f"SELECT d.rule_id, d.rule_title, d.level, "
               f"       COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n "
               f"FROM detections d{join} WHERE {where} "
               f"GROUP BY d.rule_id ORDER BY n DESC LIMIT ?")
        params = [*params, limit]
        return [dict(r) for r in self._conn().execute(sql, params)]

    def stats_top_computers(self, job_id=None, limit=10, include_suppressed=False):
        join, where, params = self._stats_where(job_id, include_suppressed)
        sql = (f"SELECT d.computer, "
               f"       COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n, "
               f"       SUM(CASE WHEN d.level IN ('critical','high') THEN 1 ELSE 0 END) AS sev_count "
               f"FROM detections d{join} WHERE {where} "
               f"GROUP BY d.computer ORDER BY n DESC LIMIT ?")
        params = [*params, limit]
        return [dict(r) for r in self._conn().execute(sql, params)]

    def stats_unique(self, field: str, job_id=None, include_suppressed=False) -> int:
        """Cardinality of a column ('computer', 'rule_id', etc.)."""
        if field not in ("computer", "rule_id", "channel"):
            raise ValueError(f"unsupported field: {field}")
        join, where, params = self._stats_where(job_id, include_suppressed)
        return self._conn().execute(
            f"SELECT COUNT(DISTINCT d.{field}) AS n FROM detections d{join} "
            f"WHERE {where}", params).fetchone()["n"]

    # -------- related-detection queries used by the detail pane --------

    def get_detection(self, job_id: str, line_no: int) -> sqlite3.Row | None:
        """Single row plus its current suppression status."""
        sql = (
            "SELECT d.job_id, d.line_no, d.ts, d.level, d.rule_id, "
            "       d.rule_title, d.computer, d.channel, d.event_id, "
            "       d.raw_json, d.verdict, d.verdict_at, "
            "       s.id AS suppression_id, s.reason AS suppression_reason "
            "FROM detections d" + self._SUPP_JOIN +
            " WHERE d.job_id=? AND d.line_no=? "
            " GROUP BY d.job_id, d.line_no LIMIT 1")
        return self._conn().execute(sql, (job_id, line_no)).fetchone()

    def related_on_host(self, computer: str | None, ts: str | None,
                        window_minutes: int = 5,
                        exclude: tuple[str, int] | None = None,
                        limit: int = 25):
        """
        Find detections on the same Computer within ±window of ts.

        We compare timestamps as strings — ISO 8601 sorts correctly that
        way and saves us a round-trip through Python datetime. The
        comparison is inclusive on both sides.
        """
        if not computer or not ts:
            return []
        # Build a textual window. We trim to the millisecond resolution
        # the timestamps already have so SQLite's string compare is
        # stable across minor format variants.
        try:
            base = self._parse_iso(ts)
        except ValueError:
            return []
        from datetime import timedelta
        lo = (base - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        hi = (base + timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        clauses = ["d.computer = ?", "d.ts >= ?", "d.ts <= ?"]
        params: list = [computer, lo, hi]
        if exclude:
            clauses.append("NOT (d.job_id = ? AND d.line_no = ?)")
            params.extend([exclude[0], exclude[1]])
        sql = ("SELECT d.job_id, d.line_no, d.ts, d.level, d.rule_id, "
               "       d.rule_title, d.computer, d.channel, d.event_id "
               "FROM detections d WHERE " + " AND ".join(clauses) +
               " ORDER BY d.ts ASC LIMIT ?")
        params.append(limit)
        return [dict(r) for r in self._conn().execute(sql, params)]

    def rule_history(self, rule_id: str | None, exclude: tuple[str, int] | None = None,
                     limit: int = 25):
        """Other fires of the same rule across all jobs."""
        if not rule_id:
            return {"total": 0, "sample": []}
        c = self._conn()
        total = c.execute(
            "SELECT COUNT(*) AS n FROM detections WHERE rule_id=?",
            (rule_id,)).fetchone()["n"]
        clauses = ["rule_id = ?"]
        params: list = [rule_id]
        if exclude:
            clauses.append("NOT (job_id = ? AND line_no = ?)")
            params.extend([exclude[0], exclude[1]])
        params.append(limit)
        rows = c.execute(
            "SELECT job_id, line_no, ts, level, computer, channel, event_id "
            "FROM detections WHERE " + " AND ".join(clauses) +
            " ORDER BY ts DESC LIMIT ?", params)
        return {"total": total, "sample": [dict(r) for r in rows]}

    @staticmethod
    def _parse_iso(ts: str):
        """Permissive ISO-8601 parser handling the formats Hayabusa emits."""
        from datetime import datetime
        candidates = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f %z",
            "%Y-%m-%d %H:%M:%S %z",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        # Last resort: lop off timezone tail and retry.
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"unparsable timestamp: {ts!r}") from exc

    def stats_timeline(self, job_id=None, bucket="hour", include_suppressed=False):
        """
        Bucket detections by time for the time-series chart.

        We compute the bucket entirely in SQL using `substr` on the ISO
        timestamp. This is robust to whatever timezone format Hayabusa
        emitted because we treat the prefix as opaque.
        """
        # 'hour' -> 'YYYY-MM-DDTHH', 'day' -> 'YYYY-MM-DD', 'minute' -> 'YYYY-MM-DDTHH:MM'
        slice_len = {"minute": 16, "hour": 13, "day": 10}.get(bucket, 13)
        join, where, params = self._stats_where(job_id, include_suppressed)
        sql = (
            f"SELECT substr(d.ts, 1, {slice_len}) AS bucket, d.level, "
            f"       COUNT(DISTINCT d.job_id || ':' || d.line_no) AS n "
            f"FROM detections d{join} WHERE {where} AND d.ts IS NOT NULL "
            f"GROUP BY bucket, d.level ORDER BY bucket ASC")
        rows = list(self._conn().execute(sql, params))
        # Pivot to {bucket: {level: n}} for easier client-side rendering.
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["bucket"], {})[r["level"] or "unknown"] = r["n"]
        return out

    def rule_feedback(self) -> list[sqlite3.Row]:
        c = self._conn()
        return list(c.execute(
            "SELECT rule_id, rule_title, tp_count, fp_count, last_at "
            "FROM rule_feedback ORDER BY (fp_count + tp_count) DESC"))

    # ----------------------------------------------------------- suppressions

    @staticmethod
    def _glob_to_like(pattern: str | None) -> str | None:
        """Translate user-facing glob (*, ?) into SQLite LIKE wildcards."""
        if not pattern:
            return None
        # Escape SQL LIKE metas first, then map globs onto them.
        escaped = pattern.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        return escaped.replace("*", "%").replace("?", "_")

    @staticmethod
    def _derive_scope(rule_id: str | None, computer_like: str | None) -> str:
        has_rule = bool(rule_id)
        has_host = bool(computer_like)
        if has_rule and has_host: return "rule+host"
        if has_rule:              return "rule"
        if has_host:              return "host"
        raise ValueError("suppression must target at least rule_id or computer")

    def add_suppression(self, *, rule_id: str | None = None,
                        computer_glob: str | None = None,
                        reason: str | None = None,
                        created_by: str | None = None) -> int:
        """
        Insert a suppression rule. Returns the new row id, or the existing
        row id if an identical suppression is already present (idempotent).
        """
        rid = (rule_id or "").strip() or None
        clike = self._glob_to_like((computer_glob or "").strip() or None)
        scope = self._derive_scope(rid, clike)
        now = time.time()
        c = self._conn()
        with self.transaction():
            try:
                cur = c.execute(
                    "INSERT INTO suppressions(scope, rule_id, computer_like, "
                    "reason, created_at, created_by, active) "
                    "VALUES(?,?,?,?,?,?,1)",
                    (scope, rid, clike, reason, now, created_by))
                row_id = cur.lastrowid
            except sqlite3.IntegrityError:
                # Same (scope, rule_id, computer_like) key exists. Reuse it
                # but bump active + refresh reason so duplicate adds behave
                # as "re-enable + update".
                row = c.execute(
                    "SELECT id FROM suppressions WHERE scope=? "
                    "AND IFNULL(rule_id,'')=IFNULL(?, '') "
                    "AND IFNULL(computer_like,'')=IFNULL(?, '')",
                    (scope, rid, clike)).fetchone()
                row_id = row["id"]
                c.execute("UPDATE suppressions SET active=1, reason=?, "
                          "created_at=?, created_by=? WHERE id=?",
                          (reason, now, created_by, row_id))
        self._export_suppression_snapshots()
        return row_id

    def remove_suppression(self, suppression_id: int) -> bool:
        c = self._conn()
        cur = c.execute("DELETE FROM suppressions WHERE id=?", (suppression_id,))
        deleted = cur.rowcount > 0
        if deleted:
            self._export_suppression_snapshots()
        return deleted

    def list_suppressions(self) -> list[sqlite3.Row]:
        return list(self._conn().execute(
            "SELECT id, scope, rule_id, computer_like, reason, "
            "       created_at, created_by, active "
            "FROM suppressions ORDER BY created_at DESC"))

    def _export_suppression_snapshots(self):
        """
        Persist suppressions as small JSON files under suppressions/ so they
        can be source-controlled and round-tripped across hosts.

        Layout:
          suppressions/global.json   — rule-only suppressions
          suppressions/<host>.json   — entries whose computer_like is an
                                       exact hostname (no wildcards left)
          suppressions/_glob.json    — host-glob entries that don't pin to
                                       a single hostname
        Source of truth remains SQLite; these files are export snapshots.
        """
        out_dir = self.db_path.parent.parent / "suppressions"
        out_dir.mkdir(parents=True, exist_ok=True)
        buckets: dict[str, list[dict]] = {}
        for row in self.list_suppressions():
            entry = {
                "id": row["id"],
                "scope": row["scope"],
                "rule_id": row["rule_id"],
                "computer_like": row["computer_like"],
                "reason": row["reason"],
                "created_at": row["created_at"],
                "created_by": row["created_by"],
                "active": bool(row["active"]),
            }
            cl = row["computer_like"]
            if not cl:
                bucket = "global"
            elif any(m in cl for m in ("%", "_")):
                bucket = "_glob"
            else:
                # Reverse the LIKE-escaping for a friendlier filename.
                bucket = cl.replace(r"\%", "%").replace(r"\_", "_")
            buckets.setdefault(bucket, []).append(entry)

        # Atomic rewrite per bucket. We write *every* known bucket file —
        # even empty buckets get rewritten to `[]` — so that a delete in
        # SQLite correctly propagates to the snapshot. Without this, a
        # subsequent boot would re-import the stale entry from disk.
        written: set[str] = set()
        for name, items in buckets.items():
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
            path = out_dir / f"{safe}.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
            tmp.replace(path)
            written.add(path.name)
        # Any pre-existing snapshot file we didn't touch must mean its bucket
        # became empty. Overwrite it with `[]` to avoid ghost re-imports, but
        # keep the file so the version-controlled diff stays readable.
        for existing in out_dir.glob("*.json"):
            if existing.name not in written:
                existing.write_text("[]", encoding="utf-8")

    def import_suppression_snapshots(self) -> int:
        """
        On boot, fold any *.json files under suppressions/ back into the
        DB. Useful when the DB was wiped but the snapshot directory was
        checked into version control.
        """
        snap_dir = self.db_path.parent.parent / "suppressions"
        if not snap_dir.exists():
            return 0
        imported = 0
        for path in sorted(snap_dir.glob("*.json")):
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(items, list):
                continue
            for entry in items:
                try:
                    self.add_suppression(
                        rule_id=entry.get("rule_id"),
                        computer_glob=self._like_to_glob(entry.get("computer_like")),
                        reason=entry.get("reason"),
                        created_by=entry.get("created_by"),
                    )
                    imported += 1
                except (ValueError, sqlite3.Error):
                    continue
        return imported

    @staticmethod
    def _like_to_glob(pat: str | None) -> str | None:
        """Inverse of `_glob_to_like` so round-trips don't double-escape."""
        if not pat:
            return None
        out = pat.replace(r"\%", "\x00pct\x00").replace(r"\_", "\x00und\x00")
        out = out.replace("%", "*").replace("_", "?")
        return out.replace("\x00pct\x00", "%").replace("\x00und\x00", "_")

    # ----------------------------------------------------------- fp_history

    def _write_fp_history(self, rule_id: str, rule_title: str | None,
                          tp: int, fp: int, when: float):
        """
        Persist a small JSON snapshot per rule so future scans / scoring
        passes can read the FP history without touching SQLite.

        File layout follows ARCHITECTURE.md §12: scoring reads this file in
        the next-generation engine and adjusts confidence accordingly.
        """
        # Slugify rule_id so it is a safe filename (UUIDs already are).
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in rule_id)
        out = {
            "rule_id": rule_id,
            "rule_title": rule_title,
            "tp_count": tp,
            "fp_count": fp,
            "fp_rate": (fp / (tp + fp)) if (tp + fp) else None,
            "updated_at": when,
        }
        path = self.fp_history_dir / f"{safe}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
        tmp.replace(path)


def reindex_jobs_dir(store: Store, jobs_root: Path) -> dict[str, int]:
    """
    Walk the workspace/jobs/ tree and ingest any detections we don't yet
    know about. Idempotent — we record `indexed_lines` per job and resume
    from there on subsequent runs.

    Returns a {job_id: newly_inserted_count} report for the boot log.
    """
    report: dict[str, int] = {}
    if not jobs_root.exists():
        return report
    for job_dir in sorted(jobs_root.iterdir()):
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        tl = job_dir / "timeline.jsonl"
        if not tl.exists():
            continue
        # If we've never seen this job, mint a row so jobs listings include it.
        # mtime of the timeline file is a reasonable proxy for started_at.
        if store.get_job(job_id) is None:
            mtime = tl.stat().st_mtime
            store.upsert_job({
                "id": job_id, "kind": "imported",
                "status": "done", "exit_code": 0,
                "started_at": mtime, "finished_at": mtime,
                "args": [], "detection_count": 0,
            })
        already = store.indexed_lines(job_id)
        batch: list[tuple[int, str, dict]] = []
        line_no = 0
        with open(tl, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line_no += 1
                if line_no <= already:
                    continue
                raw = raw.rstrip("\n")
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                batch.append((line_no, raw, event))
                if len(batch) >= 500:
                    inserted = store.insert_detections(job_id, batch)
                    store.bump_indexed_lines(job_id, inserted)
                    report[job_id] = report.get(job_id, 0) + inserted
                    batch.clear()
        if batch:
            inserted = store.insert_detections(job_id, batch)
            store.bump_indexed_lines(job_id, inserted)
            report[job_id] = report.get(job_id, 0) + inserted
    return report
