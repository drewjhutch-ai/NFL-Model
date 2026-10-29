"""Receiver usage profiles from air yards — the real matchup substance.

The old receiving matchup read was team target-share-to-a-position vs a defense's
position rank: nearly uniform across teams, so it graded out as noise (WR facet hit
47%). What actually separates receivers is *how* they're used, and air yards is the
most predictive free signal there is:

  * **target share**  — share of the team's targets (volume)
  * **air-yards share** — share of the team's air yards (volume × depth; the single
    best market-share stat for receiving production — "alpha" usage)
  * **aDOT**          — average depth of target (deep threat vs possession)
  * **deep rate**     — share of targets 20+ yards downfield
  * **YAC/ catch rate** — efficiency after the catch

Built from play-by-play we already load (air_yards + receiver_player_id). Keyed by
player_id; callers map to names/alignment. Pairing air-yards share with the
defense's alignment-specific coverage rank (outside vs slot) is a far sharper read
than team-share-vs-position.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_DEEP_AY = 20          # a "deep" target is 20+ air yards
_MIN_TARGETS = 8       # ignore noise from tiny samples when ranking roles


def receiver_profiles(pbp: pd.DataFrame, season: int | None = None) -> pd.DataFrame:
    """Per-receiver usage profile. Indexed by receiver_player_id.

    Columns: team, targets, catches, rec_yards, air_yards, aDOT, tgt_share,
    ay_share, deep_rate, catch_rate, ypt, role. Empty frame if pbp lacks air yards.
    """
    if pbp is None or getattr(pbp, "empty", True):
        return pd.DataFrame()
    need = {"receiver_player_id", "air_yards", "posteam"}
    if not need.issubset(pbp.columns):
        return pd.DataFrame()
    df = pbp
    if season is not None and "season" in df.columns:
        df = df[df["season"] == season]
    df = df[df["receiver_player_id"].notna() & (df.get("pass", 1) == 1)]
    if df.empty:
        return pd.DataFrame()
    ay = pd.to_numeric(df["air_yards"], errors="coerce")
    comp = pd.to_numeric(df.get("complete_pass", 0), errors="coerce").fillna(0)
    yds = pd.to_numeric(df.get("yards_gained", 0), errors="coerce").fillna(0)
    g = pd.DataFrame({
        "pid": df["receiver_player_id"].values, "team": df["posteam"].values,
        "ay": ay.values, "deep": (ay >= _DEEP_AY).astype(float).values,
        "comp": comp.values, "yds": (yds * comp).values,   # receiving yards (completed only)
    })
    agg = g.groupby(["pid", "team"]).agg(
        targets=("ay", "size"), air_yards=("ay", "sum"), aDOT=("ay", "mean"),
        catches=("comp", "sum"), rec_yards=("yds", "sum"), deep=("deep", "sum"),
    ).reset_index()
    # team totals for market-share stats
    team_tgt = agg.groupby("team")["targets"].transform("sum")
    team_ay = agg.groupby("team")["air_yards"].transform("sum")
    agg["tgt_share"] = agg["targets"] / team_tgt.replace(0, np.nan)
    agg["ay_share"] = agg["air_yards"] / team_ay.replace(0, np.nan)
    agg["deep_rate"] = agg["deep"] / agg["targets"].replace(0, np.nan)
    agg["catch_rate"] = agg["catches"] / agg["targets"].replace(0, np.nan)
    agg["ypt"] = agg["rec_yards"] / agg["targets"].replace(0, np.nan)
    agg["aDOT"] = agg["aDOT"].round(1)

    def role(r):
        if r["targets"] < _MIN_TARGETS:
            return "rotational"
        if r["aDOT"] >= 12:
            return "deep threat"
        if r["aDOT"] <= 7:
            return "possession"
        return "balanced"
    agg["role"] = agg.apply(role, axis=1)
    return agg.set_index("pid")


def align_coverage_rank(cov: pd.DataFrame, defense: str, alignment: str):
    """Defense's charted coverage rank vs a receiver's alignment (outside/slot).

    Uses Sharp's YPT-allowed Outside/Slot splits (1 = stingiest, 32 = softest) — a
    far sharper read than a single vs-WR rank. Returns None when unavailable.
    """
    if cov is None or getattr(cov, "empty", True) or defense not in cov.index:
        return None
    col = "ypt_Slot_rank" if str(alignment).lower() == "slot" else "ypt_Outside_rank"
    if col in cov.columns and pd.notna(cov.loc[defense].get(col)):
        return int(cov.loc[defense, col])
    return None
