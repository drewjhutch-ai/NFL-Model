"""The 'Picks of the Week' tab.

Placeholder for now. Once the 2026 season is live and the tendency/matchup data
is flowing, this becomes the home for weekly game picks and player-prop picks --
either surfaced automatically from the edge logic in ``matchups`` or logged by
hand as you make them. Building this out is the next milestone.
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.subheader("Picks of the Week")
    st.info(
        "🚧 Coming next. This tab will hold weekly **game picks** and **player-prop "
        "picks**, driven by the matchup edges and (once connected) the coverage/"
        "blitz scheme data. We'll build it out once the foundation is settled and "
        "the 2026 season data starts flowing."
    )
    st.markdown(
        "- Auto-suggested edges from the Matchups tab (biggest rank mismatches)\n"
        "- A place to log your own game & player picks with reasoning\n"
        "- Track record over the season (record, ROI, hit rate)"
    )
