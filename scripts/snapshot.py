#!/usr/bin/env python3
"""Freeze this week's model state — the Evolution Engine's weekly heartbeat.

Run by the GitHub Action every week. It rebuilds the full model (same pipeline
the app uses), then writes two committed files:

    history/team_history_<season>.csv   ranks + power rating per team, per week
    history/proj_history_<season>.csv   our pre-game projections, per game

Accumulated week over week, these give the app a memory: rank-movement arrows,
trend sparklines, and a real report card (last week's projections graded against
the results that have since landed).

Exit codes:
    0  wrote a snapshot
    2  no current-season games yet (nothing to snapshot — offseason)

Usage:
    python scripts/snapshot.py [--season 2026] [--week 5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data import history, loaders, pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    ap.add_argument("--week", type=int, default=None,
                    help="Override the week to snapshot (default: latest completed).")
    args = ap.parse_args()

    off, deff, blitz, live, schedule, extras = pipeline.build_frames()
    if not live:
        print(f"[snapshot] no {args.season} games yet — offseason, nothing to freeze.")
        return 2

    week = args.week or loaders.current_week(schedule, args.season)
    if not week:
        print("[snapshot] couldn't determine the current week.")
        return 2

    team_frame = history.snapshot_frame(off, deff, extras, args.season, week)
    path = history.write_snapshot(team_frame, args.season, week)
    print(f"[snapshot] wrote {len(team_frame)} teams for week {week} -> {path}")

    proj = history.snapshot_projections(schedule, off, deff, extras, args.season, week)
    ppath = history.write_projections(proj, args.season, week)
    if ppath is not None:
        print(f"[snapshot] wrote {len(proj)} game projections -> {ppath}")

    # Report the running grade so the Action log shows the model's accuracy.
    grade = history.grade_projections(history.load_projections(args.season), schedule)
    if grade:
        bits = [f"{k.upper()} {v['hit']}/{v['n']} ({v['pct']*100:.0f}%)"
                for k, v in grade.items()]
        print("[snapshot] report card so far — " + " · ".join(bits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
