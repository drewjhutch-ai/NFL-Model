"""The 'Picks of the Week' tab.

Two halves:
  * **Auto-surfaced leans** — the week's biggest unit + positional mismatches,
    ranked, so the model points you at the strongest spots.
  * **Your pick log** — record your own game/player picks with reasoning and
    export them; a running record to hold yourself accountable.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import edges, loaders


def _auto_leans(off, deff, schedule, extras) -> None:
    st.markdown("### 🔎 Model leans — biggest edges this week")
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded, so weekly leans aren't available. "
                "Use the Matchups tab to compare any two teams.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    idx = weeks.index(default_wk) if default_wk in weeks else 0
    wk = st.selectbox(f"Week ({season})", weeks, index=idx, key="picks_week")
    games = s[s["week"] == wk]

    leans = edges.week_leans(games, off, deff, extras)
    if leans.empty:
        st.info("No standout edges for this week yet (early-season / offseason data).")
        return
    show = leans[["Game", "Edge", "Detail"]].copy()
    show.insert(0, "#", range(1, len(show) + 1))
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption(
        "Edges rank offense-side mismatches (featured unit vs. a soft opponent). "
        "A starting point for your own read — not a guarantee."
    )


def _pick_log() -> None:
    st.markdown("### 📝 Your picks")
    if "picks" not in st.session_state:
        st.session_state["picks"] = []

    with st.form("add_pick", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        game = c1.text_input("Game / player", placeholder="e.g. KC @ BUF — Kelce over 60.5 yds")
        pick = c2.text_input("Your pick", placeholder="e.g. Kelce OVER")
        conf = c3.selectbox("Confidence", ["★", "★★", "★★★"], index=1)
        notes = st.text_input("Why (optional)", placeholder="e.g. BUF soft vs TE, KC pass-heavy")
        if st.form_submit_button("Add pick") and (game or pick):
            st.session_state["picks"].append(
                {"Game/Player": game, "Pick": pick, "Confidence": conf, "Notes": notes}
            )

    picks = st.session_state["picks"]
    if not picks:
        st.caption("No picks logged yet. Add one above.")
        return
    df = pd.DataFrame(picks)
    st.dataframe(df, width="stretch", hide_index=True)
    c1, c2 = st.columns([1, 5])
    c1.download_button("⬇️ Export CSV", df.to_csv(index=False).encode(),
                       file_name="my_picks.csv", mime="text/csv")
    if c2.button("Clear all picks"):
        st.session_state["picks"] = []
        st.rerun()
    st.caption("Picks are saved for this session. Export to keep them.")


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Picks of the Week")
    if off.empty or deff.empty:
        st.info("Load data first (needs offensive & defensive numbers).")
        return
    _auto_leans(off, deff, schedule, extras)
    st.divider()
    _pick_log()
