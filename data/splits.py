"""Situational splits — where NextGen-level scouting lives.

Season aggregates hide *how* a team wins. These splits break a team's EPA/play
down by the cuts that actually move a betting number: early vs late down, neutral
game script vs garbage time, when leading vs trailing, and home vs away. All
computed from the play-by-play already loaded, weighted by the same recency
scheme, so a team that's a different animal at home or on early downs shows it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _wmean(g: pd.DataFrame) -> float:
    w = g["w"] if "w" in g.columns else pd.Series(1.0, index=g.index)
    wsum = w.sum()
    return float((g["epa"] * w).sum() / wsum) if wsum else np.nan


def _side_epa(pbp: pd.DataFrame, team: str, mask: pd.Series, side: str) -> float:
    col = "posteam" if side == "off" else "defteam"
    sub = pbp[mask & (pbp[col] == team) & pbp["epa"].notna()]
    return _wmean(sub) if not sub.empty else np.nan


def team_splits(pbp: pd.DataFrame, schedule: pd.DataFrame, team: str) -> pd.DataFrame:
    """A tidy table of a team's offense/defense EPA across situational splits."""
    if pbp is None or pbp.empty or "epa" not in pbp.columns:
        return pd.DataFrame()
    df = pbp
    if "season" in df.columns:
        season = (config.CURRENT_SEASON if (df["season"] == config.CURRENT_SEASON).any()
                  else config.PRIOR_SEASON)
        df = df[df["season"] == season]
    if df.empty:
        return pd.DataFrame()
    down = df.get("down")
    wp = df.get("wp")

    splits: list[tuple[str, pd.Series]] = [("All plays", pd.Series(True, index=df.index))]
    if down is not None:
        splits.append(("Early downs (1–2)", down.isin([1, 2])))
        splits.append(("Late downs (3–4)", down.isin([3, 4])))
    if wp is not None:
        neutral = (wp >= config.NEUTRAL_WP_MIN) & (wp <= config.NEUTRAL_WP_MAX)
        splits.append(("Neutral script", neutral))
        splits.append(("When leading", wp >= 0.65))
        splits.append(("When trailing", wp <= 0.35))

    # home / away needs the schedule's home_team keyed by game_id
    if schedule is not None and not schedule.empty and "game_id" in df.columns:
        home_by_game = schedule.set_index("game_id")["home_team"].to_dict()
        gid_home = df["game_id"].map(home_by_game)
        is_home_off = (df.get("posteam") == gid_home)
        splits.append(("At home (off)", is_home_off))
        splits.append(("On the road (off)", (df.get("posteam") != gid_home) & df.get("posteam").notna()))

    rows = []
    for label, mask in splits:
        home_away = "(off)" in label
        off_epa = _side_epa(df, team, mask, "off")
        row = {"Split": label.replace(" (off)", ""), "Off EPA/play": off_epa}
        if not home_away:
            row["Def EPA/play"] = _side_epa(df, team, mask, "def")
        rows.append(row)
    return pd.DataFrame(rows)
