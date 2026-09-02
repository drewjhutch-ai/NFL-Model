#!/usr/bin/env python3
"""Snapshot the week's injury picture and commit it for persistence tracking.

Run by ``.github/workflows/update-coverage.yml`` on a schedule. Captures two free
sources into one timestamped row set so the model can later see how *long* a
player has been hurt (lingering injuries the market is slow to price):

    * nflverse weekly report  — status + practice participation (the tell)
    * Sleeper feed            — season-long IR / PUP / suspensions, year-round

Appended to ``injury_snapshots/injuries_<season>.csv`` (idempotent per day). The
app reads it via ``data/injury_history.persistence`` and weights chronic cases.

Exit codes:
    0  wrote a snapshot (rows captured)
    2  nothing to snapshot (no sources answered)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from data import injury_history, loaders
from data.teams import normalize_team


def _nflverse_rows(season: int):
    """Weekly report rows (status + practice) for the latest reported week."""
    rows, week = [], None
    try:
        inj = loaders.load_injuries()
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_injuries] nflverse report unavailable: {exc}")
        return rows, week
    if inj is None or inj.empty or "season" not in inj.columns:
        return rows, week
    inj = inj[inj["season"] == season]
    if inj.empty:
        return rows, week
    week = int(inj["week"].max())
    cur = inj[inj["week"] == week]
    for r in cur.itertuples():
        status = (getattr(r, "report_status", "") or "").strip()
        practice = (getattr(r, "practice_status", "") or "").strip()
        if not status and not practice:
            continue
        team = normalize_team(getattr(r, "team", None))
        if not team:
            continue
        rows.append({
            "team": team, "name": getattr(r, "full_name", "") or "",
            "pos": (getattr(r, "position", "") or "").upper(),
            "status": status, "practice": practice, "source": "nflverse",
        })
    return rows, week


def _sleeper_rows():
    """Season-long designations (IR/PUP/suspended + current game status)."""
    rows = []
    try:
        from data.providers import sleeper_injuries
        df = sleeper_injuries.fetch()
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_injuries] Sleeper feed unavailable: {exc}")
        return rows
    if df is None or df.empty:
        return rows
    for r in df.itertuples():
        rows.append({
            "team": getattr(r, "team", ""), "name": getattr(r, "name", ""),
            "pos": getattr(r, "pos", ""), "status": getattr(r, "espn_status", ""),
            "practice": "", "source": "sleeper",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()
    season = args.season

    nfl_rows, week = _nflverse_rows(season)
    sleeper_rows = _sleeper_rows()

    # Prefer the nflverse row for a player (it carries practice detail); add
    # Sleeper rows for anyone not on the weekly report (IR/PUP/suspended).
    seen = {(r["team"], r["name"].lower()) for r in nfl_rows}
    merged = list(nfl_rows)
    for r in sleeper_rows:
        if (r["team"], (r["name"] or "").lower()) not in seen:
            merged.append(r)

    if not merged:
        print("[snapshot_injuries] no injury data from either source — nothing to snapshot.")
        return 2

    n = injury_history.write_snapshot(merged, season, week=week)
    persist = injury_history.persistence(season)
    chronic = sum(1 for v in persist.values() if v["weeks"] >= 3)
    print(f"[snapshot_injuries] wrote {n} rows (week {week}) -> {injury_history.path(season).name}")
    print(f"[snapshot_injuries] tracked players: {len(persist)} · chronic (3+ wk): {chronic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
