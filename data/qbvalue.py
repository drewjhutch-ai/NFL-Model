"""Quarterback value — and the projection swing when a starter is Out.

QB is the biggest single factor in a game, and the biggest week-to-week line
mover. This identifies each team's primary passer, rates their dropback
efficiency, and expresses the drop-off to a replacement-level QB in *points* —
so when the starter is ruled Out, the betting projection actually moves instead
of just showing a warning.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def qb_values(pbp_weighted: pd.DataFrame, out_gsis_by_team: dict[str, set] | None = None,
              name_map: dict | None = None) -> pd.DataFrame:
    """Per-team starter QB: efficiency, points-over-replacement, and Out status."""
    if pbp_weighted.empty or "passer_player_id" not in pbp_weighted.columns:
        return pd.DataFrame()
    db = pbp_weighted[((pbp_weighted["pass"] == 1) | (pbp_weighted.get("sack", 0) == 1))
                      & pbp_weighted["passer_player_id"].notna()].copy()
    if db.empty:
        return pd.DataFrame()

    db["_we"] = db["w"] * db["epa"]
    grp = (db.groupby(["posteam", "passer_player_id"])
           .agg(db=("w", "sum"), we=("_we", "sum")).reset_index())
    grp["epa"] = grp["we"] / grp["db"]

    out_gsis_by_team = out_gsis_by_team or {}
    name_map = name_map or {}
    rows = []
    for team, g in grp.groupby("posteam"):
        starter = g.sort_values("db", ascending=False).iloc[0]
        gsis = starter["passer_player_id"]
        repl = config.QB_REPLACEMENT_EPA
        pts = (starter["epa"] - repl) * config.QB_DROPBACKS_PER_GAME * config.QB_ADJUST_SCALE
        pts = float(np.clip(pts, 0, config.QB_ADJUST_CAP))
        rows.append({
            "team": team, "starter_gsis": gsis,
            "starter": name_map.get(gsis, gsis),
            "starter_epa": float(starter["epa"]),
            "qb_points": pts,
            "starter_out": gsis in out_gsis_by_team.get(team, set()),
        })
    return pd.DataFrame(rows).set_index("team")


def qb_adjustment(qb: pd.DataFrame, team: str) -> float:
    """Points to subtract from a team's projection if its starter is Out."""
    if qb is None or qb.empty or team not in qb.index:
        return 0.0
    r = qb.loc[team]
    return float(r["qb_points"]) if r.get("starter_out") else 0.0
