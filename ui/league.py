"""The 'League' tab: sortable league-wide tables (moved out of Team Data).

Percent-formatted, plain-language columns with hover tooltips, plus the
descriptive Run/Pass lean, Strength/Struggle, and Coverage columns.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import tendencies
from data.providers import load_coverage

_EPA_HELP = (
    "Expected Points Added per play — the average point value of a play. "
    "0 is league-average; elite offenses run about +0.10 to +0.20, the worst "
    "around −0.15. Rewards moving the chains and scoring, not just raw yards."
)


def _glossary() -> None:
    with st.expander("📖 What do these numbers mean?"):
        st.markdown(
            "- **Points/play (EPA)** — *Expected Points Added* per play. **0 = "
            "average**, elite offenses ≈ **+0.10 to +0.20**. For a defense it's "
            "points *allowed* per play, so **lower is better**.\n"
            "- **Success rate** — share of plays that stayed on schedule "
            "(positive EPA), shown as a **%**.\n"
            "- **Explosive %** — share of plays for big gains (15+ pass / 10+ rush).\n"
            "- **Run/Pass lean** — how a team plays in neutral situations.\n"
            "- **Coverage** — zone-heavy vs man-heavy, blended from sources.\n"
            "- **Strength / struggle** — where a unit is top-8 / bottom-8."
        )


def _offense_table(off: pd.DataFrame) -> None:
    d = off.copy()
    d["Run/Pass lean"] = d["neutral_pass_rate"].map(tendencies.style_label)
    d["Strength / struggle"] = [
        tendencies.unit_summary(r.pass_epa_rank, r.rush_epa_rank) for r in d.itertuples()
    ]
    for c in ("pass_sr", "rush_sr", "explosive_rate"):
        if c in d.columns:
            d[c] = d[c] * 100
    order = ["epa_play_rank", "epa_play", "pass_epa", "rush_epa", "pass_sr",
             "rush_sr", "explosive_rate", "Run/Pass lean", "Strength / struggle"]
    d = d[[c for c in order if c in d.columns]].sort_values("epa_play_rank")
    st.dataframe(d, width="stretch", column_config={
        "epa_play_rank": st.column_config.NumberColumn("Rank", format="%d",
            help="League rank by overall efficiency (1 = best)."),
        "epa_play": st.column_config.NumberColumn("Points/play", format="%+.2f", help=_EPA_HELP),
        "pass_epa": st.column_config.NumberColumn("Pass pts/play", format="%+.2f",
            help="Points added per play when passing."),
        "rush_epa": st.column_config.NumberColumn("Rush pts/play", format="%+.2f",
            help="Points added per play when running."),
        "pass_sr": st.column_config.NumberColumn("Pass success", format="%.1f%%"),
        "rush_sr": st.column_config.NumberColumn("Rush success", format="%.1f%%"),
        "explosive_rate": st.column_config.NumberColumn("Explosive", format="%.1f%%"),
    })


def _defense_table(deff: pd.DataFrame, scheme_df) -> None:
    d = deff.copy()

    def _cov(team):
        if scheme_df is not None and team in scheme_df.index:
            return tendencies.coverage_label(scheme_df.loc[team, "zone_rate"])
        return "—"

    d["Coverage"] = [_cov(t) for t in d.index]
    d["Soft spot"] = [
        tendencies.unit_summary(r.pass_epa_rank, r.rush_epa_rank, defense=True)
        for r in d.itertuples()
    ]
    for c in ("pass_sr", "rush_sr", "explosive_rate"):
        if c in d.columns:
            d[c] = d[c] * 100
    order = ["epa_play_rank", "epa_play", "pass_epa", "rush_epa", "pass_sr",
             "rush_sr", "explosive_rate", "Coverage", "Soft spot"]
    d = d[[c for c in order if c in d.columns]].sort_values("epa_play_rank")
    st.dataframe(d, width="stretch", column_config={
        "epa_play_rank": st.column_config.NumberColumn("Rank", format="%d",
            help="League rank by defensive efficiency (1 = best defense)."),
        "epa_play": st.column_config.NumberColumn("Points/play allowed", format="%+.2f",
            help=_EPA_HELP + " Lower (more negative) is a better defense."),
        "pass_epa": st.column_config.NumberColumn("Pass pts allowed", format="%+.2f"),
        "rush_epa": st.column_config.NumberColumn("Rush pts allowed", format="%+.2f"),
        "pass_sr": st.column_config.NumberColumn("Pass success allowed", format="%.1f%%"),
        "rush_sr": st.column_config.NumberColumn("Rush success allowed", format="%.1f%%"),
        "explosive_rate": st.column_config.NumberColumn("Explosive allowed", format="%.1f%%"),
    })


def _blitz_scheme(blitz: pd.DataFrame, scheme_df) -> None:
    if not blitz.empty:
        b = blitz.copy()
        if "blitz_rate" in b.columns:
            b["blitz_rate"] = b["blitz_rate"] * 100
        st.markdown("#### Blitz rate (of dropbacks)")
        st.dataframe(b.sort_values("blitz_rate", ascending=False), width="stretch",
                     column_config={
                         "blitz_rate": st.column_config.NumberColumn("Blitz %", format="%.1f%%"),
                         "avg_box": st.column_config.NumberColumn("Avg box", format="%.2f"),
                         "blitz_rate_rank": st.column_config.NumberColumn("Rank", format="%d"),
                     })
    else:
        st.info("Blitz data (FTN charting) not available for the loaded seasons.")

    st.markdown("#### Coverage scheme (blended)")
    if scheme_df is not None:
        show = [c for c in ["zone_rate", "man_rate", "confidence", "n_sources", "sources"]
                if c in scheme_df.columns]
        sd = scheme_df[show].copy()
        for c in ("zone_rate", "man_rate"):
            if c in sd.columns:
                sd[c] = sd[c] * 100
        st.dataframe(sd.sort_values("zone_rate", ascending=False), width="stretch",
                     column_config={
                         "zone_rate": st.column_config.NumberColumn("Zone %", format="%.1f%%"),
                         "man_rate": st.column_config.NumberColumn("Man %", format="%.1f%%"),
                     })
        st.caption("Zone/man are trust-weighted blends of every connected source. "
                   "Upload PFF (sidebar) to add Cover 0–6 detail.")
    else:
        st.caption("🔒 Zone/man coverage appears here once a source is connected "
                   "(free scrapers or a PFF upload).")


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    st.subheader("League Tables")
    if off.empty and deff.empty:
        st.warning("No data loaded yet.")
        return
    _glossary()
    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
    view = st.radio("Show", ["Offense", "Defense", "Blitz / scheme"], horizontal=True)
    if view == "Offense" and not off.empty:
        _offense_table(off)
    elif view == "Defense" and not deff.empty:
        _defense_table(deff, scheme_df)
    else:
        _blitz_scheme(blitz, scheme_df)
