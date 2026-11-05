#!/usr/bin/env python3
"""Validate the rule-test EVTX fixtures against their expected detections.

Usage:
    python tools/check_rule_samples.py
    python tools/check_rule_samples.py --engine bin/hayabusa-fx-3.10.0.exe

The script only uses the Python standard library. It runs the local Hayabusa
engine against samples/rule-tests and compares the positive fixture with
expected.json. It also checks that the negative control does not fire any of
the new custom rules.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
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


def read_json_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    records: list[dict] = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            record, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        if isinstance(record, dict):
            records.append(record)
    return records


def scan(engine: Path, rules: Path, sample: Path, timeout: int) -> list[dict]:
    fd, tmp_name = tempfile.mkstemp(prefix="hayfx-rule-check-", suffix=".jsonl")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        cmd = [
            str(engine), "json-timeline", "-f", str(sample),
            "-r", str(rules), "-L", "-o", str(tmp),
            "-q", "-K", "-b", "-C", "-m", "low", "-w",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=str(engine.parent),
        )
        if not tmp.exists():
            raise SystemExit(
                f"engine produced no output for {sample.name}\n"
                f"stderr: {proc.stderr[-800:]}"
            )
        return read_json_records(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default=None)
    parser.add_argument("--rules", default=str(root / "rules-custom"))
    parser.add_argument("--samples", default=str(root / "samples" / "rule-tests"))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    engine = find_engine(args.engine, root)
    rules = Path(args.rules)
    samples = Path(args.samples)
    expected_path = samples / "expected.json"
    positive = samples / "hayfx-2026-detections.evtx"
    negative = samples / "hayfx-negative-control.evtx"

    for path in (rules, expected_path, positive, negative):
        if not path.exists():
            raise SystemExit(f"missing: {path}")

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected_by_record = {int(row["record_id"]): row for row in expected}
    expected_rule_ids = {row["rule_id"] for row in expected}

    print(f"engine: {engine}")
    print(f"rules : {rules}")
    print(f"sample: {positive.name}")

    positive_hits = scan(engine, rules, positive, args.timeout)
    actual = {
        int(row.get("RecordID", -1)): row
        for row in positive_hits
        if row.get("RuleID") in expected_rule_ids
    }

    failures: list[str] = []
    for record_id, want in sorted(expected_by_record.items()):
        got = actual.get(record_id)
        if not got:
            failures.append(f"record {record_id}: missing {want['rule_id']}")
            continue
        if got.get("RuleID") != want["rule_id"]:
            failures.append(
                f"record {record_id}: expected {want['rule_id']}, "
                f"got {got.get('RuleID')}"
            )
        elif str(got.get("Level", "")).lower() != want["level"].lower():
            failures.append(
                f"record {record_id}: expected level {want['level']}, "
                f"got {got.get('Level')}"
            )

    extra = sorted(set(actual) - set(expected_by_record))
    for record_id in extra:
        failures.append(
            f"record {record_id}: unexpected rule "
            f"{actual[record_id].get('RuleID')}"
        )

    negative_hits = scan(engine, rules, negative, args.timeout)
    negative_new = [
        row for row in negative_hits if row.get("RuleID") in expected_rule_ids
    ]
    for row in negative_new:
        failures.append(
            f"negative control: unexpected {row.get('RuleID')} "
            f"(record {row.get('RecordID')})"
        )

    print(f"positive: {len(actual)}/{len(expected_by_record)} expected rules fired")
    print(f"negative: {len(negative_new)} unexpected new-rule detections")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nOK: samples match expected detections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
