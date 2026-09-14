"""Global week control — one selector the whole app follows.

The current week is auto-detected from the schedule (the earliest week with an
unplayed game), so the app opens on the right week with no clicks. A single
sidebar selector then lets you look ahead or back; every tab reads that one
choice via :func:`selected`, so the week is set once for the whole app instead
of on every tab.
"""
from __future__ import annotations

import streamlit as st

import config
from data import loaders

_KEY = "global_week"


def weeks_for(schedule, season: int | None = None) -> list[int]:
    """Sorted list of weeks the season's schedule knows about (empty if none)."""
    season = season or config.CURRENT_SEASON
    if schedule is None or getattr(schedule, "empty", True):
        return []
    s = schedule[schedule["season"] == season]
    if s.empty:
        return []
    return sorted(int(w) for w in s["week"].unique())


def _reset_to(week: int) -> None:
    # Runs as a widget callback, before the selectbox is re-instantiated this
    # rerun, so assigning the widget-backed key here is the sanctioned pattern.
    st.session_state[_KEY] = week


def render_picker(schedule, season: int | None = None) -> int | None:
    """Render the one global week selector in the sidebar; return the chosen week.

    Seeds to the auto-detected current week on first load (and re-seeds if a stale
    value is no longer a valid week). Call once, from ``app.py``.
    """
    season = season or config.CURRENT_SEASON
    weeks = weeks_for(schedule, season)
    if not weeks:
        return None
    default = loaders.current_week(schedule, season) or weeks[0]
    if st.session_state.get(_KEY) not in weeks:   # seed / heal a stale value
        st.session_state[_KEY] = default

    st.sidebar.divider()
    st.sidebar.selectbox(
        f"Week · {season}", weeks, key=_KEY,
        help="Auto-set to the current week. Change it once and every tab follows.",
    )
    cur = loaders.current_week(schedule, season)
    if cur in weeks and st.session_state[_KEY] != cur:
        st.sidebar.button("↩ Back to current week", on_click=_reset_to, args=(cur,))
    return st.session_state[_KEY]


def selected(schedule, season: int | None = None) -> int | None:
    """The week the tabs should render: the global choice, else the auto default.

    Safe to call before :func:`render_picker` (falls back to the current week),
    so a tab never has to know whether the sidebar has drawn yet.
    """
    season = season or config.CURRENT_SEASON
    weeks = weeks_for(schedule, season)
    wk = st.session_state.get(_KEY)
    if wk in weeks:
        return wk
    return loaders.current_week(schedule, season) or (weeks[0] if weeks else None)
