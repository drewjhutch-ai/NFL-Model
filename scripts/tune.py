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
    try:
        weekly = loaders.load_weekly_player()
    except Exception as exc:  # noqa: BLE001 - calibration is optional
        print(f"[tune] weekly player stats unavailable ({exc}); skipping reconcile calibration.")
        weekly = None
    result = tuning.tune(pbp, schedule, args.season, weekly=weekly)

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
    print(f"       MARKET_WEIGHT {result['prev_market']:.3f} -> {payload['market_weight']:.3f} "
          f"(best-fit {payload['recommended_market_weight']:.2f})")
    print(f"       out-of-sample: MAE {m.get('model_mae')} (mkt {m.get('market_mae')}) · "
          f"ATS {m.get('ats_pct')}% · SU {m.get('su_pct')}%")
    ps = payload.get("prop_tuning", {})
    print(f"       prop-side: {ps.get('status')} ({ps.get('weeks', 0)} wk banked; "
          f"need {tuning.MIN_PROP_WEEKS}) — PROP_MODEL_TRUST held at {config.PROP_MODEL_TRUST}")
    rc = payload.get("reconcile")
    if rc:
        f = rc.get("fit", {})
        print(f"       reconcile (n={rc.get('n')}): yds/pt {config.RECON_YARDS_PER_POINT}→"
              f"{rc['yards_per_point']} (fit {f.get('yards_per_point')}) · "
              f"capture {config.RECON_RECEIVER_CAPTURE}→{rc['receiver_capture']} · "
              f"pass-share {config.RECON_PASS_SHARE}→{rc['pass_share']}")
    else:
        rs = payload.get("reconcile_status", {})
        print(f"       reconcile: {rs.get('status','n/a')} (n={rs.get('n',0)}) — anchors held")
    print(f"       wrote {tuning._TUNING_FILE.name} + appended {tuning._LOG_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
