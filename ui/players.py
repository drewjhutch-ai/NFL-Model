"""The 'Players' tab: usage + matchup-adjusted prop projections.

Per-game player averages and projections that adjust for how the opposing defense
handles the position — the base layer for player props. Prop *lines* need a props
feed; the projections and matchup context here are free.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import loaders, players


def _by_team(stats, teams) -> None:
    team = st.selectbox("Team", teams, key="pl_team")
    t = players.team_players(stats, team)
    if t.empty:
        st.info("No player data for this team yet.")
        return
    show = pd.DataFrame({
        "Player": t["name"], "Pos": t["pos"], "G": t["games"].round(1),
        "Pass yds": t["passing_yards"].round(1),
        "Rush yds": t["rushing_yards"].round(1), "Car": t["carries"].round(1),
        "Tgt": t["targets"].round(1), "Rec": t["receptions"].round(1),
        "Rec yds": t["receiving_yards"].round(1),
    })
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption("Per-game averages, recency-weighted (recent games count more).")


def _proj_table(stats, deff, dvp, team, opp, n=6) -> None:
    t = players.team_players(stats, team).head(n)
    rows = []
    for _, p in t.iterrows():
        proj = players.project(p, opp, deff, dvp)
        if not proj:
            continue
        row = {"Player": p["name"], "Pos": p["pos"]}
        row.update({k: round(v, 1) for k, v in proj.items()})
        rows.append(row)
    if rows:
        st.markdown(f"**{team}** vs {opp} defense")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _matchup(stats, deff, extras, schedule) -> None:
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded — use 'By team' mode.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0, key="pl_wk")
    games = s[s["week"] == wk]
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    if not labels:
        st.info("No games this week.")
        return
    pick = st.selectbox("Game", labels, key="pl_game")
    row = games.iloc[labels.index(pick)]
    away, home = row["away_team"], row["home_team"]
    dvp = extras.get("dvp", {})
    c1, c2 = st.columns(2)
    with c1:
        _proj_table(stats, deff, dvp, away, home)
    with c2:
        _proj_table(stats, deff, dvp, home, away)
    st.caption("Projections nudge each player's average by how the opposing defense "
               "handles the position. 🔒 Add a player-props odds feed to flag value vs lines.")


def render(off, deff, schedule, extras) -> None:
    st.subheader("Players — usage & prop projections")
    stats = extras.get("players")
    if stats is None or stats.empty:
        st.info("Player stats not available yet (they load once games are played).")
        return
    teams = sorted(stats["team"].dropna().unique())
    mode = st.radio("View", ["Matchup projections", "By team"], horizontal=True)
    if mode == "By team":
        _by_team(stats, teams)
    else:
        _matchup(stats, deff, extras, schedule)
