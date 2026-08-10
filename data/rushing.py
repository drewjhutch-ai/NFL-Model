"""Team rushing playstyle from Next Gen Stats tracking data.

Goes beyond "rush EPA": how much better than a blank-slate runner is this team's
ground game (rush yards over expected), how efficient (yards vs. straight-line),
and how stacked are the boxes they face. Matched against the defense's run
front, this is the RB-vs-defense playstyle read.

Season totals are recency-weighted like everything else: current season leads,
prior season is a whisper.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data.teams import normalize_team


def _season_weight(season: int) -> float:
    if season == config.CURRENT_SEASON:
        return 1.0
    if season == config.PRIOR_SEASON:
        return config.PRIOR_SEASON_WEIGHT
    return 0.0


def team_rushing_profile(ngs_rushing: pd.DataFrame) -> pd.DataFrame:
    """Attempts-weighted team rushing profile with ranks (rank 1 = best RYOE)."""
    if ngs_rushing.empty or "team_abbr" not in ngs_rushing.columns:
        return pd.DataFrame()
    df = ngs_rushing.copy()
    df["team"] = df["team_abbr"].map(normalize_team)
    df = df[df["team"].notna()]
    # weight each player-season by attempts * season recency
    df["_w"] = df["rush_attempts"].fillna(0) * df["season"].map(_season_weight)
    df = df[df["_w"] > 0]
    if df.empty:
        return pd.DataFrame()

    def wavg(g, col):
        v = g[col]
        m = v.notna()
        denom = g["_w"][m].sum()
        return float((v[m] * g["_w"][m]).sum() / denom) if denom else np.nan

    rows = []
    for team, g in df.groupby("team"):
        rows.append({
            "team": team,
            "ryoe_per_att": wavg(g, "rush_yards_over_expected_per_att")
            if "rush_yards_over_expected_per_att" in g else np.nan,
            "efficiency": wavg(g, "efficiency") if "efficiency" in g else np.nan,
            "stacked_box_pct": wavg(g, "percent_attempts_gte_eight_defenders")
            if "percent_attempts_gte_eight_defenders" in g else np.nan,
            "attempts": float(g["rush_attempts"].fillna(0).sum()),
        })
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty and "ryoe_per_att" in m.columns:
        m["ryoe_rank"] = m["ryoe_per_att"].rank(ascending=False, method="min").astype("Int64")
    return m


def rushing_label(ryoe_rank) -> str:
    if ryoe_rank is None or pd.isna(ryoe_rank):
        return "—"
    r = int(ryoe_rank)
    if r <= 8:
        return "Efficient ground game"
    if r <= 20:
        return "Average rushing"
    return "Struggles on the ground"
