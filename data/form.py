"""Rolling form — how a team is trending lately vs its season baseline.

Recent EPA/play (last few games) against the full-season number, for offense and
defense, so hot and cold streaks show up rather than being washed out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def team_form(pbp: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    """Per team: recent vs season EPA/play (offense & defense) + deltas."""
    if pbp.empty or "season" not in pbp.columns:
        return pd.DataFrame()
    season = config.CURRENT_SEASON if (pbp["season"] == config.CURRENT_SEASON).any() \
        else config.PRIOR_SEASON
    fs = pbp[pbp["season"] == season]
    if fs.empty:
        return pd.DataFrame()
    weeks = sorted(int(w) for w in fs["week"].dropna().unique())
    recent_weeks = set(weeks[-window:])
    rec = fs[fs["week"].isin(recent_weeks)]

    def side(df, col):
        return df.groupby(col)["epa"].mean()

    o_season, o_recent = side(fs, "posteam"), side(rec, "posteam")
    d_season, d_recent = side(fs, "defteam"), side(rec, "defteam")
    teams = sorted(set(o_season.index) | set(d_season.index))
    m = pd.DataFrame(index=teams)
    m["off_season"] = o_season.reindex(teams)
    m["off_recent"] = o_recent.reindex(teams)
    m["off_delta"] = m["off_recent"] - m["off_season"]
    m["def_season"] = d_season.reindex(teams)
    m["def_recent"] = d_recent.reindex(teams)
    m["def_delta"] = m["def_recent"] - m["def_season"]  # negative = improving D
    m["games_in_window"] = len(recent_weeks)
    return m


def arrow(delta: float, good_high: bool = True) -> str:
    if delta is None or pd.isna(delta):
        return "→"
    up = delta > 0.03
    down = delta < -0.03
    if not good_high:
        up, down = down, up
    return "📈" if up else ("📉" if down else "→")
