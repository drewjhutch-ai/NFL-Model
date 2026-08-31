"""The 'Team Data' tab: a visual, chart-driven scouting profile per team.

Two views:
  * **Overview** — the glance layer: a letter grade, an identity thesis, headline
    ranks with week-over-week movement and an EPA-trajectory sparkline, then the
    offense/defense percentile charts and the strengths/struggles read.
  * **Advanced** — the drill-in: situational splits (early/late down, script,
    home/away), NextGen tracking stats, radar compare, and the coverage feed.

League-wide tables live on their own tab.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import form as form_mod
from data import history, loaders, pressure, profiles, rushing, splits
from data.providers import load_coverage
from ui.components import (facet_html, fmt, gauge_bar_html, injury_card_html,
                           movement_arrow, ordinal, percentile_chart, radar_chart,
                           sparkline_fig, sw_card_html, unicode_spark)


def _pct(rank, total: int = 32) -> float:
    if rank is None or pd.isna(rank):
        return 0.0
    return (total - int(rank)) / (total - 1) * 100


def _radar_values(team, off, deff, extras, side: str) -> tuple[list, list]:
    if side == "offense" and team in off.index:
        o = off.loc[team]
        os_ = extras.get("off_sit"); dr = extras.get("drives_off")
        cats = ["Pass", "Rush", "Explosive", "Success", "3rd down", "Red zone", "Pts/drive"]
        vals = [_pct(o["pass_epa_rank"]), _pct(o["rush_epa_rank"]), _pct(o["explosive_rate_rank"]),
                _pct(o["pass_sr_rank"]),
                _pct(os_.loc[team, "third_rank"]) if os_ is not None and team in os_.index else 0,
                _pct(os_.loc[team, "rz_rank"]) if os_ is not None and team in os_.index else 0,
                _pct(dr.loc[team, "ppd_rank"]) if dr is not None and team in dr.index else 0]
        return cats, vals
    if side == "defense" and team in deff.index:
        d = deff.loc[team]
        prs = extras.get("pressure"); dr = extras.get("drives_def")
        cats = ["Pass D", "Run D", "Explosive", "Success", "Pass rush", "Pts/drive", "Turnovers"]
        to = extras.get("turnovers")
        vals = [_pct(d["pass_epa_rank"]), _pct(d["rush_epa_rank"]), _pct(d["explosive_rate_rank"]),
                _pct(d["pass_sr_rank"]),
                _pct(prs.loc[team, "pressure_rate_rank"]) if prs is not None and team in prs.index else 0,
                _pct(dr.loc[team, "ppd_rank"]) if dr is not None and team in dr.index else 0,
                _pct(to.loc[team, "margin_rank"]) if to is not None and team in to.index else 0]
        return cats, vals
    return [], []


def _compare_section(off, deff, extras, team, teams) -> None:
    st.markdown("### Radar & compare")
    others = [t for t in teams if t != team]
    cmp = st.selectbox("Compare with (optional)", ["— none —"] + others, key="cmp_team")
    meta = loaders.team_meta()
    c1, c2 = st.columns(2)
    for col, side in ((c1, "offense"), (c2, "defense")):
        cats, vals = _radar_values(team, off, deff, extras, side)
        if not cats:
            continue
        series = [(team, vals, meta.get(team, {}).get("color") or "#1f77b4")]
        if cmp != "— none —":
            c2cats, c2vals = _radar_values(cmp, off, deff, extras, side)
            if c2vals:
                series.append((cmp, c2vals, meta.get(cmp, {}).get("color") or "#e74c3c"))
        col.plotly_chart(radar_chart(cats, series, side.capitalize() + " (percentile)"),
                         width="stretch")
    st.caption("Further from center = better (league percentile). Overlay a second team to compare.")


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
    c1.markdown(sw_card_html("Strengths", [facet_html(f) for f in strengths], "strength"),
                unsafe_allow_html=True)
    c2.markdown(sw_card_html("Struggles", [facet_html(f) for f in struggles], "struggle"),
                unsafe_allow_html=True)


# --- grade + thesis header ---------------------------------------------------
def _metric_move(label, rank, delta, help_txt) -> str:
    arrow = movement_arrow(delta)
    move = f" {arrow}" if arrow else ""
    return (f"<div style='font-size:0.8rem;color:#8a8a8a;'>{label}</div>"
            f"<div style='font-size:1.5rem;font-weight:700;line-height:1.1;'>{ordinal(rank)}{move}</div>")


def _header(team: str, off: pd.DataFrame, deff: pd.DataFrame, extras: dict) -> None:
    meta = loaders.team_meta().get(team, {})
    color = meta.get("color") or "#1f77b4"
    from data import betting
    power = betting.power_ratings(off, deff)
    prank = int(power.loc[team, "power_rank"]) if team in power.index and pd.notna(power.loc[team, "power_rank"]) else None
    grade = profiles.team_grade(prank)
    thesis = profiles.team_thesis(team, off, deff, extras) if team in off.index else ""

    # week-over-week movement from persisted snapshots (empty until weeks accrue)
    hist = history.load_history(config.CURRENT_SEASON)
    mv = {k: history.rank_movement(hist, f"{k}_rank") for k in ("power", "off", "def")}

    c_logo, c_name, c_grade = st.columns([1, 7, 2])
    if meta.get("logo"):
        c_logo.image(meta["logo"], width=58)
    c_name.markdown(
        f"<div style='border-left:6px solid {color};padding:2px 0 2px 12px;'>"
        f"<h2 style='margin:0;'>{meta.get('name', team)}</h2>"
        f"<span style='color:#9aa0a6;font-size:0.9rem;'>{thesis}</span></div>",
        unsafe_allow_html=True)
    c_grade.markdown(
        f"<div style='text-align:center;border:1px solid {color};border-radius:12px;padding:4px;'>"
        f"<div style='font-size:0.65rem;letter-spacing:.14em;color:#8a8a8a;'>GRADE</div>"
        f"<div style='font-size:2rem;font-weight:800;line-height:1;color:{color};'>{grade}</div></div>",
        unsafe_allow_html=True)

    o = off.loc[team] if team in off.index else None
    d = deff.loc[team] if team in deff.index else None
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_metric_move("Offense", o["epa_play_rank"] if o is not None else None,
                             mv["off"].get(team), "Offensive EPA/play rank"), unsafe_allow_html=True)
    k2.markdown(_metric_move("Defense", d["epa_play_rank"] if d is not None else None,
                             mv["def"].get(team), "Defensive EPA/play rank"), unsafe_allow_html=True)
    pi = profiles.pass_identity(team, off) if team in off.index else None
    k3.markdown(f"<div style='font-size:0.8rem;color:#8a8a8a;'>Identity</div>"
                f"<div style='font-size:1.1rem;font-weight:600;margin-top:6px;'>{pi['base'] if pi else '—'}</div>",
                unsafe_allow_html=True)
    qb = extras.get("qb")
    qlab = qb.loc[team].get("qb_style", "—") if qb is not None and not qb.empty and team in qb.index else "—"
    k4.markdown(f"<div style='font-size:0.8rem;color:#8a8a8a;'>QB style</div>"
                f"<div style='font-size:1.1rem;font-weight:600;margin-top:6px;'>{qlab}</div>",
                unsafe_allow_html=True)

    # EPA-trajectory sparkline + recent form
    weekly = history.weekly_epa(extras.get("pbp"))
    net_series = history.spark_series(weekly, team, "net")
    fig = sparkline_fig(net_series, color=color, height=54)
    fm = extras.get("form")
    cs, cf = st.columns([1, 3])
    if fig is not None:
        cs.caption("Net EPA trajectory")
        cs.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    if fm is not None and not fm.empty and team in fm.index:
        f = fm.loc[team]
        oa = form_mod.arrow(f["off_delta"], good_high=True)
        da = form_mod.arrow(f["def_delta"], good_high=False)
        cf.caption(f"**Recent form** (last {int(f['games_in_window'])}): "
                   f"offense {oa} ({f['off_recent']:+.2f} vs {f['off_season']:+.2f} season) · "
                   f"defense {da} ({f['def_recent']:+.2f} allowed vs {f['def_season']:+.2f})")
    if not any(history.rank_movement(hist, "power_rank").to_dict()):
        cf.caption("↕ Week-over-week movement arrows appear once the season logs two weeks.")


# --- offense / defense sections (kept) ---------------------------------------
def _offense_section(off: pd.DataFrame, team: str, extras: dict) -> None:
    o = off.loc[team]
    st.markdown("### Offense")
    cc, cn = st.columns([3, 2])
    with cc:
        rows = [
            ("Overall (pts/100)", fmt(o["epa_play"], "epa"), o["epa_play_rank"]),
            ("Passing", fmt(o["pass_epa"], "epa"), o["pass_epa_rank"]),
            ("Rushing", fmt(o["rush_epa"], "epa"), o["rush_epa_rank"]),
            ("Pass success", fmt(o["pass_sr"], "pct"), o["pass_sr_rank"]),
            ("Rush success", fmt(o["rush_sr"], "pct"), o["rush_sr_rank"]),
            ("Explosive", fmt(o["explosive_rate"], "pct"), o["explosive_rate_rank"]),
        ]
        st.plotly_chart(percentile_chart(rows, "Offense percentiles"), width="stretch")
    with cn:
        with st.container(border=True):
            pi = profiles.pass_identity(team, off)
            st.markdown("**Run / Pass identity**")
            st.markdown(gauge_bar_html(pi["npr_pct"]), unsafe_allow_html=True)
            pct_txt = f"{pi['npr_pct']:.0f}th pct" if pd.notna(pi["npr_pct"]) else "—"
            st.caption(f"**{pi['base']}** · neutral pass {fmt(pi['neutral_pass_rate'], 'pct')} "
                       f"({pct_txt}) · PROE {fmt(pi['proe'], 'num1')} — {pi['tendency']}")
            qb = extras.get("qb")
            if qb is not None and not qb.empty and team in qb.index:
                q = qb.loc[team]
                st.caption(f"**QB:** {q.get('qb_style', '—')} ({fmt(q['qb_rush_rate'], 'pct')} rush rate)")
            rush = extras.get("rush")
            if rush is not None and not rush.empty and team in rush.index:
                r = rush.loc[team]
                st.caption(f"**Ground game:** {rushing.rushing_label(r.get('ryoe_rank'))} "
                           f"({r.get('ryoe_per_att', float('nan')):+.2f} yds over exp/att)")
            ovb = extras.get("ovb")
            if ovb is not None and not ovb.empty and team in ovb.index:
                b = ovb.loc[team]
                st.caption(f"**vs Blitz:** {b.get('resilience', '—')} — "
                           f"{fmt(b['epa_vs_blitz'], 'epa')} EPA blitzed vs {fmt(b['epa_no_blitz'], 'epa')} not")
            dro = extras.get("drives_off")
            if dro is not None and not dro.empty and team in dro.index:
                r = dro.loc[team]
                st.caption(f"**Drives:** {r['pts_per_drive']:.2f} pts/drive ({ordinal(r['ppd_rank'])}) · "
                           f"score {fmt(r['score_rate'], 'pct')} · TD {fmt(r['td_rate'], 'pct')}")
            to = extras.get("turnovers")
            if to is not None and not to.empty and team in to.index:
                t = to.loc[team]
                st.caption(f"**Turnovers:** {t['margin']:+.2f}/gm (regressed {t['reg_margin']:+.2f}) · "
                           f"give {t['giveaways']:.2f} · take {t['takeaways']:.2f}")
            co = extras.get("coaching")
            if co is not None and not co.empty and team in co.index:
                c = co.loc[team]
                st.caption(f"**Scheme:** {c.get('pa_label', '—')} "
                           f"(PA {fmt(c['play_action_rate'], 'pct')} · motion {fmt(c['motion_rate'], 'pct')})")
    _strengths_struggles(profiles.offense_facets(team, off, extras))


def _defense_section(deff: pd.DataFrame, blitz: pd.DataFrame, team: str,
                     extras: dict, scheme_row) -> None:
    d = deff.loc[team]
    st.markdown("### Defense")
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
        st.plotly_chart(percentile_chart(rows, "Defense percentiles (100 = stingiest)"), width="stretch")
    with cn:
        with st.container(border=True):
            prs = extras.get("pressure")
            if prs is not None and not prs.empty and team in prs.index:
                p = prs.loc[team]
                st.caption(f"**Pass rush:** {pressure.pressure_label(p['pressure_rate_rank'])} — "
                           f"pressure {fmt(p['pressure_rate'], 'pct')} ({ordinal(p['pressure_rate_rank'])}), "
                           f"sacks {fmt(p['sack_rate'], 'pct')}")
            if not blitz.empty and team in blitz.index:
                b = blitz.loc[team]
                st.caption(f"**Blitz:** {fmt(b['blitz_rate'], 'pct')} of dropbacks "
                           f"({b.get('blitz_tendency', '—')})")
            else:
                st.caption("**Blitz:** FTN charting not loaded for these seasons.")
            if scheme_row is not None:
                st.caption(f"**Coverage:** zone {fmt(scheme_row['zone_rate'], 'pct')} · "
                           f"man {fmt(scheme_row['man_rate'], 'pct')} · "
                           f"confidence **{scheme_row.get('confidence', '—')}**")
                _per_source_expander(scheme_row)
            else:
                st.caption("**Coverage (zone/man):** _auto-fetch pending or offseason_ ")
            st.caption("_Upload PFF (sidebar) → Cover 0–6 shells & situational man/zone._")
    _strengths_struggles(profiles.defense_facets(team, deff, extras))


# --- advanced: splits + NGS --------------------------------------------------
def _splits_section(team: str, extras: dict) -> None:
    st.markdown("### Situational splits")
    sp = splits.team_splits(extras.get("pbp"), extras.get("schedule"), team)
    if sp.empty:
        st.info("Splits need play-by-play for the current season — they populate once games are played.")
        return
    sp = sp.rename(columns={"Off EPA/play": "Off /100", "Def EPA/play": "Def /100"})
    num_cols = [c for c in sp.columns if c != "Split"]
    try:
        sty = sp.style.background_gradient(cmap="RdYlGn", subset=["Off /100"])
        if "Def /100" in sp.columns:
            sty = sty.background_gradient(cmap="RdYlGn_r", subset=["Def /100"])
        sty = sty.format({c: (lambda v: "—" if pd.isna(v) else f"{v * 100:+.1f}") for c in num_cols},
                         na_rep="—")
        st.dataframe(sty, width="stretch", hide_index=True)
    except Exception:  # noqa: BLE001 - styling needs matplotlib; fall back to plain
        for c in num_cols:
            sp[c] = (sp[c] * 100).round(1)
        st.dataframe(sp, width="stretch", hide_index=True)
    st.caption("Points per **100 plays** by situation (0 = average). A team much better on early "
               "downs or at home is an edge the season number hides.")


def _ngs_section(team: str, extras: dict) -> None:
    st.markdown("### NextGen tracking")
    npass, nrec = extras.get("ngs_pass"), extras.get("ngs_rec")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Passing (QB)**")
        if npass is not None and not npass.empty and team in npass.index:
            r = npass.loc[team]
            st.caption(f"⏱ Time to throw: **{fmt(r.get('avg_time_to_throw'), 'num1')}s** "
                       f"({ordinal(r.get('ttt_rank'))})")
            st.caption(f"CPOE: **{fmt(r.get('completion_percentage_above_expectation'), 'num1')}** "
                       f"({ordinal(r.get('cpoe_rank'))})")
            st.caption(f"Aggressiveness: **{fmt(r.get('aggressiveness'), 'num1')}%** "
                       f"({ordinal(r.get('aggr_rank'))})")
        else:
            st.caption("_NGS passing not available for this season yet._")
    with c2:
        st.markdown("**Receiving (targets-weighted)**")
        if nrec is not None and not nrec.empty and team in nrec.index:
            r = nrec.loc[team]
            st.caption(f"↔ Separation: **{fmt(r.get('avg_separation'), 'num1')} yds** "
                       f"({ordinal(r.get('sep_rank'))})")
            st.caption(f"YAC over expected: **{fmt(r.get('avg_yac_above_expectation'), 'num1')}** "
                       f"({ordinal(r.get('yac_rank'))})")
            if pd.notna(r.get("top_separation")):
                st.caption(f"Top target: **{r.get('top_target')}** "
                           f"({fmt(r.get('top_separation'), 'num1')} yds separation)")
        else:
            st.caption("_NGS receiving not available for this season yet._")
    st.caption("Player-tracking data (2016+, free from nflverse). The 'why' behind the EPA.")


# --- render ------------------------------------------------------------------
def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    extras = extras or {}
    if off.empty and deff.empty:
        st.warning("No play-by-play data yet. Check back once games are played.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    team = st.selectbox("Team", teams, index=0, label_visibility="collapsed")

    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
    scheme_row = scheme_df.loc[team] if scheme_df is not None and team in scheme_df.index else None

    _header(team, off, deff, extras)
    st.markdown(
        injury_card_html(extras.get("injuries", {}).get(team, []),
                         extras.get("injury_week"),
                         has_report=extras.get("injury_week") is not None),
        unsafe_allow_html=True)
    st.divider()

    overview, advanced = st.tabs(["Overview", "Advanced"])
    with overview:
        if team in off.index:
            _offense_section(off, team, extras)
        st.divider()
        if team in deff.index:
            _defense_section(deff, blitz, team, extras, scheme_row)
    with advanced:
        _splits_section(team, extras)
        st.divider()
        _ngs_section(team, extras)
        st.divider()
        from ui import sharp_panel
        sharp_panel.render_team(extras.get("sharp", {}), team)
        st.divider()
        _compare_section(off, deff, extras, team, teams)
