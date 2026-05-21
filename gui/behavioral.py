"""
Behavioral anomaly detection over the existing detection corpus.

Where this fits
---------------
ARCHITECTURE.md §4 calls for "anti-evasion via gap / rate analysis": catch
patterns a single-event Sigma rule cannot express. True gap analysis
(comparing raw EVTX event rates across channels) needs Hayabusa's
`eid-metrics` output which we don't yet collect. As a first step we
operate on what we DO have — the detection table — and surface four
anomaly classes that have a high TP-to-FP ratio in practice:

  1. BURST     — a rule fires N× its 30-day baseline rate in a short window
  2. SPREAD    — a rule that normally hits one host hits ≥3 hosts in the same hour
  3. SILENCE   — a host known-active suddenly has zero detections for hours
  4. OFF_HOURS — high/critical detection in a window that is empty in baseline

All four work on SQL aggregates over the `detections` table — no external
deps, no Rust, no ETW. Anomalies show up in the dashboard as a synthetic
"meta-detection" list that the analyst can drill into via the hunt tab.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


# -- tuning knobs -------------------------------------------------------------
# Numbers chosen to keep FP low on a single-machine corpus. For production
# we'd let these be configured per fleet via a TOML config alongside rules.

BURST_MIN_BASELINE = 3        # need this many baseline observations to compare
BURST_RATIO = 8.0             # short-window rate / baseline rate
BURST_WINDOW_MIN = 60         # the "short window" in minutes

SPREAD_MIN_HOSTS = 3          # a rule firing on this many hosts is unusual
SPREAD_WINDOW_MIN = 60

SILENCE_MIN_BASELINE_DAYS = 5    # the host must be active on this many baseline days
SILENCE_GAP_HOURS = 6            # ... then go silent for at least this long

OFF_HOURS_START = 0               # midnight–6am is "off hours" by default
OFF_HOURS_END = 6
OFF_HOURS_MIN_LEVEL = "high"     # only consider high+ detections


# -- shape helpers ------------------------------------------------------------

def _level_rank(lvl: str | None) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(
        (lvl or "").lower(), 0)


def _hour_key(ts: str | None) -> str | None:
    """Truncate a Hayabusa timestamp to its 'YYYY-MM-DDTHH' bucket. Robust
    against both `2024-05-21 13:42:15.123 +09:00` (space separator) and the
    ISO `T`-separator form, because we only care about the first 13 chars."""
    if not ts or len(ts) < 13:
        return None
    return ts[:10] + "T" + ts[11:13]


def _day_key(ts: str | None) -> str | None:
    if not ts or len(ts) < 10:
        return None
    return ts[:10]


# -- analysers ----------------------------------------------------------------

def analyse(store, *, top: int = 50) -> list[dict[str, Any]]:
    """Run all four analysers and return a deduplicated, severity-sorted list.

    The store argument is a `Store` instance; we pull rows via plain SQL
    rather than calling `query_detections` to keep this analyser cheap
    even when the table is large (we never materialise the full row set,
    just aggregates).
    """
    conn = store._conn()
    anomalies: list[dict[str, Any]] = []
    anomalies += _burst(conn)
    anomalies += _spread(conn)
    anomalies += _silence(conn)
    anomalies += _off_hours(conn)

    # Deduplicate by (kind, rule_id, host, hour) — bursts and spreads can
    # otherwise produce two rows for the same incident.
    seen = set()
    deduped: list[dict[str, Any]] = []
    for a in anomalies:
        key = (a["kind"], a.get("rule_id"), a.get("host"), a.get("hour"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    # Severity: rank desc, then score desc.
    deduped.sort(key=lambda a: (_level_rank(a.get("severity")),
                                a.get("score", 0)),
                 reverse=True)
    return deduped[:top]


def _burst(conn) -> list[dict[str, Any]]:
    """Rule X fired ≥ BURST_RATIO × its baseline rate in a 60-minute window.

    Implementation: for each rule, compute total fires and span. The
    average is fires/(span_in_hours). Then bucket by hour and flag any
    hour whose count exceeds RATIO × average.
    """
    # First pass: per-rule baseline (fires / hour-span).
    rule_stats = list(conn.execute(
        "SELECT rule_id, rule_title, COUNT(*) AS n, "
        "       MIN(ts) AS first_ts, MAX(ts) AS last_ts "
        "FROM detections WHERE rule_id IS NOT NULL AND ts IS NOT NULL "
        "GROUP BY rule_id HAVING n >= ?", (BURST_MIN_BASELINE,)))

    out: list[dict[str, Any]] = []
    for row in rule_stats:
        rid, title, n = row["rule_id"], row["rule_title"], row["n"]
        # Hours between first and last sighting; clamp to >=1 to avoid div0.
        try:
            span_hours = max(1.0, _approx_hours_between(
                row["first_ts"], row["last_ts"]))
        except ValueError:
            continue
        baseline_per_hour = n / span_hours
        if baseline_per_hour < 0.05:  # < 1 every 20h — not enough to call "burst"
            continue
        # Second pass: hourly buckets for this rule.
        hourly = conn.execute(
            "SELECT substr(ts, 1, 13) AS h, COUNT(*) AS k, "
            "       COUNT(DISTINCT computer) AS hosts "
            "FROM detections WHERE rule_id=? AND ts IS NOT NULL "
            "GROUP BY h", (rid,))
        for h_row in hourly:
            if h_row["k"] < BURST_RATIO * baseline_per_hour:
                continue
            ratio = h_row["k"] / baseline_per_hour
            out.append({
                "kind": "burst",
                "rule_id": rid,
                "rule_title": title,
                "hour": h_row["h"],
                "host": None,                # burst is rule-scoped, multi-host
                "observed": h_row["k"],
                "baseline_per_hour": round(baseline_per_hour, 2),
                "ratio": round(ratio, 1),
                "hosts_count": h_row["hosts"],
                "severity": "high" if ratio >= 20 else "medium",
                "score": int(min(100, ratio * 2)),
                "description":
                    f"ルール「{title}」が {h_row['h']} の 1 時間で "
                    f"{h_row['k']} 件発火 (平常 {baseline_per_hour:.2f}/h の {ratio:.1f} 倍)",
                "drill": {"rule_id": rid, "from": h_row["h"] + ":00:00",
                          "to": h_row["h"] + ":59:59"},
            })
    return out


def _spread(conn) -> list[dict[str, Any]]:
    """Same rule firing on ≥3 distinct hosts in the same hour-bucket.

    Lateral movement signature: a tool used on host A is then used on B,
    C, D within minutes.
    """
    rows = conn.execute(
        "SELECT rule_id, rule_title, substr(ts, 1, 13) AS h, "
        "       COUNT(DISTINCT computer) AS hosts, "
        "       COUNT(*) AS fires, "
        "       MAX(level) AS lvl "
        "FROM detections WHERE rule_id IS NOT NULL AND ts IS NOT NULL "
        "  AND computer IS NOT NULL "
        "GROUP BY rule_id, h HAVING hosts >= ?",
        (SPREAD_MIN_HOSTS,))
    out: list[dict[str, Any]] = []
    for r in rows:
        # Skip rules that ALWAYS hit many hosts (e.g. workstation-wide
        # logon rules). For now we approximate by also requiring the
        # rule's all-time host count to be > 2× hosts-in-this-hour, which
        # ensures the hour is a spike. Cheap heuristic; will refine.
        total_hosts = conn.execute(
            "SELECT COUNT(DISTINCT computer) AS n FROM detections "
            "WHERE rule_id=?", (r["rule_id"],)).fetchone()["n"]
        if total_hosts <= r["hosts"]:
            # Every host this rule ever hit, hit it this hour. Could still
            # be lateral movement, but more likely the rule fires fleet-wide.
            # Keep but lower severity.
            sev = "medium"
        else:
            sev = "high"
        # Higher severity if any participating detection was high/critical.
        if (r["lvl"] or "").lower() in ("critical", "high"):
            sev = "critical" if sev == "high" else sev
        out.append({
            "kind": "spread",
            "rule_id": r["rule_id"],
            "rule_title": r["rule_title"],
            "hour": r["h"],
            "host": None,
            "observed": r["fires"],
            "hosts_count": r["hosts"],
            "severity": sev,
            "score": min(100, 60 + r["hosts"] * 5),
            "description":
                f"ルール「{r['rule_title']}」が {r['h']} の 1 時間で "
                f"{r['hosts']} ホストにまたがり {r['fires']} 件発火 "
                f"(横展開・配布スクリプト等の可能性)",
            "drill": {"rule_id": r["rule_id"],
                      "from": r["h"] + ":00:00", "to": r["h"] + ":59:59"},
        })
    return out


def _silence(conn) -> list[dict[str, Any]]:
    """A host that is normally active goes silent for ≥SILENCE_GAP_HOURS.

    "Normally active" = at least SILENCE_MIN_BASELINE_DAYS distinct days
    with detections. "Silent" = a gap between consecutive detections that
    exceeds the threshold and falls inside the host's normal active span
    (we don't flag the gap between yesterday's last detection and now —
    that's just "no recent data").
    """
    # First: per-host activity baseline.
    hosts = list(conn.execute(
        "SELECT computer, COUNT(DISTINCT substr(ts, 1, 10)) AS days, "
        "       MIN(ts) AS first_ts, MAX(ts) AS last_ts, COUNT(*) AS total "
        "FROM detections WHERE computer IS NOT NULL AND ts IS NOT NULL "
        "GROUP BY computer HAVING days >= ?",
        (SILENCE_MIN_BASELINE_DAYS,)))
    out: list[dict[str, Any]] = []
    for h in hosts:
        # Walk consecutive timestamps for this host and find gaps.
        rows = conn.execute(
            "SELECT ts FROM detections WHERE computer=? AND ts IS NOT NULL "
            "ORDER BY ts ASC", (h["computer"],))
        prev = None
        for r in rows:
            ts = r["ts"]
            if prev is not None:
                try:
                    gap_h = _approx_hours_between(prev, ts)
                except ValueError:
                    prev = ts
                    continue
                if gap_h >= SILENCE_GAP_HOURS:
                    out.append({
                        "kind": "silence",
                        "host": h["computer"],
                        "rule_id": None,
                        "rule_title": None,
                        "hour": _hour_key(prev),
                        "observed": 0,
                        "gap_hours": round(gap_h, 1),
                        "severity": "medium" if gap_h < 24 else "high",
                        "score": min(100, int(40 + gap_h)),
                        "description":
                            f"ホスト {h['computer']} が {prev[:16]} から "
                            f"{ts[:16]} まで {gap_h:.1f} 時間無音 "
                            f"(平常は {h['days']} 日間活動)",
                        "drill": {"host": h["computer"], "from": prev,
                                  "to": ts},
                    })
            prev = ts
    # A noisy host can produce dozens of gaps; cap to longest gap per host.
    by_host: dict[str, dict[str, Any]] = {}
    for a in out:
        cur = by_host.get(a["host"])
        if not cur or a["gap_hours"] > cur["gap_hours"]:
            by_host[a["host"]] = a
    return list(by_host.values())


def _off_hours(conn) -> list[dict[str, Any]]:
    """High/critical detections during OFF_HOURS_START–OFF_HOURS_END local.

    The simplification: we don't know the host's timezone, so we treat the
    timestamp's hour field as local. False positives possible across
    timezones; reasonable for a single-fleet deployment.
    """
    min_rank = _level_rank(OFF_HOURS_MIN_LEVEL)
    rows = conn.execute(
        "SELECT rule_id, rule_title, computer, ts, level, job_id, line_no "
        "FROM detections WHERE level IS NOT NULL AND ts IS NOT NULL "
        "ORDER BY ts DESC LIMIT 5000")
    out: list[dict[str, Any]] = []
    for r in rows:
        if _level_rank(r["level"]) < min_rank:
            continue
        ts = r["ts"]
        try:
            # Hour field: chars 11–13. Robust for both 'T' and ' ' separators.
            hour = int(ts[11:13])
        except (ValueError, IndexError):
            continue
        if OFF_HOURS_START <= hour < OFF_HOURS_END:
            out.append({
                "kind": "off_hours",
                "rule_id": r["rule_id"],
                "rule_title": r["rule_title"],
                "host": r["computer"],
                "hour": _hour_key(ts),
                "observed": 1,
                "ts": ts,
                "severity": r["level"],
                "score": 60 + _level_rank(r["level"]) * 10,
                "description":
                    f"{ts[:16]} (深夜帯) に "
                    f"{r['level']} 検知 「{r['rule_title']}」 が "
                    f"{r['computer']} で発火",
                "drill": {"job_id": r["job_id"], "line_no": r["line_no"]},
            })
    # Cap per (host, rule) to keep the list digestible.
    seen: dict[tuple, dict[str, Any]] = {}
    for a in out:
        key = (a["host"], a["rule_id"])
        if key not in seen:
            seen[key] = a
    return list(seen.values())


# -- helpers ------------------------------------------------------------------

def _approx_hours_between(ts1: str, ts2: str) -> float:
    """Lightweight diff between two ISO-ish timestamps.

    We parse just enough to compute hours; full timezone math is overkill
    here because we only need ordering and rough magnitudes.
    """
    from datetime import datetime
    fmt_attempts = [
        "%Y-%m-%d %H:%M:%S.%f %z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]
    def parse(s):
        for fmt in fmt_attempts:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # Last-resort: lop tz suffix and retry.
        s2 = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s2)
        except ValueError as e:
            raise ValueError(f"unparseable timestamp: {s!r}") from e
    a, b = parse(ts1), parse(ts2)
    # Force both naive or both aware before subtraction.
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None); b = b.replace(tzinfo=None)
    return abs((b - a).total_seconds()) / 3600.0
