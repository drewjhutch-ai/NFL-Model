"""NFL model dashboard — Streamlit entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from data import loaders, tendencies
from ui import matchups, picks, team_tendencies

st.set_page_config(page_title="NFL Model", page_icon="🏈", layout="wide")


@st.cache_data(ttl=60 * 60, show_spinner="Crunching tendencies…")
def build_frames():
    """Load, weight, and aggregate everything the tabs need. Cached as a unit."""
    pbp = loaders.load_pbp()
    ftn = loaders.load_ftn()
    pbp_w = loaders.add_recency_weight(pbp)

    off = tendencies.compute_offense(pbp_w)
    deff = tendencies.compute_defense(pbp_w)
    blitz = tendencies.compute_blitz(pbp_w, ftn)
    live = loaders.has_current_season_data(pbp_w)
    return off, deff, blitz, live


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
    st.sidebar.caption("Data: nflverse (free) + FTN charting. Coverage scheme: paid feed (pluggable).")


def main() -> None:
    try:
        off, deff, blitz, live = build_frames()
    except Exception as exc:  # noqa: BLE001
        st.error("Couldn't load NFL data. Are you online? See console for details.")
        st.exception(exc)
        return

    sidebar(live)

    tab_data, tab_matchups, tab_picks = st.tabs(
        ["📊 Team Data", "⚔️ Matchups", "🎯 Picks of the Week"]
    )
    with tab_data:
        team_tendencies.render(off, deff, blitz)
    with tab_matchups:
        matchups.render(off, deff, blitz)
    with tab_picks:
        picks.render()


if __name__ == "__main__":
    main()
