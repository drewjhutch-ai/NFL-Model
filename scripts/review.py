#!/usr/bin/env python3
"""Weekly game review — cross-references facets against what actually happened.

Run by the GitHub Action after games settle, right beside the self-tuner. Grades
the season's accuracy and, for every facet edge the model flagged, checks whether
the flagged side actually won — a per-facet hit rate. Appends the result to
review_log.csv so the learning loop is auditable ("coverage-fit hit 71%").

Exit codes:
    0  wrote a review (there were graded games)
    2  nothing to grade yet (offseason / too early)

Usage:
    python scripts/review.py [--season 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data import loaders, review  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    pbp = loaders.load_pbp()
    schedule = loaders.load_schedule()
    summary = review.weekly_review(pbp, schedule, args.season)

    if not summary.get("graded_games"):
        print(f"[review] nothing to grade for {args.season} yet.")
        return 2

    review.append_review_log(summary)
    print(f"[review] {summary['headline']}")
    for f in summary.get("facets", []):
        print(f"       {f['facet']:16} hit {f['hit_rate']:5}%  "
              f"({f['hits']}/{f['n_flagged']} flagged, r={f.get('correlation')})")
    print(f"[review] appended {review._REVIEW_LOG.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
