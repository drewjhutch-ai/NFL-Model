"""The 'Players' tab: usage, distribution-based prop projections, and an edge finder.

Projections adjust each player's recency-weighted average by the opposing
defense and the projected game script, then express the result as a *range*
(a distribution), not a single number. The prop-edge finder turns any line you
enter into a model probability, edge, fair price, and Kelly stake — the same
Bet-Engine math the Betting and Picks tabs use.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, betengine, loaders, players, props
from ui.components import fmt, ordinal


def _script(off, deff, extras, team, opp, team_is_home) -> float:
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    home, away = (team, opp) if team_is_home else (opp, team)
    margin = betting.project_margin(off, deff, home, away, st_ppg, qb)  # + = home
    if pd.isna(margin):
        return 0.0
    return float(margin if team_is_home else -margin)


def _proj_table(stats, off, deff, extras, team, opp, team_is_home, n=6) -> None:
    dvp = extras.get("dvp", {})
    script = _script(off, deff, extras, team, opp, team_is_home)
    t = players.team_players(stats, team).head(n)
    rows = []
    for _, p in t.iterrows():
        proj = props.project_player(p, opp, deff, dvp, script=script)
        if not proj:
            continue
        row = {"Player": p["name"], "Pos": p["pos"]}
        for stat, mean in proj.items():
            cv = props._CV.get(stat, 0.0)
            if cv and mean:
                row[stat] = f"{mean:.0f} ±{mean*cv:.0f}"
            else:
                row[stat] = f"{mean:.1f}"
        rows.append(row)
    if rows:
        arrow = "▲ favored" if script > 1 else ("▼ underdog" if script < -1 else "even")
        st.markdown(f"**{team}** vs {opp} defense · script {script:+.1f} ({arrow})")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _matchup(stats, off, deff, extras, schedule) -> None:
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded — use 'By team' or the prop finder.")
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
    c1, c2 = st.columns(2)
    with c1:
        _proj_table(stats, off, deff, extras, away, home, team_is_home=False)
    with c2:
        _proj_table(stats, off, deff, extras, home, away, team_is_home=True)
    st.caption("Projections adjust for the opposing defense **and** game script "
               "(favorites run more, dogs throw more). Ranges are ±1 std. "
               "Use the **Prop edge finder** to price a specific line.")


def _prop_finder(stats, off, deff, extras, schedule) -> None:
    st.markdown("### 🎯 Prop edge finder")
    st.caption("Enter the book's line for any player stat → model probability, edge, fair odds, "
               "and Kelly stake. No props feed needed — type the number off your sportsbook.")
    teams = sorted(stats["team"].dropna().unique())
    c1, c2 = st.columns(2)
    team = c1.selectbox("Team", teams, key="pf_team")
    opp = c2.selectbox("Opponent", [t for t in teams if t != team], key="pf_opp")
    tp = players.team_players(stats, team)
    if tp.empty:
        st.info("No players for this team yet.")
        return
    names = list(tp["name"])
    who = st.selectbox("Player", names, key="pf_player")
    p = tp[tp["name"] == who].iloc[0]
    # infer home/away from the schedule if possible (affects script)
    team_is_home = True
    if schedule is not None and not schedule.empty:
        gm = schedule[(schedule["home_team"] == team) & (schedule["away_team"] == opp)]
        team_is_home = not gm.empty or schedule[(schedule["home_team"] == opp) &
                                                (schedule["away_team"] == team)].empty
    script = _script(off, deff, extras, team, opp, team_is_home)
    proj = props.project_player(p, opp, deff, extras.get("dvp", {}), script=script)
    if not proj:
        st.info("No projectable stats for this player vs this opponent.")
        return
    stat = st.selectbox("Stat", list(proj.keys()), key="pf_stat")
    mean = proj[stat]
    c3, c4, c5 = st.columns(3)
    line = c3.number_input("Book line", value=float(round(mean, 1)), step=0.5, key="pf_line")
    over_odds = c4.number_input("Over odds", value=-110, step=5, key="pf_over")
    under_odds = c5.number_input("Under odds", value=-110, step=5, key="pf_under")

    p_over = props.over_prob(mean, float(line), stat)
    if pd.isna(p_over):
        st.info("Can't price this stat.")
        return
    side, p_side, odds, other = (("Over", p_over, over_odds, under_odds) if p_over >= 0.5
                                 else ("Under", 1 - p_over, under_odds, over_odds))
    bet = betengine._bet("finder", f"{team} vs {opp}", "Player prop",
                         f"{who} {stat} {side} {line:g}", p_side, odds, other,
                         games_played=0, rationale=f"Projected {mean:.1f}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Projection", f"{mean:.1f}")
    m2.metric(f"Model {side}", f"{p_side*100:.0f}%")
    m3.metric("Edge", f"{bet['edge']*100:+.1f} pts" if pd.notna(bet['edge']) else "—")
    m4.metric("Kelly", f"{bet['kelly']*100:.1f}u" if bet['kelly'] else "—")
    fair = betengine.fmt_odds(bet["fair_odds"])
    verdict = ("🟢 **Value** — take the " + side if pd.notna(bet["edge"]) and bet["edge"] > 0.02
               else "🟡 No clear edge at this price")
    st.markdown(f"{verdict}. Fair odds **{fair}** vs your **{betengine.fmt_odds(odds)}**.")


def _by_team(stats, teams) -> None:
    team = st.selectbox("Team", teams, key="pl_team")
    t = players.team_players(stats, team)
    if t.empty:
        st.info("No player data for this team yet.")
        return
    show = pd.DataFrame({
        "Player": t["name"], "Pos": t["pos"], "G": t["games"].round(0),
        "Pass yds": t["passing_yards"].round(1), "Rush yds": t["rushing_yards"].round(1),
        "Car": t["carries"].round(1), "Tgt": t["targets"].round(1),
        "Rec": t["receptions"].round(1), "Rec yds": t["receiving_yards"].round(1),
    })
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption("Per-game averages, recency-weighted (recent games count more).")


def render(off, deff, schedule, extras) -> None:
    st.subheader("Players — usage, prop projections & the edge finder")
    stats = extras.get("players")
    if stats is None or stats.empty:
        st.info("Player stats not available yet (they load once games are played).")
        return
    teams = sorted(stats["team"].dropna().unique())
    mode = st.radio("View", ["Matchup projections", "Prop edge finder", "By team"], horizontal=True)
    if mode == "By team":
        _by_team(stats, teams)
    elif mode == "Prop edge finder":
        _prop_finder(stats, off, deff, extras, schedule)
    else:
        _matchup(stats, off, deff, extras, schedule)
