"""Injury-report history — persistence tracking for lingering injuries.

A single weekly report can't tell you a knee has been nagging a receiver for a
month. This module snapshots the injury picture each week (committed by the
GitHub Action, the same pattern as the Sharp data) and, on read, computes how
many weeks each player has carried a limiting designation. Chronic cases — a WR1
who's been *limited in practice* four weeks running — are the ones the market is
slowest to price, so the valuation weights them harder.

Snapshot rows: snapshot (ISO date), season, week, team, name, pos, status,
practice, source. One append per run; a re-run on the same day is idempotent.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "injury_snapshots"
# Designations that count as "on the report" for persistence.
_LIMIT_STATUSES = {"Out", "Doubtful", "Questionable", "IR", "PUP", "Suspended", "Day-To-Day"}
_COLS = ["snapshot", "season", "week", "team", "name", "pos", "status", "practice", "source"]


def path(season: int) -> Path:
    return _DIR / f"injuries_{season}.csv"


def write_snapshot(rows: list[dict], season: int, week=None, stamp: str | None = None) -> int:
    """Append today's injury snapshot to the season file (idempotent per day)."""
    if not rows:
        return 0
    stamp = stamp or _dt.date.today().isoformat()
    df = pd.DataFrame(rows)
    df["snapshot"] = stamp
    df["season"] = season
    if "week" not in df.columns:
        df["week"] = week
    for c in _COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[_COLS]
    _DIR.mkdir(exist_ok=True)
    p = path(season)
    if p.exists():
        try:
            prev = pd.read_csv(p)
            prev = prev[prev["snapshot"].astype(str) != str(stamp)]  # re-run replaces today
            out = pd.concat([prev, df], ignore_index=True)
        except Exception:  # noqa: BLE001
            out = df
    else:
        out = df
    out.to_csv(p, index=False)
    return len(df)


def load_history(season: int) -> pd.DataFrame:
    p = path(season)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def persistence(season: int) -> dict:
    """(team, name_lower) -> {weeks, first, last, statuses} across limiting snapshots.

    ``weeks`` is the count of distinct snapshot dates the player appeared with a
    limiting designation — the persistence signal for chronic / lingering injuries.
    """
    h = load_history(season)
    if h.empty or "status" not in h.columns:
        return {}
    lim = h[h["status"].isin(_LIMIT_STATUSES)]
    if lim.empty:
        return {}
    out: dict = {}
    for (team, name), g in lim.groupby(["team", "name"]):
        snaps = sorted(str(s) for s in g["snapshot"].dropna().unique())
        out[(str(team), str(name).lower())] = {
            "weeks": len(snaps),
            "first": snaps[0] if snaps else "",
            "last": snaps[-1] if snaps else "",
            "statuses": sorted(str(s) for s in g["status"].dropna().unique()),
        }
    return out
