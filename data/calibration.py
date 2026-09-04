"""Calibration & attribution — is the model actually honest, and does the blend earn its keep?

Two questions the hit-rate report card can't answer:

1. **Calibration.** When the model says 70%, does it happen ~70% of the time? A
   miscalibrated model bleeds money — worst of all on parlays, which compound the
   error. We grade the stored pre-game win probabilities against outcomes with a
   Brier score and a reliability table (predicted bucket → actual rate).

2. **Attribution.** Does our number actually beat the market, and does the
   ensemble blend beat the raw model? We compare mean-absolute margin error for
   the model, the blended model, and the market spread over the same games. If we
   don't beat the closing number, no amount of features matters.

Everything reads the committed projection log (history/proj_history_<season>.csv),
so it fills in as the season is graded — empty and honest until then.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _graded(proj: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Join stored projections to final results (home margin + total)."""
    if proj is None or proj.empty or schedule is None or schedule.empty:
        return pd.DataFrame()
    if "result" not in schedule.columns or "game_id" not in schedule.columns:
        return pd.DataFrame()
    res = schedule.dropna(subset=["result"])[["game_id", "result"]].rename(
        columns={"result": "home_margin"})
    m = proj.merge(res, on="game_id", how="inner")
    return m.dropna(subset=["home_margin"])


def grade(proj: pd.DataFrame, schedule: pd.DataFrame, bins: int = 5) -> dict:
    """Calibration + attribution metrics, or {} until there are graded games."""
    g = _graded(proj, schedule)
    if g.empty:
        return {}
    out: dict = {"n": int(len(g))}

    # --- win-probability calibration ---
    if "model_p_home" in g.columns:
        gp = g.dropna(subset=["model_p_home"]).copy()
        if not gp.empty:
            gp["win"] = (gp["home_margin"] > 0).astype(float)
            gp["p"] = gp["model_p_home"].clip(0, 1)
            out["brier"] = float(((gp["p"] - gp["win"]) ** 2).mean())
            out["base_brier"] = float(((gp["win"].mean() - gp["win"]) ** 2).mean())
            edges = np.linspace(0, 1, bins + 1)
            rel = []
            for lo, hi in zip(edges[:-1], edges[1:]):
                m = gp[(gp["p"] >= lo) & (gp["p"] < hi if hi < 1 else gp["p"] <= hi)]
                if len(m):
                    rel.append({"bucket": f"{lo*100:.0f}–{hi*100:.0f}%",
                                "predicted": float(m["p"].mean()),
                                "actual": float(m["win"].mean()), "n": int(len(m))})
            out["reliability"] = rel

    # --- margin attribution: model vs blended vs market ---
    def _mae(col, is_market=False):
        if col not in g.columns:
            return None
        d = g.dropna(subset=[col])
        if d.empty:
            return None
        pred = d[col]
        return float((pred - d["home_margin"]).abs().mean())

    out["model_mae"] = _mae("model_margin")
    out["blended_mae"] = _mae("blended_margin")
    out["market_mae"] = _mae("mkt_spread")   # mkt_spread = home margin the market expects
    if "model_margin" in g.columns:
        gm = g.dropna(subset=["model_margin"])
        if not gm.empty:
            out["margin_bias"] = float((gm["model_margin"] - gm["home_margin"]).mean())
    return out


def verdict(cal: dict) -> str:
    """One-line plain-English read of where the model stands."""
    if not cal:
        return "No graded games yet — calibration fills in as the season is played."
    bits = []
    if cal.get("brier") is not None and cal.get("base_brier"):
        skill = 1 - cal["brier"] / cal["base_brier"] if cal["base_brier"] else 0
        bits.append(f"Brier {cal['brier']:.3f} ({'beats' if skill > 0 else 'trails'} "
                    f"the naive baseline)")
    mm, km = cal.get("model_mae"), cal.get("market_mae")
    if mm is not None and km is not None:
        bits.append(f"our margin error {mm:.1f} vs market {km:.1f} — "
                    f"{'beating' if mm < km else 'behind'} the number")
    if cal.get("margin_bias") is not None and abs(cal["margin_bias"]) >= 0.8:
        side = "home" if cal["margin_bias"] > 0 else "away"
        bits.append(f"a {abs(cal['margin_bias']):.1f}-pt lean toward {side} teams (bias to watch)")
    return " · ".join(bits) if bits else "Grading in progress."
