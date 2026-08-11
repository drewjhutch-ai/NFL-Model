"""The 'Team Data' tab: a visual, chart-driven scouting profile per team.

Pick a team and get percentile charts for offense and defense (all metrics
visible at once), an analytical run/pass identity, split Strengths vs Struggles
(broad headline + the ultra-specific chink), and the contextual notes — QB
mobility, ground game, pass rush, blitz, coverage, and blitz vulnerability.
League-wide tables live on their own tab.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import pressure, profiles, rushing, tendencies
from data.providers import load_coverage
from ui.components import fmt, gauge_bar_html, ordinal, percentile_chart


def _per_source_expander(scheme_row) -> None:
    rows = []
    for label in scheme_row.index:
        if label.startswith("zone_"):
            key = label[len("zone_"):]
            rows.append({"Source": key,
                         "Zone": fmt(scheme_row.get(f"zone_{key}"), "pct"),
                         "Man": fmt(scheme_row.get(f"man_{key}"), "pct")})
    if not rows:
        return
    with st.expander("How the coverage sources compare"):
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _strengths_struggles(facets: list[dict]) -> None:
    strengths, struggles = profiles.strengths_and_struggles(facets)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**💪 Strengths**")
        if strengths:
            for f in strengths:
                st.markdown("- " + profiles.facet_line(f))
        else:
            st.caption("No top-12 strengths — a middling unit.")
    with c2:
        st.markdown("**🩹 Struggles**")
        if struggles:
            for f in struggles:
                st.markdown("- " + profiles.facet_line(f))
        else:
            st.caption("No bottom-12 weaknesses — few glaring holes.")


def _offense_section(off: pd.DataFrame, team: str, extras: dict) -> None:
    o = off.loc[team]
    st.markdown(f"## 🏈 {team} Offense")
    cc, cn = st.columns([3, 2])
    with cc:
        rows = [
            ("Overall (EPA/play)", fmt(o["epa_play"], "epa"), o["epa_play_rank"]),
            ("Passing", fmt(o["pass_epa"], "epa"), o["pass_epa_rank"]),
            ("Rushing", fmt(o["rush_epa"], "epa"), o["rush_epa_rank"]),
            ("Pass success", fmt(o["pass_sr"], "pct"), o["pass_sr_rank"]),
            ("Rush success", fmt(o["rush_sr"], "pct"), o["rush_sr_rank"]),
            ("Explosive", fmt(o["explosive_rate"], "pct"), o["explosive_rate_rank"]),
        ]
        st.plotly_chart(percentile_chart(rows, "Offense percentiles"),
                        use_container_width=True)
    with cn:
        pi = profiles.pass_identity(team, off)
        st.markdown("**Run / Pass identity**")
        st.markdown(gauge_bar_html(pi["npr_pct"]), unsafe_allow_html=True)
        pct_txt = f"{pi['npr_pct']:.0f}th pct" if pd.notna(pi["npr_pct"]) else "—"
        st.caption(
            f"**{pi['base']}** · neutral pass {fmt(pi['neutral_pass_rate'], 'pct')} "
            f"({pct_txt}) · PROE {fmt(pi['proe'], 'num1')} — {pi['tendency']}"
        )
        qb = extras.get("qb")
        if qb is not None and not qb.empty and team in qb.index:
            q = qb.loc[team]
            st.caption(f"**QB:** {pressure.qb_label(q['qb_rush_rate'])} "
                       f"({fmt(q['qb_rush_rate'], 'pct')} rush rate)")
        rush = extras.get("rush")
        if rush is not None and not rush.empty and team in rush.index:
            r = rush.loc[team]
            st.caption(f"**Ground game:** {rushing.rushing_label(r.get('ryoe_rank'))} "
                       f"({r.get('ryoe_per_att', float('nan')):+.2f} yds over exp/att)")
        ovb = extras.get("ovb")
        if ovb is not None and not ovb.empty and team in ovb.index:
            b = ovb.loc[team]
            st.caption(
                f"**vs Blitz:** {pressure.blitz_resilience_label(b['blitz_delta'])} — "
                f"{fmt(b['epa_vs_blitz'], 'epa')} EPA blitzed vs "
                f"{fmt(b['epa_no_blitz'], 'epa')} not (faced {fmt(b['blitz_faced_rate'], 'pct')})"
            )
        st.caption("**vs coverage schemes:** _upload PFF to unlock man/zone splits_ 🔒")
    _strengths_struggles(profiles.offense_facets(team, off, extras))


def _defense_section(deff: pd.DataFrame, blitz: pd.DataFrame, team: str,
                     extras: dict, scheme_row) -> None:
    d = deff.loc[team]
    st.markdown(f"## 🛡️ {team} Defense")
    cc, cn = st.columns([3, 2])
    with cc:
        rows = [
            ("Overall allowed", fmt(d["epa_play"], "epa"), d["epa_play_rank"]),
            ("Pass D", fmt(d["pass_epa"], "epa"), d["pass_epa_rank"]),
            ("Run D", fmt(d["rush_epa"], "epa"), d["rush_epa_rank"]),
            ("Pass success allowed", fmt(d["pass_sr"], "pct"), d["pass_sr_rank"]),
            ("Rush success allowed", fmt(d["rush_sr"], "pct"), d["rush_sr_rank"]),
            ("Explosive allowed", fmt(d["explosive_rate"], "pct"), d["explosive_rate_rank"]),
        ]
        st.plotly_chart(percentile_chart(rows, "Defense percentiles (100 = stingiest)"),
                        use_container_width=True)
    with cn:
        prs = extras.get("pressure")
        if prs is not None and not prs.empty and team in prs.index:
            p = prs.loc[team]
            st.caption(
                f"**Pass rush:** {pressure.pressure_label(p['pressure_rate_rank'])} — "
                f"pressure {fmt(p['pressure_rate'], 'pct')} ({ordinal(p['pressure_rate_rank'])}), "
                f"sacks {fmt(p['sack_rate'], 'pct')}"
            )
        if not blitz.empty and team in blitz.index:
            b = blitz.loc[team]
            st.caption(f"**Blitz:** {fmt(b['blitz_rate'], 'pct')} of dropbacks "
                       f"({tendencies.blitz_label(b['blitz_rate'])})")
        else:
            st.caption("**Blitz:** FTN charting not loaded for these seasons.")
        if scheme_row is not None:
            st.caption(
                f"**Coverage:** zone {fmt(scheme_row['zone_rate'], 'pct')} · "
                f"man {fmt(scheme_row['man_rate'], 'pct')} · "
                f"confidence **{scheme_row.get('confidence', '—')}**"
            )
            _per_source_expander(scheme_row)
        else:
            st.caption("**Coverage (zone/man):** _no source connected_ 🔒")
        st.caption("_Upload PFF (sidebar) to add Cover 0–6 shells & situational man/zone._")
    _strengths_struggles(profiles.defense_facets(team, deff, extras))


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    extras = extras or {}
    st.subheader("Team Data & Tendencies")
    if off.empty and deff.empty:
        st.warning("No play-by-play data yet. Check back once games are played.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    team = st.selectbox("Team", teams, index=0)

    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
    scheme_row = None
    if scheme_df is not None and team in scheme_df.index:
        scheme_row = scheme_df.loc[team]

    if team in off.index:
        _offense_section(off, team, extras)
    st.divider()
    if team in deff.index:
        _defense_section(deff, blitz, team, extras, scheme_row)
