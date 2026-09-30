#!/usr/bin/env python3
"""Bank this week's posted player-prop lines for the prop-side tuner.

The free odds feed only returns *current* lines, so to ever tune the prop
market-blend (``config.PROP_MODEL_TRUST``) we have to store the lines ourselves as
they're posted. This writes them to ``prop_line_history/props_<season>_w<week>.csv``
(one file per week, overwritten with the latest pull), which ``data/prop_history``
reads and the learning loop grades once enough weeks accrue.

Needs an Odds API key in the environment (``ODDS_API_KEY``) — the same key the app
uses, added as a GitHub Actions secret so the weekly workflow can pull it. Without
a key (or if the pull is empty) it's a clean no-op.

Exit codes:
    0  banked this week's lines
    2  no key / no lines / no current week (nothing written)

Usage:
    python scripts/snapshot_prop_lines.py [--season 2026] [--week 5]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data import loaders, odds_providers as op, prop_history  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    if not op.get_odds_provider().is_available():
        print("[snapshot_prop_lines] no ODDS_API_KEY in the environment — nothing to bank.")
        return 2

    try:
        schedule = loaders.load_schedule()
        week = args.week or loaders.current_week(schedule, args.season)
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_prop_lines] couldn't resolve the current week: {exc}")
        week = args.week
    if not week:
        print("[snapshot_prop_lines] no current week yet — nothing to bank.")
        return 2

    df = op.player_props()
    if df is None or df.empty:
        print("[snapshot_prop_lines] the odds feed returned no prop lines — nothing banked.")
        return 2

    df = df.copy()
    df["season"] = args.season
    df["week"] = int(week)
    df["ts"] = _dt.datetime.utcnow().isoformat(timespec="minutes")
    prop_history.dir_path().mkdir(parents=True, exist_ok=True)
    path = prop_history.path_for(args.season, week)
    df.to_csv(path, index=False)   # overwrite: keep the latest pull for the week
    print(f"[snapshot_prop_lines] banked {len(df)} prop rows for week {week} -> {path.name} "
          f"({prop_history.weeks_available(args.season)} week(s) on file).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
