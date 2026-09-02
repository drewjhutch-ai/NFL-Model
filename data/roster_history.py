"""Current-roster snapshots — a committed fallback + transaction history.

The pipeline reads the live Sleeper roster, but live feeds flake (we just watched
ESPN hard-block a datacenter). So the weekly Action also commits a roster
snapshot, and the pipeline falls back to it when the live pull fails — the app
never loses current team assignments. Keeping dated snapshots also lets the model
*see transactions*: diff the newest two to find who was traded, signed, or cut.

Snapshot columns: snapshot (ISO date), season, player_id, name, team, pos,
number, status. Latest snapshot per day (idempotent).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "rosters_data"
_COLS = ["snapshot", "season", "player_id", "name", "team", "pos", "number", "status"]


def path(season: int) -> Path:
    return _DIR / f"rosters_{season}.csv"


def write_snapshot(roster: pd.DataFrame, season: int, stamp: str | None = None) -> int:
    """Append today's roster snapshot to the season file (idempotent per day)."""
    if roster is None or roster.empty:
        return 0
    stamp = stamp or _dt.date.today().isoformat()
    df = roster.copy()
    df["snapshot"] = stamp
    df["season"] = season
    for c in _COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[_COLS]
    _DIR.mkdir(exist_ok=True)
    p = path(season)
    if p.exists():
        try:
            prev = pd.read_csv(p)
            prev = prev[prev["snapshot"].astype(str) != str(stamp)]
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


def load_latest(season: int) -> pd.DataFrame:
    """The most recent committed roster snapshot (team/pos per player)."""
    h = load_history(season)
    if h.empty or "snapshot" not in h.columns:
        return pd.DataFrame()
    latest = h[h["snapshot"].astype(str) == str(h["snapshot"].max())]
    return latest.reset_index(drop=True)


def recent_moves(season: int) -> list[dict]:
    """Team changes between the two most recent snapshots — the transaction log."""
    h = load_history(season)
    if h.empty or "snapshot" not in h.columns:
        return []
    stamps = sorted(str(s) for s in h["snapshot"].dropna().unique())
    if len(stamps) < 2:
        return []
    prev = h[h["snapshot"].astype(str) == stamps[-2]].set_index("player_id")
    cur = h[h["snapshot"].astype(str) == stamps[-1]].set_index("player_id")
    moves = []
    for pid, row in cur.iterrows():
        if pid in prev.index:
            old = str(prev.loc[pid, "team"]) if not isinstance(prev.loc[pid], pd.DataFrame) else None
            new = str(row["team"])
            if old and old != "nan" and old != new:
                moves.append({"player_id": pid, "name": row.get("name", ""),
                              "pos": row.get("pos", ""), "from": old, "to": new})
    return moves
