"""The 'Team Data' tab: a full tendency profile for any team, plus league tables."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import tendencies
from data.providers import SchemeUnavailable, get_provider
from ui.components import fmt, rank_badge_html


def _profile_columns(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
                     team: str, scheme_row) -> None:
    ocol, dcol = st.columns(2)

    with ocol:
        st.markdown("#### 🏈 Offense")
        if team in off.index:
            o = off.loc[team]
            st.markdown(
                rank_badge_html("Overall EPA / play", fmt(o["epa_play"], "epa"), o["epa_play_rank"])
                + rank_badge_html("Pass EPA / play", fmt(o["pass_epa"], "epa"), o["pass_epa_rank"])
                + rank_badge_html("Rush EPA / play", fmt(o["rush_epa"], "epa"), o["rush_epa_rank"])
                + rank_badge_html("Pass success rate", fmt(o["pass_sr"], "pct"), o["pass_sr_rank"])
                + rank_badge_html("Rush success rate", fmt(o["rush_sr"], "pct"), o["rush_sr_rank"])
                + rank_badge_html("Explosive-play rate", fmt(o["explosive_rate"], "pct"), o["explosive_rate_rank"]),
                unsafe_allow_html=True,
            )
            lean = tendencies.style_label(o["neutral_pass_rate"])
            st.caption(
                f"**Play-style lean:** {lean}  ·  "
                f"neutral pass rate {fmt(o['neutral_pass_rate'], 'pct')}  ·  "
                f"PROE {fmt(o['proe'], 'num1') if pd.notna(o['proe']) else '—'}"
            )
        else:
            st.info("No offensive data for this team yet.")

    with dcol:
        st.markdown("#### 🛡️ Defense")
        if team in deff.index:
            d = deff.loc[team]
            st.markdown(
                rank_badge_html("Overall EPA / play allowed", fmt(d["epa_play"], "epa"), d["epa_play_rank"])
                + rank_badge_html("Pass EPA / play allowed", fmt(d["pass_epa"], "epa"), d["pass_epa_rank"])
                + rank_badge_html("Rush EPA / play allowed", fmt(d["rush_epa"], "epa"), d["rush_epa_rank"])
                + rank_badge_html("Pass success allowed", fmt(d["pass_sr"], "pct"), d["pass_sr_rank"])
                + rank_badge_html("Rush success allowed", fmt(d["rush_sr"], "pct"), d["rush_sr_rank"])
                + rank_badge_html("Explosive allowed", fmt(d["explosive_rate"], "pct"), d["explosive_rate_rank"]),
                unsafe_allow_html=True,
            )
            # blitz + coverage scheme
            if not blitz.empty and team in blitz.index:
                b = blitz.loc[team]
                st.caption(
                    f"**Blitz tendency:** {tendencies.blitz_label(b['blitz_rate'])}  ·  "
                    f"blitz rate {fmt(b['blitz_rate'], 'pct')}"
                )
            else:
                st.caption("**Blitz tendency:** FTN charting not loaded for these seasons.")

            if scheme_row is not None:
                st.caption(
                    f"**Coverage:** zone {fmt(scheme_row['zone_rate'], 'pct')} · "
                    f"man {fmt(scheme_row['man_rate'], 'pct')}"
                )
            else:
                st.caption("**Coverage (zone/man):** _awaiting paid scheme feed_ 🔒")
        else:
            st.info("No defensive data for this team yet.")


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame) -> None:
    st.subheader("Team Data & Tendencies")

    if off.empty and deff.empty:
        st.warning("No play-by-play data available yet. Check back once games are played.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    team = st.selectbox("Team", teams, index=0)

    # Coverage scheme (paid) — optional.
    scheme_row = None
    provider = get_provider()
    scheme_df = None
    if provider.is_available():
        try:
            import config
            scheme_df = provider.coverage_tendencies(config.CURRENT_SEASON)
            if team in scheme_df.index:
                scheme_row = scheme_df.loc[team]
        except SchemeUnavailable:
            scheme_df = None

    _profile_columns(off, deff, blitz, team, scheme_row)

    st.divider()
    st.markdown("### League tables")
    view = st.radio("Show", ["Offense", "Defense", "Blitz / scheme"], horizontal=True)

    if view == "Offense" and not off.empty:
        cols = ["epa_play", "epa_play_rank", "pass_epa", "pass_epa_rank",
                "rush_epa", "rush_epa_rank", "neutral_pass_rate", "proe",
                "explosive_rate", "plays"]
        st.dataframe(off[[c for c in cols if c in off.columns]]
                     .sort_values("epa_play_rank"), width='stretch')
    elif view == "Defense" and not deff.empty:
        cols = ["epa_play", "epa_play_rank", "pass_epa", "pass_epa_rank",
                "rush_epa", "rush_epa_rank", "explosive_rate", "plays"]
        st.dataframe(deff[[c for c in cols if c in deff.columns]]
                     .sort_values("epa_play_rank"), width='stretch')
    else:
        if blitz.empty:
            st.info("Blitz data (FTN charting) not available for the loaded seasons.")
        else:
            st.dataframe(blitz.sort_values("blitz_rate", ascending=False),
                         width='stretch')
        if scheme_df is not None:
            st.markdown("#### Coverage scheme (paid feed)")
            st.dataframe(scheme_df, width='stretch')
        else:
            st.caption("🔒 Zone/man coverage rates appear here once your paid scheme feed is connected.")
