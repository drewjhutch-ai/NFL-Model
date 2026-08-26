"""NFL model dashboard — Streamlit entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from data import loaders, pipeline
from ui import betting, gamebets, league, matchups, picks, team_tendencies
from ui import players as ui_players

st.set_page_config(page_title="NFL Model", page_icon="🏈", layout="wide")


@st.cache_data(ttl=60 * 60, show_spinner="Crunching tendencies…")
def build_frames():
    """Load, weight, and aggregate everything the tabs need. Cached as a unit.

    The heavy lifting lives in ``data.pipeline`` so the weekly snapshot Action
    can reuse the exact same code path outside Streamlit.
    """
    return pipeline.build_frames()


def sidebar(live: bool) -> None:
    st.sidebar.title("🏈 NFL Model")
    if live:
        st.sidebar.success(f"Live: {config.CURRENT_SEASON} season is driving the data.")
    else:
        st.sidebar.warning(
            f"Offseason mode: no {config.CURRENT_SEASON} games yet. Showing the "
            f"{config.PRIOR_SEASON} phantom baseline until Week 1."
        )
    st.sidebar.caption(
        f"Current season: **{config.CURRENT_SEASON}**  \n"
        f"Baseline: **{config.PRIOR_SEASON}** (weight {config.PRIOR_SEASON_WEIGHT:g})"
    )
    if st.sidebar.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown("### 🔒 Coverage (zone/man)")
    st.sidebar.caption(
        "A weekly GitHub Action auto-fetches zone/man from the free sources "
        "and commits it, so this loads without any manual step. "
        "Optionally add PFF for gold-standard charting:"
    )
    up = st.sidebar.file_uploader(
        "Upload PFF coverage CSV", type=["csv"], key="pff_upload",
        help="Export the team coverage table from PFF (ELITE/+) and upload it here. "
             "Optional — the free sources work without it.",
    )
    if up is not None:
        st.session_state["pff_bytes"] = up.getvalue()
    if st.session_state.get("pff_bytes"):
        col_a, col_b = st.sidebar.columns([3, 1])
        col_a.success("PFF export loaded ✓")
        if col_b.button("Clear", key="pff_clear"):
            st.session_state.pop("pff_bytes", None)
            st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(
        "Data: nflverse + FTN charting (free). Coverage scheme: weekly "
        "auto-fetch blended with PFF + SumerSports + StatRankings."
    )


def main() -> None:
    try:
        off, deff, blitz, live, schedule, extras = build_frames()
    except Exception as exc:  # noqa: BLE001
        st.error("Couldn't load NFL data. Are you online? See console for details.")
        st.exception(exc)
        return

    sidebar(live)

    (tab_data, tab_league, tab_matchups, tab_players, tab_gamebets,
     tab_betting, tab_picks) = st.tabs(
        ["📊 Team Data", "📋 League", "⚔️ Matchups", "🧍 Players",
         "🎰 Game Bets", "💰 Betting", "🎯 Picks of the Week"])
    with tab_data:
        team_tendencies.render(off, deff, blitz, extras)
    with tab_league:
        league.render(off, deff, blitz, extras)
    with tab_matchups:
        matchups.render(off, deff, blitz, schedule, extras)
    with tab_players:
        ui_players.render(off, deff, schedule, extras)
    with tab_gamebets:
        gamebets.render(off, deff, blitz, schedule, extras)
    with tab_betting:
        betting.render(off, deff, schedule, extras)
    with tab_picks:
        picks.render(off, deff, schedule, extras)


if __name__ == "__main__":
    main()
