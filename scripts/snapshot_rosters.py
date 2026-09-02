#!/usr/bin/env python3
"""Snapshot current rosters and commit them — the base current-team layer.

Run by ``.github/workflows/update-coverage.yml`` on a schedule. Pulls the live
Sleeper roster (team + position for every rostered player) and appends a dated
snapshot to ``rosters_data/rosters_<season>.csv``. The app reads the latest
snapshot as a fallback when the live feed is down, and diffs consecutive
snapshots to surface transactions (trades / signings / cuts) through the season.

Exit codes:
    0  wrote a roster snapshot
    2  the feed returned nothing (nothing to snapshot)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from data import roster_history
from data.providers import sleeper


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    roster = sleeper.current_rosters()
    if roster is None or roster.empty:
        print(f"[snapshot_rosters] roster feed empty ({sleeper.last_error()}) — nothing to snapshot.")
        return 2

    n = roster_history.write_snapshot(roster, args.season)
    moves = roster_history.recent_moves(args.season)
    print(f"[snapshot_rosters] wrote {n} players ({roster['team'].nunique()} teams) "
          f"-> {roster_history.path(args.season).name}")
    if moves:
        print(f"[snapshot_rosters] {len(moves)} roster moves since last snapshot:")
        for m in moves[:20]:
            print(f"    {m['name']} ({m['pos']}): {m['from']} -> {m['to']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
