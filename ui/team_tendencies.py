"""The 'Team Data' tab: a full tendency profile for any team, plus league tables."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import tendencies
from data.providers import load_coverage
from ui.components import fmt, rank_badge_html


def _per_source_expander(scheme_row) -> None:
    """Show each source's zone/man behind the blended consensus."""
    rows = []
    for label in scheme_row.index:
        if label.startswith("zone_"):
            key = label[len("zone_"):]
            rows.append({
                "Source": key,
                "Zone": fmt(scheme_row.get(f"zone_{key}"), "pct"),
                "Man": fmt(scheme_row.get(f"man_{key}"), "pct"),
            })
    if not rows:
        return
    with st.expander("How the sources compare"):
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        spread = scheme_row.get("zone_spread")
        if pd.notna(spread):
            st.caption(f"Sources disagree by {fmt(spread, 'pct')} on zone rate.")


def _profile_columns(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
                     team: str, scheme_row) -> None:
    ocol, dcol = st.columns(2)

    with ocol:
        st.markdown("#### 🏈 Offense")
        if team in off.index:
            o = off.loc[team]
            st.markdown(
                rank_badge_html("Points per play (EPA)", fmt(o["epa_play"], "epa"), o["epa_play_rank"])
                + rank_badge_html("Passing points/play", fmt(o["pass_epa"], "epa"), o["pass_epa_rank"])
                + rank_badge_html("Rushing points/play", fmt(o["rush_epa"], "epa"), o["rush_epa_rank"])
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
                rank_badge_html("Points/play allowed (EPA)", fmt(d["epa_play"], "epa"), d["epa_play_rank"])
                + rank_badge_html("Passing pts allowed", fmt(d["pass_epa"], "epa"), d["pass_epa_rank"])
                + rank_badge_html("Rushing pts allowed", fmt(d["rush_epa"], "epa"), d["rush_epa_rank"])
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
                conf = scheme_row.get("confidence", "—")
                srcs = scheme_row.get("sources", "")
                st.caption(
                    f"**Coverage (blended):** zone {fmt(scheme_row['zone_rate'], 'pct')} · "
                    f"man {fmt(scheme_row['man_rate'], 'pct')}  ·  "
                    f"confidence **{conf}**"
                    + (f"  ·  _{srcs}_" if srcs else "")
                )
                _per_source_expander(scheme_row)
            else:
                st.caption(
                    "**Coverage (zone/man):** _no source connected yet_ 🔒  \n"
                    "Add a PFF export to `scheme_data/` or enable the free scrapers."
                )
        else:
            st.info("No defensive data for this team yet.")


_EPA_HELP = (
    "Expected Points Added per play — the average point value of a play. "
    "0 is league-average; elite offenses run about +0.10 to +0.20, the worst "
    "around −0.15. It rewards moving the chains and scoring, not just raw yards."
)


def _glossary() -> None:
    with st.expander("📖 What do these numbers mean?"):
        st.markdown(
            "- **Points/play (EPA)** — *Expected Points Added* per play. The single "
            "best measure of efficiency: how many points, on average, each play is "
            "worth. **0 = league average**, elite offenses ≈ **+0.10 to +0.20**, "
            "bad ones ≈ **−0.15**. For a defense it's *points allowed per play*, so "
            "**lower is better**.\n"
            "- **Success rate** — the share of plays that stayed 'on schedule' "
            "(gained positive EPA). Consistency, shown as a **%**.\n"
            "- **Explosive %** — share of plays that went for big gains "
            "(15+ passing / 10+ rushing yards).\n"
            "- **Run/Pass lean** — how a team plays in neutral situations (not "
            "trailing or protecting a lead): pass-heavy, balanced, run-heavy.\n"
            "- **Coverage** — how a defense plays the back end: **zone-heavy** vs "
            "**man-heavy**, blended from multiple sources.\n"
            "- **Strength / struggle** — where a unit is notably good or bad "
            "(top-8 / bottom-8 in the league) at passing vs. running the ball."
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
    st.dataframe(
        d, width="stretch",
        column_config={
            "epa_play_rank": st.column_config.NumberColumn("Rank", format="%d",
                help="League rank by overall efficiency (1 = best)."),
            "epa_play": st.column_config.NumberColumn("Points/play", format="%+.2f", help=_EPA_HELP),
            "pass_epa": st.column_config.NumberColumn("Pass pts/play", format="%+.2f",
                help="Points added per play when passing (passing EPA)."),
            "rush_epa": st.column_config.NumberColumn("Rush pts/play", format="%+.2f",
                help="Points added per play when running (rushing EPA)."),
            "pass_sr": st.column_config.NumberColumn("Pass success", format="%.1f%%",
                help="Share of pass plays that were successful (positive EPA)."),
            "rush_sr": st.column_config.NumberColumn("Rush success", format="%.1f%%",
                help="Share of run plays that were successful."),
            "explosive_rate": st.column_config.NumberColumn("Explosive", format="%.1f%%",
                help="Share of plays gaining 15+ pass / 10+ rush yards."),
        },
    )


def _defense_table(deff: pd.DataFrame, scheme_df: pd.DataFrame | None) -> None:
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
    st.dataframe(
        d, width="stretch",
        column_config={
            "epa_play_rank": st.column_config.NumberColumn("Rank", format="%d",
                help="League rank by defensive efficiency (1 = best defense)."),
            "epa_play": st.column_config.NumberColumn("Points/play allowed", format="%+.2f",
                help=_EPA_HELP + " Lower (more negative) is a better defense."),
            "pass_epa": st.column_config.NumberColumn("Pass pts allowed", format="%+.2f",
                help="Points allowed per play through the air (lower is better)."),
            "rush_epa": st.column_config.NumberColumn("Rush pts allowed", format="%+.2f",
                help="Points allowed per play on the ground (lower is better)."),
            "pass_sr": st.column_config.NumberColumn("Pass success allowed", format="%.1f%%",
                help="Share of opponent pass plays that succeeded (lower is better)."),
            "rush_sr": st.column_config.NumberColumn("Rush success allowed", format="%.1f%%",
                help="Share of opponent run plays that succeeded (lower is better)."),
            "explosive_rate": st.column_config.NumberColumn("Explosive allowed", format="%.1f%%",
                help="Share of opponent plays that went for big gains (lower is better)."),
        },
    )


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame) -> None:
    st.subheader("Team Data & Tendencies")

    if off.empty and deff.empty:
        st.warning("No play-by-play data available yet. Check back once games are played.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    team = st.selectbox("Team", teams, index=0)

    # Coverage scheme — blended across all connected sources. An uploaded PFF
    # export (sidebar) is threaded in so it joins the blend on hosted apps.
    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
    scheme_row = None
    if scheme_df is not None and team in scheme_df.index:
        scheme_row = scheme_df.loc[team]

    _profile_columns(off, deff, blitz, team, scheme_row)

    st.divider()
    st.markdown("### League tables")
    _glossary()
    view = st.radio("Show", ["Offense", "Defense", "Blitz / scheme"], horizontal=True)

    if view == "Offense" and not off.empty:
        _offense_table(off)
    elif view == "Defense" and not deff.empty:
        _defense_table(deff, scheme_df)
    else:
        if blitz.empty:
            st.info("Blitz data (FTN charting) not available for the loaded seasons.")
        else:
            st.dataframe(blitz.sort_values("blitz_rate", ascending=False),
                         width='stretch')
        if scheme_df is not None:
            st.markdown("#### Coverage scheme (blended)")
            show = ["zone_rate", "man_rate", "confidence", "n_sources", "sources"]
            show = [c for c in show if c in scheme_df.columns]
            st.dataframe(
                scheme_df[show].sort_values("zone_rate", ascending=False),
                width="stretch",
            )
            st.caption(
                "Zone/man are trust-weighted blends of every connected source. "
                "**Confidence** reflects how tightly the sources agree."
            )
        else:
            st.caption(
                "🔒 Zone/man coverage appears here once a source is connected — "
                "drop a PFF export in `scheme_data/` or enable the free scrapers."
            )
