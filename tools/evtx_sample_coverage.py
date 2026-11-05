#!/usr/bin/env python3
"""Measure Hayabusa detection coverage against an EVTX sample directory.

The EVTX-ATTACK-SAMPLES repository contains many small, self-contained EVTX
files. Scanning them individually is slower than one directory scan, but it is
the only reliable way to say which sample produced which detection.

Usage:
    python3 tools/evtx_sample_coverage.py --dataset /path/to/evtx-attack-samples
    python3 tools/evtx_sample_coverage.py --dataset ... --workers 4 --json-out coverage.json

The script intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def find_engine(explicit: str | None, root: Path) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"engine not found: {p}")
        return p.resolve()
    names = (("hayabusa-fx-3.10.0.exe", "hayabusa.exe", "hayabusa-fx")
             if sys.platform == "win32"
             else ("hayabusa-fx", "hayabusa"))
    for name in names:
        p = root / "bin" / name
        if p.is_file():
            return p.resolve()
    raise SystemExit("Hayabusa engine not found in bin/. Use --engine.")


def scan_one(engine: Path, rules: Path, sample: Path, min_level: str,
             all_rules: bool, timeout: int) -> dict:
    fd, tmp_name = tempfile.mkstemp(prefix="hayfx-coverage-", suffix=".jsonl")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        cmd = [
            str(engine), "json-timeline", "-f", str(sample),
            "-r", str(rules), "-L", "-o", str(tmp),
            "-q", "-K", "-b", "-C", "-m", min_level, "-w",
        ]
        if all_rules:
            cmd.append("-A")
        started = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=str(engine.parent))
        elapsed = time.time() - started
        titles: list[str] = []
        levels: dict[str, int] = {}
        text = ""
        if tmp.exists():
            for _ in range(3):
                try:
                    text = tmp.read_text(encoding="utf-8", errors="replace")
                    break
                except OSError:
                    time.sleep(0.2)
        if text:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                title = event.get("RuleTitle") or event.get("RuleID") or "(unknown)"
                titles.append(title)
                level = (event.get("Level") or "unknown").lower()
                levels[level] = levels.get(level, 0) + 1
        return {
            "file": sample.name,
            "path": str(sample),
            "count": len(titles),
            "levels": levels,
            "rules": sorted(set(titles)),
            "elapsed_sec": round(elapsed, 2),
            "exit_code": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"file": sample.name, "path": str(sample), "count": 0,
                "levels": {}, "rules": [], "elapsed_sec": timeout,
                "exit_code": -1, "stderr_tail": "timeout"}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True,
                        help="directory containing .evtx samples")
    parser.add_argument("--engine", default=None)
    parser.add_argument("--rules", default=None,
                        help="rule directory (default: <repo>/bin/rules)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-level", default="low",
                        choices=("informational", "low", "medium", "high", "critical"))
    parser.add_argument("--all-rules", action="store_true",
                        help="pass -A (enable all rules regardless of channel)")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    engine = find_engine(args.engine, repo)
    rules = Path(args.rules).resolve() if args.rules else (repo / "bin" / "rules").resolve()
    dataset = Path(args.dataset).resolve()
    samples = sorted(dataset.rglob("*.evtx"))
    if not samples:
        raise SystemExit(f"no .evtx files under {dataset}")
    workers = max(1, min(args.workers, 16))

    print(f"engine : {engine}")
    print(f"rules  : {rules}")
    print(f"samples: {len(samples)}")
    print(f"workers: {workers}  min-level: {args.min_level}  all-rules: {args.all_rules}")
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(scan_one, engine, rules, sample, args.min_level,
                        args.all_rules, args.timeout): sample
            for sample in samples
        }
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            result = fut.result()
            results.append(result)
            if i % 25 == 0 or i == len(samples):
                hit = sum(1 for r in results if r["count"] > 0)
                print(f"  {i:4d}/{len(samples)}  covered={hit}", flush=True)

    results.sort(key=lambda r: r["file"].lower())
    covered = [r for r in results if r["count"] > 0]
    missed = [r for r in results if r["count"] == 0]
    print()
    print(f"covered: {len(covered)}/{len(results)} "
          f"({len(covered) / len(results) * 100:.1f}%)")
    print(f"missed : {len(missed)}")
    for r in missed:
        print(f"  MISS {r['file']}")
    print()
    print("top rules:")
    counts: dict[str, int] = {}
    for r in results:
        for title in r["rules"]:
            counts[title] = counts.get(title, 0) + 1
    for title, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        print(f"  {n:4d}  {title}")

    if args.json_out:
        out = Path(args.json_out)
        out.write_text(json.dumps({
            "dataset": str(dataset),
            "engine": str(engine),
            "rules": str(rules),
            "covered": len(covered),
            "total": len(results),
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
