"""Expected production (ffverse ff_opportunity) — an independent regression anchor.

Given a player's *opportunity* (targets, air yards, carries, where on the field),
ff_opportunity models what his production *should* be. Comparing our projection —
and the market line — to this independent expectation flags overheated numbers
(sell) and buy-lows (the model likes a guy the box score hasn't rewarded yet).
Per-game expectations, keyed by gsis id, from the current season (prior in the
offseason).
"""
from __future__ import annotations

import pandas as pd

import config


def _season_slice(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "season" not in df.columns:
        return pd.DataFrame()
    season = (config.CURRENT_SEASON if (df["season"] == config.CURRENT_SEASON).any()
              else config.PRIOR_SEASON)
    return df[df["season"] == season].copy()


def _find(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def player_expected(ff_opp: pd.DataFrame) -> pd.DataFrame:
    """player_id -> per-game expected rec yds / rush yds / receptions / TDs."""
    df = _season_slice(ff_opp)
    if df.empty:
        return pd.DataFrame()
    idc = _find(df, "player_id", "gsis_id")
    if idc is None:
        return pd.DataFrame()
    recy = _find(df, "rec_yards_gained_exp", "receiving_yards_exp")
    rushy = _find(df, "rush_yards_gained_exp", "rushing_yards_exp")
    rec = _find(df, "receptions_exp")
    rtd = _find(df, "rec_touchdown_exp")
    rutd = _find(df, "rush_touchdown_exp")
    keep = {c: n for c, n in (("exp_rec_yds", recy), ("exp_rush_yds", rushy),
                              ("exp_rec", rec)) if n}
    if not keep and not (rtd or rutd):
        return pd.DataFrame()
    g = df.groupby(idc)
    out = pd.DataFrame(index=g.size().index)
    for out_col, src in keep.items():
        out[out_col] = g[src].mean()
    td_cols = [c for c in (rtd, rutd) if c]
    if td_cols:
        out["exp_td"] = sum(g[c].mean() for c in td_cols)
    out.index = out.index.astype(str)
    out.index.name = "player_id"
    return out
