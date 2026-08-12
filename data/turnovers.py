"""Turnover margin — the 6th core handicapping category — with luck regression.

Turnovers swing games but are noisy and regress hard (fumble recoveries are ~50%
luck). We report actual giveaways/takeaways per game and a regressed margin so a
team riding turnover luck doesn't look better than it is.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Turnovers are ~40% skill, 60% luck year to year — regress most of the way.
_TO_SKILL = 0.4


def turnover_margin(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Per team: giveaways, takeaways, margin/game, and a regressed margin."""
    if pbp_weighted.empty:
        return pd.DataFrame()
    df = pbp_weighted.copy()
    df["_to"] = ((df.get("interception", 0) == 1) | (df.get("fumble_lost", 0) == 1)).astype(float)

    give, take = {}, {}
    for team, g in df[df["posteam"].notna()].groupby("posteam"):
        games = g["game_id"].nunique()
        give[team] = float((g["w"] * g["_to"]).sum() / games) if games else np.nan
    for team, g in df[df["defteam"].notna()].groupby("defteam"):
        games = g["game_id"].nunique()
        take[team] = float((g["w"] * g["_to"]).sum() / games) if games else np.nan

    teams = sorted(set(give) | set(take))
    m = pd.DataFrame({"giveaways": pd.Series(give), "takeaways": pd.Series(take)},
                     index=teams)
    m["margin"] = m["takeaways"] - m["giveaways"]
    # regress toward the league mean (turnovers are largely luck)
    lg = m["margin"].mean()
    m["reg_margin"] = _TO_SKILL * m["margin"] + (1 - _TO_SKILL) * lg
    m["margin_rank"] = m["margin"].rank(ascending=False, method="min").astype("Int64")
    return m
