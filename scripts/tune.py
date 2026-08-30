#!/usr/bin/env python3
"""Weekly self-tuning — the model re-fits itself from results.

Run by the GitHub Action after games settle. Grades the season so far, searches
for the settings that would have predicted it best, nudges the live config toward
them, and writes model_tuning.json (which config.py overlays on the defaults).

Exit codes:
    0  wrote an updated tuning (the model learned something)
    2  held — not enough graded games yet (offseason / early weeks)

Usage:
    python scripts/tune.py [--season 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data import loaders, tuning  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    pbp = loaders.load_pbp()
    schedule = loaders.load_schedule()
    result = tuning.tune(pbp, schedule, args.season)

    if result["status"] == "held":
        print(f"[tune] holding defaults — {result['reason']}.")
        return 2

    payload = result["payload"]
    tuning.write(payload)
    tuning.append_log(payload)
    m = payload["metrics"]
    print(f"[tune] learned from {payload['graded_games']} games (season {payload['season']}):")
    print(f"       POINTS_WEIGHT {result['prev_points']:.3f} -> {payload['points_weight']:.3f} "
          f"(best-fit {payload['recommended_points_weight']:.2f})")
    print(f"       out-of-sample: MAE {m.get('model_mae')} (mkt {m.get('market_mae')}) · "
          f"ATS {m.get('ats_pct')}% · SU {m.get('su_pct')}%")
    print(f"       wrote {tuning._TUNING_FILE.name} + appended {tuning._LOG_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
