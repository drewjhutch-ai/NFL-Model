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
    """Return {total_adj, margin_compression, pass_penalty, note} for a game."""
    none = {"total_adj": 0.0, "margin_compression": 0.0, "pass_penalty": 0.0, "note": ""}
    if row is None:
        return none
    roof = str(row.get("roof", "")).lower()
    if roof in _INDOOR:
        return {**none, "note": "🏟️ Indoors — no weather."}

    wind = row.get("wind")
    temp = row.get("temp")
    if pd.isna(wind) and pd.isna(temp):
        return none

    total_adj = 0.0
    pass_penalty = 0.0
    notes = []
    if pd.notna(wind) and wind >= config.WIND_THRESHOLD:
        over = wind - config.WIND_THRESHOLD
        total_adj -= min(over * config.WIND_PTS_PER_MPH, config.WIND_MAX_PTS)
        pass_penalty += min(over * 0.012, 0.10)
        notes.append(f"💨 {int(wind)} mph wind")
    if pd.notna(temp) and temp <= config.COLD_THRESHOLD:
        total_adj -= min((config.COLD_THRESHOLD - temp) * 0.08, 2.5)
        notes.append(f"🥶 {int(temp)}°F")

    # low-scoring games play closer -> regress the margin toward pick'em a touch
    margin_compression = min(abs(total_adj) * 0.015, 0.12)
    note = " · ".join(notes) + (" → lower total, closer game" if notes else "")
    return {"total_adj": total_adj, "margin_compression": margin_compression,
            "pass_penalty": pass_penalty, "note": note}
