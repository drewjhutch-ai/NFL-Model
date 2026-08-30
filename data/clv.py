"""Closing-line value and ROI — the honest scoreboard for a betting model.

Hit-rate flatters; **ROI** (did the bets make money) and **CLV** (did we beat the
closing line) are what actually predict long-term profit. Both are graded from the
projections the Evolution Engine already stores each week:

  * **ROI** — settle every recommended spread/total pick at -110 and total the
    units won/lost.
  * **CLV** — compare the line we captured (stored at pick time, early week) to the
    closing line (the schedule's final number). Consistently beating the close is
    the single best sign the model is genuinely sharp, win or lose on the day.

Both return empty until at least one game has been graded, so they no-op cleanly
in the offseason and early in a week.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_WIN_UNITS = 100 / 110   # profit on a 1-unit bet at -110


def _settled(schedule: pd.DataFrame) -> pd.DataFrame:
    if schedule is None or schedule.empty or "result" not in schedule.columns:
        return pd.DataFrame()
    s = schedule.dropna(subset=["result"]).copy()
    if s.empty:
        return s
    if "home_score" in s.columns and "away_score" in s.columns:
        s["_total"] = s["home_score"] + s["away_score"]
    else:
        s["_total"] = np.nan
    return s.set_index("game_id")


def grade_roi(proj: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """Units won/lost and ROI% for our stored spread & total picks (at -110)."""
    if proj is None or proj.empty:
        return {}
    res = _settled(schedule)
    if res.empty:
        return {}
    rec = {"spread": [0, 0, 0.0], "total": [0, 0, 0.0]}   # wins, losses, units
    for _, p in proj.iterrows():
        gid = p.get("game_id")
        if gid not in res.index:
            continue
        r = res.loc[gid]
        hm = r.get("result")
        # spread pick
        side, sp = p.get("value_side"), p.get("mkt_spread")
        if isinstance(side, str) and pd.notna(sp) and pd.notna(hm):
            cover = hm + sp                       # >0 home covered, 0 push
            if cover != 0:
                won = (side == p["home"]) == (cover > 0)
                rec["spread"][0 if won else 1] += 1
                rec["spread"][2] += _WIN_UNITS if won else -1
        # total pick
        ts, tl, tp = p.get("total_side"), p.get("total_line"), r.get("_total")
        if isinstance(ts, str) and pd.notna(tl) and pd.notna(tp) and tp != tl:
            won = (ts == "Over") == (tp > tl)
            rec["total"][0 if won else 1] += 1
            rec["total"][2] += _WIN_UNITS if won else -1
    out = {}
    for k, (w, l, u) in rec.items():
        n = w + l
        if n:
            out[k] = {"record": f"{w}-{l}", "units": round(u, 2), "roi": round(u / n * 100, 1)}
    tot_n = sum(rec[k][0] + rec[k][1] for k in rec)
    tot_u = sum(rec[k][2] for k in rec)
    if tot_n:
        out["overall"] = {"bets": tot_n, "units": round(tot_u, 2), "roi": round(tot_u / tot_n * 100, 1)}
    return out


def grade_clv(proj: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """Average closing-line value (points) and how often we beat the close."""
    if proj is None or proj.empty:
        return {}
    res = _settled(schedule)
    if res.empty:
        return {}
    diffs = []
    for _, p in proj.iterrows():
        side, ourline = p.get("value_side"), p.get("mkt_spread")
        gid = p.get("game_id")
        if not isinstance(side, str) or pd.isna(ourline) or gid not in res.index:
            continue
        close = res.loc[gid].get("spread_line")
        if pd.isna(close):
            continue
        # + = we captured a better number than the close (home spread convention)
        clv = (close - ourline) if side == p["home"] else (ourline - close)
        diffs.append(clv)
    if not diffs:
        return {}
    arr = np.array(diffs, dtype=float)
    return {"avg_clv": round(float(arr.mean()), 2),
            "beat_pct": round(float((arr > 0).mean()) * 100),
            "n": len(diffs)}
