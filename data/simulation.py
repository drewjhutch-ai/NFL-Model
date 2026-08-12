"""Monte Carlo game simulation.

Turns our point projections (margin + total) into full outcome distributions:
win probability, cover probability, over probability, a projected box score, and
the spread of likely finals. This is what lets you reason in probabilities the
way the market does, instead of a single number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data import betting
from data.weather import weather_effects


def simulate(off: pd.DataFrame, deff: pd.DataFrame, home: str, away: str,
             extras: dict, row: pd.Series | None = None, n: int | None = None) -> dict:
    """Simulate a game n times; return distributions + probabilities."""
    n = n or config.SIM_N
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    margin_mean = betting.project_margin(off, deff, home, away, st_ppg, qb)  # + = home
    total_mean = betting.project_total(off, deff, home, away, extras.get("pace"))
    if pd.isna(margin_mean) or pd.isna(total_mean):
        return {}

    if row is not None:
        wx = weather_effects(row)
        total_mean += wx["total_adj"]
        margin_mean *= (1 - wx["margin_compression"])
        if qb is not None and not qb.empty:
            from data.qbvalue import qb_adjustment
            total_mean -= 0.5 * (qb_adjustment(qb, home) + qb_adjustment(qb, away))

    rng = np.random.default_rng(42)
    margins = rng.normal(margin_mean, config.MARGIN_STD, n)
    totals = np.clip(rng.normal(total_mean, config.TOTAL_STD, n), 20, None)
    home_pts = (totals + margins) / 2
    away_pts = (totals - margins) / 2

    out = {
        "home": home, "away": away, "n": n,
        "margin_mean": float(margin_mean), "total_mean": float(total_mean),
        "home_win": float((margins > 0).mean()),
        "proj_home": float(home_pts.mean()), "proj_away": float(away_pts.mean()),
        "margins": margins, "totals": totals,
    }
    if row is not None:
        mkt_spread = row.get("spread_line")
        mkt_total = row.get("total_line")
        if pd.notna(mkt_spread):
            out["home_cover"] = float((margins > mkt_spread).mean())
            out["mkt_spread"] = mkt_spread
        if pd.notna(mkt_total):
            out["over"] = float((totals > mkt_total).mean())
            out["mkt_total"] = mkt_total
    return out


def game_script(margin_mean: float) -> str:
    """A quick read on how the game likely flows."""
    m = abs(margin_mean)
    if m >= 10:
        return "Likely one-sided — expect the trailing team pass-heavy, garbage-time risk."
    if m >= 4:
        return "Favorite controls — script leans run-late for the leader."
    return "Projected close — script stays balanced, late-game leverage matters."
