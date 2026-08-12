"""Coaching / scheme tendencies — how a staff chooses to play.

Play-action, no-huddle, and motion rates (from FTN charting) plus pass-rate over
expected and pace tell you a team's identity and how it might attack a matchup.
Recency-weighted like everything else.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import labels


def _wrate(g: pd.DataFrame, col: str) -> float:
    if col not in g.columns:
        return np.nan
    v = g[col].fillna(0).astype(float)
    w = g["w"]
    return float((v * w).sum() / w.sum()) if w.sum() else np.nan


def coaching_tendencies(pbp_weighted: pd.DataFrame, ftn: pd.DataFrame) -> pd.DataFrame:
    """Per-offense play-action / no-huddle / motion rates from FTN charting."""
    if ftn.empty or pbp_weighted.empty or "nflverse_play_id" not in ftn.columns:
        return pd.DataFrame()
    f = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
    keep = [c for c in ["game_id", "play_id", "is_play_action", "is_no_huddle", "is_motion"]
            if c in f.columns]
    cols = [c for c in ["game_id", "play_id", "posteam", "qb_dropback", "w"]
            if c in pbp_weighted.columns]
    m = pbp_weighted[cols].merge(f[keep], on=["game_id", "play_id"], how="inner")
    if m.empty:
        return pd.DataFrame()
    rows = []
    for team, g in m.groupby("posteam"):
        db = g[g.get("qb_dropback", 1) == 1] if "qb_dropback" in g.columns else g
        rows.append({
            "team": team,
            "play_action_rate": _wrate(db, "is_play_action"),
            "no_huddle_rate": _wrate(g, "is_no_huddle"),
            "motion_rate": _wrate(g, "is_motion"),
        })
    out = pd.DataFrame(rows).set_index("team")
    if not out.empty and "play_action_rate" in out.columns:
        out["pa_label"] = labels.band_series(
            out["play_action_rate"],
            [(0.30, "Low play-action"), (0.65, "Average PA"), (1.01, "Play-action heavy")])
    return out
