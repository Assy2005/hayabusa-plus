#!/usr/bin/env python
"""
CLI: fetch IoC feeds declared in lookups/feeds.yml and write them to
lookups/<output>.txt.

Usage:
    python tools/fetch_feeds.py              # fetch all feeds
    python tools/fetch_feeds.py loldrivers   # fetch only the named feed(s)
    python tools/fetch_feeds.py --dry-run    # parse the manifest, print summary

Designed to be cron-able: silent on success (exit 0), prints a single-line
summary to stderr on partial failure (exit 2), exits 1 on hard error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gui"))
import feed_fetcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("feeds", nargs="*",
                        help="optional feed names to limit to (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be fetched without doing it")
    args = parser.parse_args()

    lookups_dir = ROOT / "lookups"
    manifest = lookups_dir / "feeds.yml"

    if args.dry_run:
        if not manifest.exists():
            print(f"no manifest at {manifest}", file=sys.stderr)
            return 1
        feeds = feed_fetcher._load_feeds_yaml(manifest)
        wanted = set(args.feeds) if args.feeds else None
        for f in feeds:
            if wanted and f.get("name") not in wanted:
                continue
            print(f"{f.get('name'):25}  {f.get('url')}  -> {f.get('output')}")
        return 0

    results = feed_fetcher.fetch_all(
        lookups_dir, manifest=manifest,
        filter_names=args.feeds if args.feeds else None)

    ok, fail = 0, 0
    for r in results:
        name = r.get("name") or r.get("output") or "?"
        if r.get("error"):
            fail += 1
            print(f"[FAIL] {name}: {r['error']}", file=sys.stderr)
        else:
            ok += 1
            print(f"[ OK ] {name}: {r.get('entries')} entries "
                  f"({r.get('bytes_in')} B, {r.get('elapsed_sec')}s)")
    if fail and ok:
        return 2
    if fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
