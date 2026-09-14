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


def _clean(x) -> str:
    """Coerce any cell to a stripped string. A DataFrame cell can be NaN (a
    ``float``), and ``getattr(row, col, "")`` returns that NaN — not the default —
    because the attribute *exists*; NaN is also truthy, so ``x or ""`` keeps it.
    Guarding on ``isinstance(str)`` is what actually protects the ``.strip()``.
    """
    return x.strip() if isinstance(x, str) else ""


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
        status = _clean(getattr(r, "report_status", ""))
        practice = _clean(getattr(r, "practice_status", ""))
        if not status and not practice:
            continue
        team = normalize_team(_clean(getattr(r, "team", "")) or None)
        if not team:
            continue
        rows.append({
            "team": team, "name": _clean(getattr(r, "full_name", "")),
            "pos": _clean(getattr(r, "position", "")).upper(),
            "status": status, "practice": practice, "source": "nflverse",
        })
    return rows, week


def _sleeper_rows():
    """Season-long designations (IR/PUP/suspended + current game status).

    Uses the shared Sleeper provider — the same single memoized player pull the
    roster snapshot uses — so both snapshots ride one 5 MB download and share one
    code path, rather than a second, separately-maintained fetch.
    """
    rows = []
    try:
        from data.providers import sleeper
        by_team = sleeper.injuries_by_team()
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_injuries] Sleeper feed unavailable: {exc}")
        return rows
    if not by_team:
        return rows
    for team, df in by_team.items():
        if df is None or df.empty:
            continue
        for r in df.itertuples():
            rows.append({
                "team": _clean(getattr(r, "team", "")) or team,
                "name": _clean(getattr(r, "name", "")),
                "pos": _clean(getattr(r, "pos", "")).upper(),
                "status": _clean(getattr(r, "espn_status", "")),
                "practice": "", "source": "sleeper",
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()
    season = args.season

    # Each source is isolated: a failure in one must not abort the other, so a
    # broken weekly report can't wipe out the season-long Sleeper feed (the bug
    # that froze this snapshot for a week), and vice versa.
    try:
        nfl_rows, week = _nflverse_rows(season)
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_injuries] nflverse rows failed: {exc}")
        nfl_rows, week = [], None
    try:
        sleeper_rows = _sleeper_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"[snapshot_injuries] sleeper rows failed: {exc}")
        sleeper_rows = []
    print(f"[snapshot_injuries] sources: nflverse={len(nfl_rows)} sleeper={len(sleeper_rows)}")

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
