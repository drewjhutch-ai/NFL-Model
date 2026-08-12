"""Player usage and matchup-adjusted prop projections.

Per-game averages (recency-weighted) for every skill player, plus projections
that nudge those averages by how the opposing defense fares vs the position —
the base layer for player props, the biggest market we didn't touch before.
Prop *lines* need a props feed (odds API player-props tier); the projections and
matchup context here are free.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_STATS = ["passing_yards", "passing_tds", "attempts", "carries", "rushing_yards",
          "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds"]
SKILL = ("QB", "RB", "WR", "TE", "FB")


def player_stats(weekly_weighted: pd.DataFrame) -> pd.DataFrame:
    """Per-player, per-game recency-weighted averages + position/team/games."""
    if weekly_weighted.empty or "player_id" not in weekly_weighted.columns:
        return pd.DataFrame()
    df = weekly_weighted.copy()
    stats = [s for s in _STATS if s in df.columns]
    for s in stats:
        df[s] = df[s].fillna(0.0)
    rows = []
    for pid, g in df.groupby("player_id"):
        wsum = g["w"].sum()
        if not wsum:
            continue
        rec = {"player_id": pid,
               "name": g["player_display_name"].iloc[-1] if "player_display_name" in g else pid,
               "pos": g["position"].iloc[-1] if "position" in g else "",
               "team": g["recent_team"].iloc[-1] if "recent_team" in g else "",
               "games": float(wsum)}
        for s in stats:
            rec[s] = float((g["w"] * g[s]).sum() / wsum)   # per-game average
        rows.append(rec)
    m = pd.DataFrame(rows).set_index("player_id")
    return m[m["pos"].isin(SKILL)] if "pos" in m.columns else m


def _factor(rank, spread: float = 0.14) -> float:
    """Rank 1 (tough D) -> below 1; rank 32 (soft) -> above 1."""
    if rank is None or pd.isna(rank):
        return 1.0
    return 1.0 + (int(rank) - 16.5) / 16.5 * spread


def project(player: pd.Series, opp: str, deff: pd.DataFrame, dvp: dict) -> dict:
    """Matchup-adjusted projection for a player vs opponent ``opp``."""
    pos = player.get("pos", "")
    out = {}
    # passing (QB) vs opp pass defense
    if pos == "QB":
        f = _factor(deff.loc[opp, "pass_epa_rank"]) if opp in deff.index else 1.0
        out["Pass yds"] = player.get("passing_yards", 0) * f
        out["Pass TD"] = player.get("passing_tds", 0) * f
        rf = _factor(deff.loc[opp, "rush_epa_rank"]) if opp in deff.index else 1.0
        if player.get("rushing_yards", 0) >= 10:
            out["Rush yds"] = player.get("rushing_yards", 0) * rf
    # rushing (RB) vs opp run defense
    if pos in ("RB", "FB"):
        rf = _factor(deff.loc[opp, "rush_epa_rank"]) if opp in deff.index else 1.0
        out["Rush yds"] = player.get("rushing_yards", 0) * rf
        out["Carries"] = player.get("carries", 0)
    # receiving (RB/WR/TE) vs opp coverage of that position
    if pos in ("RB", "WR", "TE"):
        dfp = dvp.get(pos)
        cf = _factor(dfp.loc[opp, "def_rank"]) if dfp is not None and opp in dfp.index else 1.0
        if player.get("targets", 0) >= 1.5:
            out["Rec yds"] = player.get("receiving_yards", 0) * cf
            out["Rec"] = player.get("receptions", 0) * cf
            out["Targets"] = player.get("targets", 0)
    return {k: v for k, v in out.items() if v and not pd.isna(v)}


def team_players(stats: pd.DataFrame, team: str, min_games: float = 1.0) -> pd.DataFrame:
    """A team's skill players, ranked by involvement."""
    if stats.empty:
        return stats
    t = stats[(stats["team"] == team) & (stats["games"] >= min_games)].copy()
    t["_use"] = t["targets"].fillna(0) + t["carries"].fillna(0) + t["attempts"].fillna(0) * 0.5
    return t.sort_values("_use", ascending=False)
