"""NFL model dashboard — Streamlit entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from data import (adjust, injuries, loaders, positional, pressure, rushing,
                  situational, tendencies)
from ui import betting, league, matchups, picks, team_tendencies

st.set_page_config(page_title="NFL Model", page_icon="🏈", layout="wide")


@st.cache_data(ttl=60 * 60, show_spinner="Crunching tendencies…")
def build_frames():
    """Load, weight, and aggregate everything the tabs need. Cached as a unit."""
    pbp = loaders.load_pbp()
    ftn = loaders.load_ftn()
    pbp_w = loaders.add_recency_weight(pbp)

    off = tendencies.compute_offense(pbp_w)
    deff = tendencies.compute_defense(pbp_w)
    # opponent-adjust EPA (strength of schedule) — flows into ranks, edges, betting
    off, deff = adjust.apply_epa_adjustment(off, deff, pbp_w)
    tendencies.compute_qb_rank(off)
    blitz = tendencies.compute_blitz(pbp_w, ftn)
    live = loaders.has_current_season_data(pbp_w)

    schedule = loaders.load_schedule()
    posmap = loaders.position_map()
    wr_off, wr_def = positional.wr_tiers(pbp_w, posmap)
    extras = {
        "dvp": positional.defense_vs_position(pbp_w, posmap),
        "usage": positional.offense_usage(pbp_w, posmap),
        "wr_off": wr_off,
        "wr_def": wr_def,
        "qb": pressure.qb_profiles(pbp_w, posmap),
        "pressure": pressure.defense_pressure(pbp_w),
        "protection": pressure.offense_protection(pbp_w),
        "ovb": pressure.offense_vs_blitz(pbp_w, ftn),
        "rush": rushing.team_rushing_profile(loaders.load_ngs_rushing()),
        "off_sit": situational.offense_situational(pbp_w),
        "def_sit": situational.defense_situational(pbp_w),
    }
    inj_map, inj_week = injuries.build(
        loaders.load_injuries(), loaders.load_snaps(), loaders.load_rosters(),
        config.CURRENT_SEASON)
    extras["injuries"] = inj_map
    extras["injury_week"] = inj_week
    return off, deff, blitz, live, schedule, extras


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
        "Free sources (SumerSports, StatRankings) load automatically. "
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
        "Data: nflverse + FTN charting (free). Coverage scheme: blended from "
        "PFF + SumerSports + StatRankings."
    )


def main() -> None:
    try:
        off, deff, blitz, live, schedule, extras = build_frames()
    except Exception as exc:  # noqa: BLE001
        st.error("Couldn't load NFL data. Are you online? See console for details.")
        st.exception(exc)
        return

    sidebar(live)

    tab_data, tab_league, tab_matchups, tab_betting, tab_picks = st.tabs(
        ["📊 Team Data", "📋 League", "⚔️ Matchups", "💰 Betting", "🎯 Picks of the Week"]
    )
    with tab_data:
        team_tendencies.render(off, deff, blitz, extras)
    with tab_league:
        league.render(off, deff, blitz, extras)
    with tab_matchups:
        matchups.render(off, deff, blitz, schedule, extras)
    with tab_betting:
        betting.render(off, deff, schedule, extras)
    with tab_picks:
        picks.render(off, deff, schedule, extras)


if __name__ == "__main__":
    main()
