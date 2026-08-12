"""Drive-level efficiency — points per drive, scoring rate, TD rate.

Sharps lean on per-drive output because it ties efficiency straight to scoring.
Computed from drive results (recency-weighted) for offense and defense.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_POINTS = {"Touchdown": 7.0, "Field goal": 3.0}
_SCORE = {"Touchdown", "Field goal"}


def _agg(dr: pd.DataFrame, col: str, best_high: bool) -> pd.DataFrame:
    rows = []
    for team, g in dr.groupby(col):
        wsum = g["w"].sum()
        if not wsum:
            continue
        rows.append({
            "team": team,
            "pts_per_drive": float((g["w"] * g["pts"]).sum() / wsum),
            "score_rate": float((g["w"] * g["score"]).sum() / wsum),
            "td_rate": float((g["w"] * g["td"]).sum() / wsum),
        })
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        asc = not best_high
        m["ppd_rank"] = m["pts_per_drive"].rank(ascending=asc, method="min").astype("Int64")
    return m


def drive_efficiency(pbp_weighted: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(offense, defense) drive efficiency. Offense rank 1 = most points/drive."""
    if pbp_weighted.empty or "fixed_drive" not in pbp_weighted.columns:
        return pd.DataFrame(), pd.DataFrame()
    d = pbp_weighted[pbp_weighted["fixed_drive"].notna()
                     & pbp_weighted["posteam"].notna() & pbp_weighted["defteam"].notna()]
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    dr = d.drop_duplicates(["game_id", "fixed_drive"]).copy()
    dr["pts"] = dr["fixed_drive_result"].map(_POINTS).fillna(0.0)
    dr["score"] = dr["fixed_drive_result"].isin(_SCORE).astype(float)
    dr["td"] = (dr["fixed_drive_result"] == "Touchdown").astype(float)
    return _agg(dr, "posteam", True), _agg(dr, "defteam", False)
