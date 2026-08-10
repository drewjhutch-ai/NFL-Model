"""The 'Matchups' tab: put one team's offense against another's defense and
surface where the edges are, so you can make an informed pick.

Edge logic is deliberately simple and transparent (rank differentials). It's a
decision aid, not a black box -- you still make the call.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.components import fmt, ordinal


def _edge(off_rank, def_rank) -> tuple[str, float]:
    """Compare an offense unit rank vs the defense unit rank it faces.

    Both are 1..32 where 1 = best. The offense has an edge when it's strong
    (low rank) against a weak defense (high rank). Returns (label, magnitude).
    """
    if pd.isna(off_rank) or pd.isna(def_rank):
        return "—", 0.0
    # Defense rank flipped so a bad defense (32) becomes a big positive for offense.
    magnitude = (32 - int(def_rank)) - (int(off_rank) - 1)  # roughly -31..+31
    if magnitude >= 12:
        return "🟢 Strong offense edge", magnitude
    if magnitude >= 5:
        return "🟢 Lean offense", magnitude
    if magnitude <= -12:
        return "🔴 Strong defense edge", magnitude
    if magnitude <= -5:
        return "🔴 Lean defense", magnitude
    return "🟡 Even", magnitude


def _unit_row(name, off_team, off_rank, def_team, def_rank) -> dict:
    label, mag = _edge(off_rank, def_rank)
    return {
        "Matchup": name,
        f"{off_team} O (rank)": ordinal(off_rank),
        f"{def_team} D (rank)": ordinal(def_rank),
        "Edge": label,
        "_mag": mag,
    }


def _one_direction(off: pd.DataFrame, deff: pd.DataFrame, o_team: str, d_team: str) -> None:
    st.markdown(f"##### {o_team} offense vs. {d_team} defense")
    if o_team not in off.index or d_team not in deff.index:
        st.info("Not enough data for this side of the matchup.")
        return
    o = off.loc[o_team]
    d = deff.loc[d_team]
    rows = [
        _unit_row("Passing", o_team, o["pass_epa_rank"], d_team, d["pass_epa_rank"]),
        _unit_row("Rushing", o_team, o["rush_epa_rank"], d_team, d["rush_epa_rank"]),
        _unit_row("Explosive", o_team, o["explosive_rate_rank"], d_team, d["explosive_rate_rank"]),
        _unit_row("Overall", o_team, o["epa_play_rank"], d_team, d["epa_play_rank"]),
    ]
    df = pd.DataFrame(rows).drop(columns="_mag")
    st.dataframe(df, width='stretch', hide_index=True)


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame) -> None:
    st.subheader("Matchup Comparison")
    if off.empty or deff.empty:
        st.warning("Need offensive and defensive data to compare matchups.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    c1, c2 = st.columns(2)
    with c1:
        away = st.selectbox("Team A", teams, index=0, key="mu_away")
    with c2:
        default_b = 1 if len(teams) > 1 else 0
        home = st.selectbox("Team B", teams, index=default_b, key="mu_home")

    if away == home:
        st.info("Pick two different teams.")
        return

    left, right = st.columns(2)
    with left:
        _one_direction(off, deff, away, home)
        if not blitz.empty and home in blitz.index:
            from data import tendencies
            b = blitz.loc[home]
            st.caption(f"{home} D blitz: {tendencies.blitz_label(b['blitz_rate'])} "
                       f"({fmt(b['blitz_rate'], 'pct')})")
    with right:
        _one_direction(off, deff, home, away)
        if not blitz.empty and away in blitz.index:
            from data import tendencies
            b = blitz.loc[away]
            st.caption(f"{away} D blitz: {tendencies.blitz_label(b['blitz_rate'])} "
                       f"({fmt(b['blitz_rate'], 'pct')})")

    st.divider()
    st.caption(
        "Edges are rank differentials (1 = best, 32 = worst). A strong offense "
        "unit facing a weak defense unit lights up green. This is a decision aid "
        "— the pick is yours."
    )
