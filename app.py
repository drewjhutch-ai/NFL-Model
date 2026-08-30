"""NFL model dashboard — Streamlit entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from data import loaders, pipeline
from ui import (betting, gamebets, league, matchups, picks, team_tendencies,
                touchdowns)
from ui import players as ui_players

st.set_page_config(page_title="NFL Model", page_icon="◆", layout="wide")


def _inject_css() -> None:
    """Global visual system — clean, dark, cutting-edge. Cosmetic only."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');
        :root{ --accent:#2dd4bf; --line:#1e2732; --muted:#8b98a5; --surf:#141b23; }
        html, body, .stApp, .stMarkdown, [class*="css"]{
            font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif; }
        .block-container{ padding-top:2.4rem; padding-bottom:3rem; max-width:1300px; }
        h1,h2,h3,h4{ font-weight:700; letter-spacing:-0.02em; }
        h1{ font-size:1.85rem; } h2{ font-size:1.35rem; }
        h3{ font-size:1.1rem; }
        /* section headers get a quiet accent tick */
        .stMarkdown h3{ border-left:3px solid var(--accent); padding-left:11px;
            margin:0.5rem 0 0.7rem; }
        [data-testid="stCaptionContainer"]{ color:var(--muted) !important; }
        /* tabs → clean segmented bar */
        div[data-baseweb="tab-list"]{ gap:4px; border-bottom:1px solid var(--line); }
        button[data-baseweb="tab"]{ font-weight:600; font-size:0.92rem; color:var(--muted);
            padding:9px 16px; }
        button[data-baseweb="tab"][aria-selected="true"]{ color:#fff; }
        div[data-baseweb="tab-highlight"]{ background-color:var(--accent); }
        /* metrics → KPI tiles */
        div[data-testid="stMetric"]{ background:var(--surf); border:1px solid var(--line);
            border-radius:12px; padding:12px 15px; }
        div[data-testid="stMetricLabel"] p{ color:var(--muted); font-size:0.8rem; }
        div[data-testid="stMetricValue"]{ font-weight:700; letter-spacing:-0.01em; }
        /* buttons */
        .stButton>button{ border-radius:10px; border:1px solid var(--line); font-weight:600; }
        .stButton>button:hover{ border-color:var(--accent); color:var(--accent); }
        /* dataframes + bordered containers + expanders */
        [data-testid="stDataFrame"]{ border:1px solid var(--line); border-radius:12px; }
        div[data-testid="stVerticalBlockBorderWrapper"]{ border-color:var(--line) !important;
            border-radius:14px; }
        div[data-testid="stExpander"]{ border:1px solid var(--line) !important;
            border-radius:12px !important; }
        hr{ border-color:var(--line); margin:1rem 0; }
        /* inputs / selects / sliders */
        div[data-baseweb="select"]>div, .stNumberInput input, .stTextInput input{
            border-radius:9px !important; border-color:var(--line) !important;
            background:var(--surf) !important; }
        div[data-baseweb="select"]>div:focus-within{ border-color:var(--accent) !important; }
        div[data-testid="stSlider"] [role="slider"]{ background:var(--accent) !important; }
        label p{ color:var(--muted) !important; font-size:0.82rem !important; }
        /* sidebar */
        section[data-testid="stSidebar"]{ border-right:1px solid var(--line); }
        code{ font-family:'IBM Plex Mono',ui-monospace,monospace; }
        /* brand header */
        .brand{ display:flex; align-items:baseline; gap:12px; margin:0 0 6px;
            padding-bottom:12px; border-bottom:1px solid var(--line); }
        .brand b{ font-size:1.15rem; font-weight:800; letter-spacing:0.14em; }
        .brand .accent{ color:var(--accent); }
        .brand span{ color:var(--muted); font-size:0.8rem; letter-spacing:0.02em; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60 * 60, show_spinner="Crunching tendencies…")
def build_frames():
    """Load, weight, and aggregate everything the tabs need. Cached as a unit.

    The heavy lifting lives in ``data.pipeline`` so the weekly snapshot Action
    can reuse the exact same code path outside Streamlit.
    """
    return pipeline.build_frames()


def sidebar(live: bool) -> None:
    st.sidebar.title("NFL Model")
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
    if st.sidebar.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown("### Coverage (zone/man)")
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
        col_a.success("PFF export loaded")
        if col_b.button("Clear", key="pff_clear"):
            st.session_state.pop("pff_bytes", None)
            st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(
        "Data: nflverse + FTN charting (free). Coverage scheme: weekly "
        "auto-fetch blended with PFF + SumerSports + StatRankings."
    )


def main() -> None:
    _inject_css()
    try:
        off, deff, blitz, live, schedule, extras = build_frames()
    except Exception as exc:  # noqa: BLE001
        st.error("Couldn't load NFL data. Are you online? See console for details.")
        st.exception(exc)
        return

    sidebar(live)

    st.markdown(
        "<div class='brand'><b><span class='accent'>◆</span> NFL MODEL</b>"
        "<span>analytics · projections · betting edge</span></div>",
        unsafe_allow_html=True)

    (tab_data, tab_league, tab_matchups, tab_players, tab_td, tab_gamebets,
     tab_betting, tab_picks) = st.tabs(
        ["Team Data", "League", "Matchups", "Players", "Touchdowns",
         "Game Bets", "Betting", "Picks of the Week"])
    with tab_data:
        team_tendencies.render(off, deff, blitz, extras)
    with tab_league:
        league.render(off, deff, blitz, extras)
    with tab_matchups:
        matchups.render(off, deff, blitz, schedule, extras)
    with tab_players:
        ui_players.render(off, deff, schedule, extras)
    with tab_td:
        touchdowns.render(off, deff, blitz, schedule, extras)
    with tab_gamebets:
        gamebets.render(off, deff, blitz, schedule, extras)
    with tab_betting:
        betting.render(off, deff, schedule, extras)
    with tab_picks:
        picks.render(off, deff, schedule, extras)


if __name__ == "__main__":
    main()
