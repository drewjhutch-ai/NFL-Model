"""NFL model dashboard — Streamlit entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from data import loaders, pipeline
from ui import (betting, clv, gamebets, home, injuries, kit, league, longodds,
                matchups, picks, team_tendencies, touchdowns)
from ui import players as ui_players

st.set_page_config(page_title="NFL Model", page_icon="◆", layout="wide")


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
    st.sidebar.markdown("### Live odds")
    from data import odds_providers as _op
    if _op.get_odds_provider().is_available():
        st.sidebar.success("The Odds API key detected ✓")
        st.sidebar.caption("Live multi-book odds, line shopping, the sharp tracker, "
                           "CLV and prop lines are active.")
    else:
        st.sidebar.info("No odds key — using the schedule's lines.")
        st.sidebar.caption("Add **ODDS_API_KEY** in Streamlit Secrets (from the-odds-api.com) "
                           "to unlock live odds, line movement, CLV, and prop lines.")

    st.sidebar.divider()
    st.sidebar.caption(
        "Data: nflverse + FTN charting (free). Coverage scheme: weekly "
        "auto-fetch blended with PFF + SumerSports + StatRankings."
    )


def _safe(render_fn, *args) -> None:
    """Render one tab in isolation — a failure shows in that tab, never crashes
    the whole app (an exception used to blank every tab)."""
    try:
        render_fn(*args)
    except Exception as exc:  # noqa: BLE001
        st.error(f"This tab hit an error: {type(exc).__name__}. The rest of the app is unaffected.")
        with st.expander("Details"):
            st.exception(exc)


def _week_label(schedule, live: bool) -> str:
    season = config.CURRENT_SEASON
    if live and schedule is not None and not schedule.empty:
        wk = loaders.current_week(schedule, season)
        if wk:
            return f"Week {int(wk)} · {season}"
    return f"{season} · offseason"


def main() -> None:
    kit.inject()
    try:
        off, deff, blitz, live, schedule, extras = build_frames()
    except Exception as exc:  # noqa: BLE001
        st.error("Couldn't load NFL data. Are you online? See console for details.")
        st.exception(exc)
        return

    sidebar(live)

    week_txt = _week_label(schedule, live)
    st.markdown(kit.brand_header(week_txt, live), unsafe_allow_html=True)

    # A session-state nav (not st.tabs) so cross-page links work: a card on the
    # Home page can set st.session_state["_nav_to"] + a target and rerun, landing
    # the user on the right section, pre-selected. Styled as a tab strip in kit.
    sections = ["This Week", "Team Data", "League", "Matchups", "Players",
                "Touchdowns", "Game Bets", "Betting", "Picks of the Week",
                "Long Odds", "CLV", "Injuries"]
    jump = st.session_state.pop("_nav_to", None)
    if jump in sections:
        st.session_state["nav"] = jump
    st.session_state.setdefault("nav", "This Week")
    nav = st.radio("Section", sections, key="nav", horizontal=True,
                   label_visibility="collapsed")

    if nav == "This Week":
        _safe(home.render, off, deff, schedule, extras, live)
    elif nav == "Team Data":
        _safe(team_tendencies.render, off, deff, blitz, extras)
    elif nav == "League":
        _safe(league.render, off, deff, blitz, extras)
    elif nav == "Matchups":
        _safe(matchups.render, off, deff, blitz, schedule, extras)
    elif nav == "Players":
        _safe(ui_players.render, off, deff, schedule, extras)
    elif nav == "Touchdowns":
        _safe(touchdowns.render, off, deff, blitz, schedule, extras)
    elif nav == "Game Bets":
        _safe(gamebets.render, off, deff, blitz, schedule, extras)
    elif nav == "Betting":
        _safe(betting.render, off, deff, schedule, extras)
    elif nav == "Picks of the Week":
        _safe(picks.render, off, deff, schedule, extras)
    elif nav == "Long Odds":
        _safe(longodds.render, off, deff, schedule, extras)
    elif nav == "CLV":
        _safe(clv.render, off, deff, schedule, extras)
    elif nav == "Injuries":
        _safe(injuries.render, off, deff, schedule, extras)


if __name__ == "__main__":
    main()
