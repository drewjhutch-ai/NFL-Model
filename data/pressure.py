"""QB mobility (offense) and pass-rush pressure (defense).

Two edges that decide games and props:
* Is the QB a runner? Scramble + designed-run rate and the EPA it generates.
* Can the defense get home? Sack and pressure (sack-or-hit) rate per dropback.

A mobile QB against a slow rush, or a statue QB against a heavy rush, is exactly
the kind of edge this surfaces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import labels


def _wmean(g: pd.DataFrame, value: str) -> float:
    v, w = g[value], g["w"]
    mask = v.notna() & w.notna()
    denom = w[mask].sum()
    return float((v[mask] * w[mask]).sum() / denom) if denom else np.nan


def qb_profiles(pbp_weighted: pd.DataFrame, posmap: dict[str, str]) -> pd.DataFrame:
    """Per-offense QB mobility profile with ranks (rank 1 = most mobile)."""
    if pbp_weighted.empty:
        return pd.DataFrame()
    df = pbp_weighted.copy()
    rusher_pos = df.get("rusher_player_id", pd.Series(index=df.index)).map(posmap)
    is_scramble = df.get("qb_scramble", 0) == 1
    is_qb_run = (df["rush"] == 1) & (rusher_pos == "QB")
    df["_qbrun"] = (is_scramble | is_qb_run).astype(float)
    df["_drop"] = (df.get("qb_dropback", 0) == 1).astype(float)

    rows = []
    for team, g in df.groupby("posteam"):
        dropbacks = float((g["_drop"] * g["w"]).sum())
        qbruns = float((g["_qbrun"] * g["w"]).sum())
        runs = g[g["_qbrun"] == 1]
        rows.append({
            "team": team,
            "qb_rush_rate": (qbruns / dropbacks) if dropbacks else np.nan,
            "qb_rush_epa": _wmean(runs, "epa") if not runs.empty else np.nan,
            "qb_rushes": qbruns,
        })
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        m["qb_rush_rate_rank"] = m["qb_rush_rate"].rank(ascending=False, method="min").astype("Int64")
        m["qb_style"] = labels.band_series(m["qb_rush_rate"], labels.QB_BANDS)
    return m


def defense_pressure(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Per-defense pass-rush profile with ranks (rank 1 = most pressure)."""
    if pbp_weighted.empty or "qb_dropback" not in pbp_weighted.columns:
        return pd.DataFrame()
    db = pbp_weighted[pbp_weighted["qb_dropback"] == 1].copy()
    if db.empty:
        return pd.DataFrame()
    db["_sack"] = (db.get("sack", 0) == 1).astype(float)
    db["_pressure"] = ((db.get("sack", 0) == 1) | (db.get("qb_hit", 0) == 1)).astype(float)

    rows = []
    for team, g in db.groupby("defteam"):
        rows.append({
            "team": team,
            "sack_rate": _wmean(g, "_sack"),
            "pressure_rate": _wmean(g, "_pressure"),
            "dropbacks": float(g["w"].sum()),
        })
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        m["pressure_rate_rank"] = m["pressure_rate"].rank(ascending=False, method="min").astype("Int64")
        m["sack_rate_rank"] = m["sack_rate"].rank(ascending=False, method="min").astype("Int64")
    return m


def offense_protection(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Per-offense pass protection: sack/pressure rate allowed (rank 1 = best)."""
    if pbp_weighted.empty or "qb_dropback" not in pbp_weighted.columns:
        return pd.DataFrame()
    db = pbp_weighted[pbp_weighted["qb_dropback"] == 1].copy()
    if db.empty:
        return pd.DataFrame()
    db["_sack"] = (db.get("sack", 0) == 1).astype(float)
    db["_pressure"] = ((db.get("sack", 0) == 1) | (db.get("qb_hit", 0) == 1)).astype(float)
    rows = []
    for team, g in db.groupby("posteam"):
        rows.append({"team": team, "sack_allowed_rate": _wmean(g, "_sack"),
                     "pressure_allowed_rate": _wmean(g, "_pressure")})
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        m["protection_rank"] = m["sack_allowed_rate"].rank(ascending=True, method="min").astype("Int64")
    return m


def offense_vs_blitz(pbp_weighted: pd.DataFrame, ftn: pd.DataFrame) -> pd.DataFrame:
    """How each offense performs when blitzed vs not (FTN charting, 2022+).

    ``epa_vs_blitz`` ranked (1 = best against the blitz); ``blitz_delta`` < 0
    means the offense is *worse* when blitzed — i.e. a blitz-vulnerable unit.
    """
    if ftn.empty or pbp_weighted.empty or "n_blitzers" not in ftn.columns:
        return pd.DataFrame()
    f = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
    cols = [c for c in ["game_id", "play_id", "posteam", "qb_dropback", "epa", "w"]
            if c in pbp_weighted.columns]
    merged = pbp_weighted[cols].merge(f[["game_id", "play_id", "n_blitzers"]],
                                      on=["game_id", "play_id"], how="inner")
    if "qb_dropback" in merged.columns:
        merged = merged[merged["qb_dropback"] == 1]
    merged = merged[merged["posteam"].notna() & merged["n_blitzers"].notna()]
    if merged.empty:
        return pd.DataFrame()
    merged["_blitz"] = (merged["n_blitzers"] >= 1)
    rows = []
    for team, g in merged.groupby("posteam"):
        blitzed = g[g["_blitz"]]
        clean = g[~g["_blitz"]]
        evb = _wmean(blitzed, "epa") if not blitzed.empty else np.nan
        enb = _wmean(clean, "epa") if not clean.empty else np.nan
        rows.append({"team": team, "epa_vs_blitz": evb, "epa_no_blitz": enb,
                     "blitz_delta": (evb - enb) if pd.notna(evb) and pd.notna(enb) else np.nan,
                     "blitz_faced_rate": _wmean(g.assign(_b=g["_blitz"].astype(float)), "_b")})
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        m["vs_blitz_rank"] = m["epa_vs_blitz"].rank(ascending=False, method="min").astype("Int64")
        m["resilience"] = labels.band_series(m["blitz_delta"], labels.RESILIENCE_BANDS)
    return m


def blitz_resilience_label(delta) -> str:
    """Does the offense hold up against the blitz?"""
    if delta is None or pd.isna(delta):
        return "—"
    if delta >= 0.05:
        return "Thrives vs blitz"
    if delta >= -0.05:
        return "Handles blitz fine"
    if delta >= -0.15:
        return "Dips vs blitz"
    return "Struggles vs blitz"


def qb_label(rush_rate: float) -> str:
    if rush_rate is None or np.isnan(rush_rate):
        return "—"
    if rush_rate >= 0.11:
        return "Mobile / dual-threat"
    if rush_rate >= 0.06:
        return "Some mobility"
    return "Pocket passer"


def pressure_label(rank) -> str:
    if rank is None or pd.isna(rank):
        return "—"
    r = int(rank)
    if r <= 8:
        return "Heavy pass rush"
    if r <= 20:
        return "Average rush"
    return "Weak pass rush"
