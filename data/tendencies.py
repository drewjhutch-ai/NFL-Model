"""Turn weighted play-by-play into team tendencies and 1-32 rankings.

The output of this module is what the dashboard renders: for every team, an
offensive profile and a defensive profile, each with raw metrics *and* league
ranks. All aggregation respects the per-play recency weight ``w`` so the current
season drives everything and the prior season is only a whisper.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


# --- weighted helpers --------------------------------------------------------
def _wmean(g: pd.DataFrame, value: str, weight: str = "w") -> float:
    """Weighted mean of ``value`` within group ``g`` (NaN-safe)."""
    v = g[value]
    w = g[weight]
    mask = v.notna() & w.notna()
    denom = w[mask].sum()
    if denom == 0:
        return np.nan
    return float((v[mask] * w[mask]).sum() / denom)


def _neutral(pbp: pd.DataFrame) -> pd.DataFrame:
    """Plays run in a neutral game script (see config)."""
    cols_ok = {"down", "wp", "half_seconds_remaining"}.issubset(pbp.columns)
    if not cols_ok:
        return pbp
    return pbp[
        pbp["down"].isin(config.NEUTRAL_DOWNS)
        & pbp["wp"].between(config.NEUTRAL_WP_MIN, config.NEUTRAL_WP_MAX)
        & (pbp["half_seconds_remaining"] > config.NEUTRAL_MIN_HALF_SECONDS)
    ]


def _explosive(pbp: pd.DataFrame) -> pd.Series:
    """Boolean series: was each play an explosive gain?"""
    yards = pbp["yards_gained"]
    is_pass = pbp["pass"] == 1
    return (is_pass & (yards >= config.EXPLOSIVE_PASS_YARDS)) | (
        (~is_pass) & (yards >= config.EXPLOSIVE_RUSH_YARDS)
    )


def _rank(series: pd.Series, best_high: bool) -> pd.Series:
    """1-32 ranking. Rank 1 = best. ``best_high`` flips the direction."""
    return series.rank(ascending=not best_high, method="min").astype("Int64")


# --- core aggregation --------------------------------------------------------
def _team_metrics(pbp: pd.DataFrame, team_col: str) -> pd.DataFrame:
    """Per-team weighted metrics grouped by ``team_col`` (posteam or defteam)."""
    pbp = pbp[pbp[team_col].notna()].copy()
    pbp["is_explosive"] = _explosive(pbp)
    neutral = _neutral(pbp)

    rows = []
    for team, g in pbp.groupby(team_col):
        gp = g[g["pass"] == 1]
        gr = g[g["rush"] == 1]
        gn = neutral[neutral[team_col] == team]

        rows.append(
            {
                "team": team,
                "plays": float(g["w"].sum()),
                "epa_play": _wmean(g, "epa"),
                "pass_epa": _wmean(gp, "epa"),
                "rush_epa": _wmean(gr, "epa"),
                "pass_sr": _wmean(gp, "success"),
                "rush_sr": _wmean(gr, "success"),
                "explosive_rate": _wmean(g.assign(_e=g["is_explosive"].astype(float)), "_e"),
                "pass_rate": _wmean(g.assign(_p=(g["pass"] == 1).astype(float)), "_p"),
                "neutral_pass_rate": _wmean(gn.assign(_p=(gn["pass"] == 1).astype(float)), "_p")
                if not gn.empty else np.nan,
                "proe": _wmean(g, "pass_oe") if "pass_oe" in g.columns else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("team")


def compute_offense(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Offensive profile per team, with ranks (rank 1 = best offense)."""
    m = _team_metrics(pbp_weighted, "posteam")
    if m.empty:
        return m
    m["epa_play_rank"] = _rank(m["epa_play"], best_high=True)
    m["pass_epa_rank"] = _rank(m["pass_epa"], best_high=True)
    m["rush_epa_rank"] = _rank(m["rush_epa"], best_high=True)
    m["pass_sr_rank"] = _rank(m["pass_sr"], best_high=True)
    m["rush_sr_rank"] = _rank(m["rush_sr"], best_high=True)
    m["explosive_rate_rank"] = _rank(m["explosive_rate"], best_high=True)
    return m.sort_values("epa_play", ascending=False)


def compute_defense(pbp_weighted: pd.DataFrame) -> pd.DataFrame:
    """Defensive profile per team, with ranks (rank 1 = best defense).

    Defense is scored on what it *allows*, so lower EPA/success allowed is better.
    """
    m = _team_metrics(pbp_weighted, "defteam")
    if m.empty:
        return m
    m["epa_play_rank"] = _rank(m["epa_play"], best_high=False)
    m["pass_epa_rank"] = _rank(m["pass_epa"], best_high=False)
    m["rush_epa_rank"] = _rank(m["rush_epa"], best_high=False)
    m["pass_sr_rank"] = _rank(m["pass_sr"], best_high=False)
    m["rush_sr_rank"] = _rank(m["rush_sr"], best_high=False)
    m["explosive_rate_rank"] = _rank(m["explosive_rate"], best_high=False)
    return m.sort_values("epa_play", ascending=True)


def compute_blitz(pbp_weighted: pd.DataFrame, ftn: pd.DataFrame) -> pd.DataFrame:
    """Defensive blitz rate & average box count from FTN charting.

    Returns an empty frame if FTN data isn't available for the weighted seasons.
    """
    if ftn.empty or pbp_weighted.empty:
        return pd.DataFrame()

    # FTN keys map onto pbp game_id / play_id.
    ftn = ftn.rename(
        columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"}
    )
    cols = ["game_id", "play_id", "defteam", "qb_dropback", "w"]
    cols = [c for c in cols if c in pbp_weighted.columns]
    merged = pbp_weighted[cols].merge(ftn, on=["game_id", "play_id"], how="inner")
    if merged.empty or "n_blitzers" not in merged.columns:
        return pd.DataFrame()

    # Blitz rate is measured over dropbacks (you can't blitz a handoff meaningfully).
    if "qb_dropback" in merged.columns:
        merged = merged[merged["qb_dropback"] == 1]
    merged = merged[merged["defteam"].notna() & merged["n_blitzers"].notna()]
    if merged.empty:
        return pd.DataFrame()

    merged["_blitz"] = (merged["n_blitzers"] >= config.BLITZ_MIN_EXTRA_RUSHERS).astype(float)

    rows = []
    for team, g in merged.groupby("defteam"):
        row = {"team": team, "dropbacks_charted": float(g["w"].sum()),
               "blitz_rate": _wmean(g, "_blitz")}
        if "n_defense_box" in g.columns:
            row["avg_box"] = _wmean(g, "n_defense_box")
        rows.append(row)
    m = pd.DataFrame(rows).set_index("team")
    if not m.empty:
        m["blitz_rate_rank"] = _rank(m["blitz_rate"], best_high=True)  # rank 1 = blitziest
    return m


# --- play-style labels -------------------------------------------------------
def style_label(neutral_pass_rate: float) -> str:
    """Human-readable lean from neutral pass rate."""
    if neutral_pass_rate is None or np.isnan(neutral_pass_rate):
        return "—"
    if neutral_pass_rate >= 0.62:
        return "Very pass-heavy"
    if neutral_pass_rate >= 0.56:
        return "Pass-leaning"
    if neutral_pass_rate >= 0.50:
        return "Balanced"
    if neutral_pass_rate >= 0.44:
        return "Run-leaning"
    return "Very run-heavy"


def blitz_label(blitz_rate: float) -> str:
    if blitz_rate is None or np.isnan(blitz_rate):
        return "—"
    if blitz_rate >= 0.34:
        return "Heavy blitz"
    if blitz_rate >= 0.26:
        return "Above-average blitz"
    if blitz_rate >= 0.20:
        return "Average"
    return "Low blitz / coverage-heavy"


def _tier(rank) -> str | None:
    """Bucket a 1-32 rank into strong / mid / weak (1 = best)."""
    if rank is None or pd.isna(rank):
        return None
    r = int(rank)
    if r <= 8:
        return "strong"
    if r >= 25:
        return "weak"
    return "mid"


def unit_summary(pass_rank, rush_rank, defense: bool = False) -> str:
    """Plain-language 'where they're strong / where they struggle'.

    Offense reads like "Strong pass · weak run"; defense like "Soft vs run".
    Only notable units (top-8 / bottom-8) are called out; otherwise "Balanced".
    """
    tp, tr = _tier(pass_rank), _tier(rush_rank)
    if tp is None and tr is None:
        return "—"
    parts = []
    if defense:
        if tp == "strong": parts.append("stout vs pass")
        elif tp == "weak": parts.append("soft vs pass")
        if tr == "strong": parts.append("stout vs run")
        elif tr == "weak": parts.append("soft vs run")
    else:
        if tp == "strong": parts.append("strong pass")
        elif tp == "weak": parts.append("weak pass")
        if tr == "strong": parts.append("strong run")
        elif tr == "weak": parts.append("weak run")
    if not parts:
        return "Balanced"
    text = " · ".join(parts)
    return text[0].upper() + text[1:]


def coverage_label(zone_rate) -> str:
    """Man/zone identity from a defense's blended zone rate."""
    if zone_rate is None or pd.isna(zone_rate):
        return "—"
    z = float(zone_rate)
    if z >= 0.60:
        return f"Zone-heavy ({z * 100:.0f}%)"
    if z <= 0.45:
        return f"Man-heavy ({(1 - z) * 100:.0f}%)"
    return f"Balanced ({z * 100:.0f}% zone)"
