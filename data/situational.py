"""Situational efficiency: third down and red zone, offense and defense.

The moments that decide games and props. Third-down conversion keeps drives
alive; red-zone finishing turns yards into points. Both are recency-weighted and
ranked league-wide so they slot straight into the matchup edges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data.statutil import shrink


def _wmean(g: pd.DataFrame, value: str) -> float:
    v, w = g[value], g["w"]
    mask = v.notna() & w.notna()
    denom = w[mask].sum()
    return float((v[mask] * w[mask]).sum() / denom) if denom else np.nan


def _situational(pbp_weighted: pd.DataFrame, team_col: str, best_high: bool) -> pd.DataFrame:
    if pbp_weighted.empty or team_col not in pbp_weighted.columns:
        return pd.DataFrame()
    df = pbp_weighted[pbp_weighted[team_col].notna()].copy()
    empty = df.iloc[0:0]
    third = df[df["down"] == 3] if "down" in df.columns else empty
    rz = df[df["yardline_100"] <= 20] if "yardline_100" in df.columns else empty

    def _flag(g, col):
        s = g[col].fillna(0).astype(float) if col in g.columns else pd.Series(0.0, index=g.index)
        return g.assign(_x=s)

    rows = []
    for team in sorted(df[team_col].unique()):
        gt = third[third[team_col] == team]
        gz = rz[rz[team_col] == team]
        rows.append({
            "team": team,
            "third_conv": _wmean(_flag(gt, "first_down"), "_x") if not gt.empty else np.nan,
            "third_epa": _wmean(gt, "epa") if not gt.empty else np.nan,
            "third_n": float(gt["w"].sum()),
            "rz_td_rate": _wmean(_flag(gz, "touchdown"), "_x") if not gz.empty else np.nan,
            "rz_epa": _wmean(gz, "epa") if not gz.empty else np.nan,
            "rz_n": float(gz["w"].sum()),
        })
    m = pd.DataFrame(rows).set_index("team")
    if m.empty:
        return m
    # Shrink these regression-prone rates toward league mean by sample size.
    lg_third = m["third_conv"].mean()
    lg_rz = m["rz_td_rate"].mean()
    m["third_conv"] = shrink(m["third_conv"], m["third_n"], lg_third, config.SHRINK_SITUATIONAL)
    m["rz_td_rate"] = shrink(m["rz_td_rate"], m["rz_n"], lg_rz, config.SHRINK_SITUATIONAL)
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
