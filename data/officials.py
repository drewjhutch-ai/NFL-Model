"""Referee scoring tendencies — a totals angle from the officiating crew.

Some referees' games run consistently higher- or lower-scoring than league
average (how they call holding, pass interference, and clock/penalty tempo).
This rolls each referee's historical games into an average total and an over
rate vs the closing line. It's a reference signal: nflverse doesn't publish the
*upcoming* week's crew assignments in a reliable free feed, so we surface the
tendencies rather than auto-applying them to a specific game.
"""
from __future__ import annotations

import pandas as pd


def _ref_name_col(officials: pd.DataFrame):
    for c in ("official_name", "name", "off"):
        if c in officials.columns:
            return c
    return None


def referee_tendencies(officials: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """referee -> games, avg total points, over rate vs the line, penalty-tempo proxy."""
    if officials is None or officials.empty or schedule is None or schedule.empty:
        return pd.DataFrame()
    name_c = _ref_name_col(officials)
    if name_c is None or "game_id" not in officials.columns:
        return pd.DataFrame()
    refs = officials
    if "position" in officials.columns:
        refs = officials[officials["position"].astype(str).str.contains("Referee", case=False, na=False)]
        if refs.empty:
            refs = officials
    need = {"game_id", "home_score", "away_score"}
    if not need.issubset(schedule.columns):
        return pd.DataFrame()
    sched = schedule.dropna(subset=["home_score", "away_score"]).copy()
    sched["_total"] = sched["home_score"] + sched["away_score"]
    if "total_line" in sched.columns:
        sched["_over"] = (sched["_total"] > sched["total_line"]).astype(float)
    m = refs[[name_c, "game_id"]].merge(sched[["game_id", "_total"] +
                                              (["_over"] if "_over" in sched.columns else [])],
                                        on="game_id", how="inner")
    if m.empty:
        return pd.DataFrame()
    agg = {"games": ("game_id", "nunique"), "avg_total": ("_total", "mean")}
    if "_over" in m.columns:
        agg["over_rate"] = ("_over", "mean")
    out = m.groupby(name_c).agg(**agg)
    out = out[out["games"] >= 5].sort_values("avg_total", ascending=False)
    out["vs_league"] = out["avg_total"] - m["_total"].mean()
    return out.rename_axis("Referee")
