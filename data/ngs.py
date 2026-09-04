"""Next Gen Stats team summaries — the tracking layer.

NGS is charted from player tracking chips: how fast a QB gets rid of it, how open
receivers actually get, yards after the catch over expectation. It's the "why"
behind the EPA. These frames are season-cumulative per player, so we roll them up
to one row per team (the primary passer for passing; target-weighted for
receiving) with league ranks, and fall back to the prior season in the offseason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _season_slice(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "season" not in df.columns:
        return pd.DataFrame()
    season = (config.CURRENT_SEASON if (df["season"] == config.CURRENT_SEASON).any()
              else config.PRIOR_SEASON)
    return df[df["season"] == season].copy()


def team_passing(ngs_pass: pd.DataFrame) -> pd.DataFrame:
    """One row per team from its primary passer (most attempts). Adds ranks.

    Lower time-to-throw isn't strictly "better", so it's left unranked-for-good;
    CPOE and aggressiveness rank high-good.
    """
    df = _season_slice(ngs_pass)
    if df.empty or "team_abbr" not in df.columns:
        return pd.DataFrame()
    df = df.sort_values("attempts", ascending=False)
    starter = df.groupby("team_abbr").first()
    out = starter.rename_axis("team")
    if "completion_percentage_above_expectation" in out.columns:
        out["cpoe_rank"] = out["completion_percentage_above_expectation"].rank(
            ascending=False, method="min").astype("Int64")
    if "aggressiveness" in out.columns:
        out["aggr_rank"] = out["aggressiveness"].rank(ascending=False, method="min").astype("Int64")
    if "avg_time_to_throw" in out.columns:
        out["ttt_rank"] = out["avg_time_to_throw"].rank(ascending=True, method="min").astype("Int64")
    return out


def player_receiving(ngs_rec: pd.DataFrame) -> pd.DataFrame:
    """Per-player receiving tracking, keyed by gsis id: separation & YAC-over-expected.

    These are the playmaking signals a raw target count misses — a receiver who
    gets open and creates after the catch beats his yardage baseline more often.
    """
    df = _season_slice(ngs_rec)
    if df.empty or "player_gsis_id" not in df.columns:
        return pd.DataFrame()
    keep = {"avg_separation": "sep", "avg_cushion": "cushion",
            "avg_yac_above_expectation": "yac_oe"}
    cols = {v: df[k] for k, v in keep.items() if k in df.columns}
    if not cols:
        return pd.DataFrame()
    out = pd.DataFrame(cols)
    out["player_id"] = df["player_gsis_id"].astype(str).values
    return out.dropna(subset=["player_id"]).groupby("player_id").last()


def player_passing(ngs_pass: pd.DataFrame) -> pd.DataFrame:
    """Per-player passing tracking, keyed by gsis id: CPOE & time-to-throw."""
    df = _season_slice(ngs_pass)
    if df.empty or "player_gsis_id" not in df.columns:
        return pd.DataFrame()
    keep = {"completion_percentage_above_expectation": "cpoe",
            "avg_time_to_throw": "ttt", "aggressiveness": "aggr"}
    cols = {v: df[k] for k, v in keep.items() if k in df.columns}
    if not cols:
        return pd.DataFrame()
    out = pd.DataFrame(cols)
    out["player_id"] = df["player_gsis_id"].astype(str).values
    return out.dropna(subset=["player_id"]).groupby("player_id").last()


def team_receiving(ngs_rec: pd.DataFrame) -> pd.DataFrame:
    """Target-weighted team receiving tracking + the team's most-open target."""
    df = _season_slice(ngs_rec)
    if df.empty or "team_abbr" not in df.columns:
        return pd.DataFrame()
    rows = []
    for team, g in df.groupby("team_abbr"):
        w = g["targets"].fillna(0)
        wsum = w.sum()
        def wavg(col):
            if col not in g.columns or wsum == 0:
                return np.nan
            return float((g[col].fillna(0) * w).sum() / wsum)
        # the team's featured separation guy (most targets)
        top = g.sort_values("targets", ascending=False).iloc[0] if len(g) else None
        rows.append({
            "team": team,
            "avg_separation": wavg("avg_separation"),
            "avg_cushion": wavg("avg_cushion"),
            "avg_yac_above_expectation": wavg("avg_yac_above_expectation"),
            "top_target": top.get("player_display_name") if top is not None else None,
            "top_separation": top.get("avg_separation") if top is not None else np.nan,
        })
    out = pd.DataFrame(rows).set_index("team")
    if "avg_separation" in out.columns:
        out["sep_rank"] = out["avg_separation"].rank(ascending=False, method="min").astype("Int64")
    if "avg_yac_above_expectation" in out.columns:
        out["yac_rank"] = out["avg_yac_above_expectation"].rank(ascending=False, method="min").astype("Int64")
    return out
