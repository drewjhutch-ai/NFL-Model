"""Weather effects on the projection.

Wind is the dominant weather factor in the NFL — it drags down passing, field
goals, and scoring; cold has a smaller effect. Domes and closed roofs remove it.
This converts a game's conditions into a **total adjustment** (points off the
over/under), a **margin compression** (low-scoring games play closer, regressing
the spread toward pick'em), and a passing dampener the matchup edges can use.
"""
from __future__ import annotations

import pandas as pd

import config

_INDOOR = {"dome", "closed", "indoors", "retractable_closed"}


def weather_effects(row: pd.Series) -> dict:
    """Wind/cold → betting adjustments for a game.

    Returns total_adj (points off the O/U), pass_factor & rush_factor (script
    shift for props — wind suppresses passing and tilts to the run), pass_penalty
    (legacy additive form), margin_compression (low-scoring plays closer), fg_hit
    (kicking meaningfully hampered), and a human note. Calibrated to research:
    negligible < ~8 mph, accelerating, ~−6 pts at 20 mph, kicking hit hard at 20+.
    """
    none = {"total_adj": 0.0, "margin_compression": 0.0, "pass_penalty": 0.0,
            "pass_factor": 1.0, "rush_factor": 1.0, "fg_hit": False, "note": ""}
    if row is None:
        return none
    roof = str(row.get("roof", "")).lower()
    if roof in _INDOOR:
        return {**none, "note": "Indoors — no weather."}

    wind = row.get("wind")
    temp = row.get("temp")
    gust = row.get("wind_gust")
    if pd.isna(wind) and pd.isna(temp):
        return none

    total_adj = 0.0
    pass_factor = 1.0
    rush_factor = 1.0
    fg_hit = False
    notes = []
    if pd.notna(wind):
        # gusts hit the kicking/deep game beyond the steady wind — fold in a share
        eff = float(wind)
        if pd.notna(gust) and gust > wind:
            eff += (float(gust) - float(wind)) * 0.3
        if eff >= config.WIND_THRESHOLD:
            over = eff - config.WIND_THRESHOLD
            total_adj -= min(config.WIND_COEF * over ** config.WIND_EXPONENT, config.WIND_MAX_PTS)
            pass_factor -= min(over * 0.008, 0.16)     # passing yards suppressed
            rush_factor += min(over * 0.004, 0.07)     # script tilts to the run
            fg_hit = eff >= 18                          # FG range/accuracy hit hard
            g = f", gust {int(gust)}" if pd.notna(gust) and gust > wind + 4 else ""
            notes.append(f"{int(wind)} mph wind{g}")
    if pd.notna(temp) and temp <= config.COLD_THRESHOLD:
        total_adj -= min((config.COLD_THRESHOLD - temp) * 0.08, 2.5)
        notes.append(f"{int(temp)}°F")

    pass_penalty = 1.0 - pass_factor   # legacy additive fraction
    margin_compression = min(abs(total_adj) * 0.015, 0.12)
    tail = []
    if total_adj <= -0.5:
        tail.append("lower total")
    if fg_hit:
        tail.append("FG range hit")
    if pass_factor <= 0.95:
        tail.append("passing down, lean run")
    note = " · ".join(notes) + ((" → " + ", ".join(tail)) if notes and tail else "")
    return {"total_adj": total_adj, "margin_compression": margin_compression,
            "pass_penalty": pass_penalty, "pass_factor": pass_factor,
            "rush_factor": rush_factor, "fg_hit": fg_hit, "note": note}
