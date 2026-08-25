"""Evolution Engine — the model's memory of the season.

Everything else in the app recomputes from scratch on each load and then forgets.
That makes "track the game week to week" impossible. This module adds memory in
two layers:

1. **On-the-fly weekly trends** — team EPA by week, computed straight from this
   season's play-by-play. Powers sparklines and "heating up / cooling off" the
   moment there are two weeks of games, with no persistence required.

2. **Persisted weekly snapshots** — each week the GitHub Action freezes every
   team's ranks and power rating (``history/team_history_<season>.csv``) and our
   game projections (``history/proj_history_<season>.csv``). That memory powers
   week-over-week rank *movement* arrows and the model report card: we grade the
   projections we made last week against the results that have since come in, and
   the accuracy feeds the learning loop.

All readers degrade gracefully — before games exist (offseason, Week 1) every
function returns an empty frame and the UI shows a clean "trends begin soon"
state instead of breaking.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import config

HISTORY_DIR = Path(__file__).resolve().parents[1] / "history"

# Rank columns we snapshot and track movement on. Maps a short key -> the column
# name as it appears in the offense/defense frames.
_OFF_RANKS = {"off": "epa_play_rank", "pass_off": "pass_epa_rank",
              "rush_off": "rush_epa_rank", "explosive_off": "explosive_rate_rank"}
_DEF_RANKS = {"def": "epa_play_rank", "pass_def": "pass_epa_rank",
              "rush_def": "rush_epa_rank"}


# --- layer 1: on-the-fly weekly trends ---------------------------------------
def weekly_epa(pbp: pd.DataFrame, season: int | None = None) -> pd.DataFrame:
    """Long frame of per-team, per-week EPA/play for offense and defense.

    Columns: team, week, off_epa, def_epa, net. Uses the current season if it has
    games, else the prior (phantom) season, so a trajectory always renders once
    real weeks exist. Raw (not opponent-adjusted) — this is a form trajectory.
    """
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return pd.DataFrame(columns=["team", "week", "off_epa", "def_epa", "net"])
    if season is None:
        season = (config.CURRENT_SEASON
                  if (pbp["season"] == config.CURRENT_SEASON).any()
                  else config.PRIOR_SEASON)
    df = pbp[(pbp["season"] == season) & pbp["week"].notna() & pbp["epa"].notna()]
    if df.empty:
        return pd.DataFrame(columns=["team", "week", "off_epa", "def_epa", "net"])
    off = df.groupby(["posteam", "week"])["epa"].mean().rename("off_epa")
    deff = df.groupby(["defteam", "week"])["epa"].mean().rename("def_epa")
    out = pd.concat([off, deff], axis=1).reset_index()
    out = out.rename(columns={out.columns[0]: "team"})
    out["net"] = out["off_epa"].fillna(0) - out["def_epa"].fillna(0)
    return out.sort_values(["team", "week"]).reset_index(drop=True)


def spark_series(weekly: pd.DataFrame, team: str, metric: str = "net") -> list[float]:
    """Ordered list of a team's weekly values for a sparkline (empty if none)."""
    if weekly is None or weekly.empty or team not in set(weekly["team"]):
        return []
    s = weekly[weekly["team"] == team].sort_values("week")[metric]
    return [float(v) for v in s if pd.notna(v)]


def trajectory(weekly: pd.DataFrame, team: str, metric: str = "net",
               window: int = 3) -> float:
    """Slope-ish read: mean of the last ``window`` weeks minus the season mean.

    Positive = trending above their own baseline lately. NaN if too little data.
    """
    vals = spark_series(weekly, team, metric)
    if len(vals) < 2:
        return np.nan
    recent = np.mean(vals[-window:])
    return float(recent - np.mean(vals))


# --- layer 2: persisted snapshots --------------------------------------------
def _team_hist_path(season: int) -> Path:
    return HISTORY_DIR / f"team_history_{season}.csv"


def _proj_hist_path(season: int) -> Path:
    return HISTORY_DIR / f"proj_history_{season}.csv"


def snapshot_frame(off: pd.DataFrame, deff: pd.DataFrame, extras: dict,
                   season: int, week: int) -> pd.DataFrame:
    """One row per team: the ranks + power rating to freeze for this week."""
    from data import betting  # local import avoids a cycle
    power = betting.power_ratings(off, deff)
    teams = sorted(set(off.index) | set(deff.index))
    st = extras.get("st_ppg")
    sos = extras.get("sos")
    rows = []
    for t in teams:
        row = {"season": season, "week": int(week), "team": t}
        row["net"] = float(power.loc[t, "net"]) if t in power.index else np.nan
        row["power_rank"] = (int(power.loc[t, "power_rank"])
                             if t in power.index and pd.notna(power.loc[t, "power_rank"]) else np.nan)
        for key, col in _OFF_RANKS.items():
            row[f"{key}_rank"] = (int(off.loc[t, col])
                                  if t in off.index and pd.notna(off.loc[t, col]) else np.nan)
        for key, col in _DEF_RANKS.items():
            row[f"{key}_rank"] = (int(deff.loc[t, col])
                                  if t in deff.index and pd.notna(deff.loc[t, col]) else np.nan)
        row["st_ppg"] = float(st.get(t)) if st is not None and t in getattr(st, "index", []) else np.nan
        row["sos"] = float(sos.get(t)) if sos is not None and t in getattr(sos, "index", []) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def write_snapshot(frame: pd.DataFrame, season: int, week: int) -> Path:
    """Append this week's snapshot, replacing any existing row for the same week."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _team_hist_path(season)
    if path.exists():
        prev = pd.read_csv(path)
        prev = prev[prev["week"] != int(week)]
        frame = pd.concat([prev, frame], ignore_index=True)
    frame = frame.sort_values(["week", "power_rank"]).reset_index(drop=True)
    frame.to_csv(path, index=False)
    return path


def load_history(season: int) -> pd.DataFrame:
    """Full persisted team-history frame for a season (empty if none yet)."""
    path = _team_hist_path(season)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:  # noqa: BLE001 - a corrupt/partial file shouldn't crash the app
        return pd.DataFrame()


def rank_movement(history: pd.DataFrame, metric: str = "power_rank") -> pd.Series:
    """Per-team change in a rank vs the previous snapshot week.

    Positive = *improved* (moved toward #1) since last week. Empty if there aren't
    two snapshot weeks yet. Ranks are 1=best, so improvement is prev_rank - now.
    """
    if history is None or history.empty or "week" not in history.columns:
        return pd.Series(dtype=float)
    weeks = sorted(history["week"].dropna().unique())
    if len(weeks) < 2 or metric not in history.columns:
        return pd.Series(dtype=float)
    now = history[history["week"] == weeks[-1]].set_index("team")[metric]
    prev = history[history["week"] == weeks[-2]].set_index("team")[metric]
    delta = prev.reindex(now.index) - now  # + = improved (rank got smaller)
    return delta.dropna()


def hist_spark(history: pd.DataFrame, team: str, metric: str = "net") -> list[float]:
    """A team's persisted week-by-week values for a sparkline (empty if none)."""
    if history is None or history.empty or "team" not in history.columns:
        return []
    s = history[history["team"] == team].sort_values("week")
    return [float(v) for v in s[metric] if pd.notna(v)] if metric in s.columns else []


# --- layer 2b: projection snapshots + grading (the report card) --------------
def snapshot_projections(schedule: pd.DataFrame, off: pd.DataFrame, deff: pd.DataFrame,
                         extras: dict, season: int, week: int) -> pd.DataFrame:
    """Freeze our pre-game projections for a week's games (for later grading)."""
    from data import betting  # local import avoids a cycle
    if schedule is None or schedule.empty:
        return pd.DataFrame()
    games = schedule[(schedule["season"] == season) & (schedule["week"] == int(week))]
    rows = []
    for _, r in games.iterrows():
        a = betting.assess(r, off, deff, extras)
        rows.append({
            "season": season, "week": int(week),
            "game_id": r.get("game_id"), "home": a["home"], "away": a["away"],
            "model_margin": a["model_margin"], "blended_margin": a["blended_margin"],
            "model_total": a["model_total"], "model_p_home": a["model_p_home"],
            "mkt_spread": a["mkt_spread"], "total_line": a["total_line"],
            "value_side": a["value_side"], "total_side": a["total_side"],
        })
    return pd.DataFrame(rows)


def write_projections(frame: pd.DataFrame, season: int, week: int) -> Path | None:
    if frame is None or frame.empty:
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _proj_hist_path(season)
    if path.exists():
        prev = pd.read_csv(path)
        prev = prev[prev["week"] != int(week)]
        frame = pd.concat([prev, frame], ignore_index=True)
    frame.to_csv(path, index=False)
    return path


def load_projections(season: int) -> pd.DataFrame:
    path = _proj_hist_path(season)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def grade_projections(proj: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """Score our stored projections against final results.

    Returns hit-rates for our side (ATS), total, and straight-up winner, plus a
    sample count. Empty dict until at least one graded game exists.
    """
    if proj is None or proj.empty or schedule is None or schedule.empty:
        return {}
    res = schedule.dropna(subset=["result"]) if "result" in schedule.columns else pd.DataFrame()
    if res.empty:
        return {}
    res = res.set_index("game_id")
    ats_hit = ats_n = tot_hit = tot_n = su_hit = su_n = 0
    for _, p in proj.iterrows():
        gid = p.get("game_id")
        if gid not in res.index:
            continue
        r = res.loc[gid]
        home_margin = r.get("result")            # home score - away score
        total_pts = r.get("total")
        if pd.notna(home_margin):
            # straight up
            if pd.notna(p.get("model_margin")):
                su_n += 1
                pick_home = p["model_margin"] > 0
                su_hit += int(pick_home == (home_margin > 0))
            # against the spread (did our value side cover?)
            side, spread = p.get("value_side"), p.get("mkt_spread")
            if isinstance(side, str) and pd.notna(spread):
                ats_n += 1
                cover_margin = home_margin + spread  # >0 = home covered
                covered_home = cover_margin > 0
                ats_hit += int((side == p["home"]) == covered_home)
        if pd.notna(total_pts) and isinstance(p.get("total_side"), str) and pd.notna(p.get("total_line")):
            tot_n += 1
            went_over = total_pts > p["total_line"]
            tot_hit += int((p["total_side"] == "Over") == went_over)
    out = {}
    if su_n:
        out["su"] = {"hit": su_hit, "n": su_n, "pct": su_hit / su_n}
    if ats_n:
        out["ats"] = {"hit": ats_hit, "n": ats_n, "pct": ats_hit / ats_n}
    if tot_n:
        out["total"] = {"hit": tot_hit, "n": tot_n, "pct": tot_hit / tot_n}
    return out
