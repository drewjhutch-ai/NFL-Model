"""Situational efficiency: third down and red zone, offense and defense.

The moments that decide games and props. Third-down conversion keeps drives
alive; red-zone finishing turns yards into points. Both are recency-weighted and
ranked league-wide so they slot straight into the matchup edges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wmean(g: pd.DataFrame, value: str) -> float:
    v, w = g[value], g["w"]
    mask = v.notna() & w.notna()
    denom = w[mask].sum()
    return float((v[mask] * w[mask]).sum() / denom) if denom else np.nan


def _situational(pbp_weighted: pd.DataFrame, team_col: str, best_high: bool) -> pd.DataFrame:
    if pbp_weighted.empty or team_col not in pbp_weighted.columns:
        return pd.DataFrame()
    df = pbp_weighted[pbp_weighted[team_col].notna()].copy()
    third = df[df.get("down") == 3]
    rz = df[df.get("yardline_100", 100) <= 20]

    rows = []
    for team in sorted(df[team_col].unique()):
        gt = third[third[team_col] == team]
        gz = rz[rz[team_col] == team]
        rows.append({
            "team": team,
            "third_conv": _wmean(gt.assign(_c=gt.get("first_down", 0).fillna(0).astype(float)), "_c")
            if not gt.empty else np.nan,
            "third_epa": _wmean(gt, "epa") if not gt.empty else np.nan,
            "rz_td_rate": _wmean(gz.assign(_t=gz.get("touchdown", 0).fillna(0).astype(float)), "_t")
            if not gz.empty else np.nan,
            "rz_epa": _wmean(gz, "epa") if not gz.empty else np.nan,
        })
    m = pd.DataFrame(rows).set_index("team")
    if m.empty:
        return m
    asc = not best_high
    m["third_rank"] = m["third_epa"].rank(ascending=asc, method="min").astype("Int64")
    m["rz_rank"] = m["rz_td_rate"].rank(ascending=asc, method="min").astype("Int64")
    return m


def offense_situational(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Offense third-down & red-zone efficiency (rank 1 = best)."""
    return _situational(pbp_weighted, "posteam", best_high=True)


def defense_situational(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Defense third-down & red-zone efficiency allowed (rank 1 = stingiest)."""
    return _situational(pbp_weighted, "defteam", best_high=False)
