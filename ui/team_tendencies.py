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
from data import sharp_value as sv
from data.providers import load_coverage
from ui import kit
from ui.components import (facet_html, fmt, gauge_bar_html, injury_card_html,
                           movement_arrow, ordinal, percentile_chart, radar_chart,
                           sparkline_fig, sw_card_html, unicode_spark)


def _sharp_power_rank(extras) -> pd.Series | None:
    """Sharp Football's independent charted-EPA power rank (1 = best), or None."""
    rt = sv.epa_ratings(extras.get("sharp") or {})
    if rt.empty or "off_epa" not in rt.columns or "def_epa" not in rt.columns:
        return None
    return (rt["off_epa"] - rt["def_epa"]).rank(ascending=False, method="min")


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
def _rank_tile(label: str, rank, delta=None, help_accent="accent") -> str:
    val = ordinal(int(rank)) if rank is not None and pd.notna(rank) else "—"
    direction = None
    dtxt = None
    if delta is not None and pd.notna(delta) and delta != 0:
        direction = "up" if delta > 0 else "down"
        dtxt = f"{abs(int(delta))} wk"
    # rank accent: top-10 green, bottom-10 red, else neutral
    acc = help_accent
    if rank is not None and pd.notna(rank):
        acc = "edge" if int(rank) <= 10 else ("fade" if int(rank) >= 23 else "accent")
    return kit.kpi(label, val, dtxt, direction, acc)


def _header(team: str, off: pd.DataFrame, deff: pd.DataFrame, extras: dict) -> None:
    meta = loaders.team_meta().get(team, {})
    color = meta.get("color") or kit.PALETTE["accent"]
    from data import betting
    power = betting.power_ratings(off, deff)
    prank = int(power.loc[team, "power_rank"]) if team in power.index and pd.notna(power.loc[team, "power_rank"]) else None
    net = float(power.loc[team, "net"]) if team in power.index and pd.notna(power.loc[team, "net"]) else None
    grade = profiles.team_grade(prank)
    thesis = profiles.team_thesis(team, off, deff, extras) if team in off.index else ""

    hist = history.load_history(config.CURRENT_SEASON)
    mv = {k: history.rank_movement(hist, f"{k}_rank") for k in ("power", "off", "def")}
    sharp_rank = _sharp_power_rank(extras)
    sos = extras.get("sos")
    pace = extras.get("pace")
    pace_rank = pace.rank(ascending=False, method="min") if pace is not None and len(pace) else None

    c_logo, c_name, c_grade = st.columns([1, 7, 2])
    if meta.get("logo"):
        c_logo.image(meta["logo"], width=60)
    pi = profiles.pass_identity(team, off) if team in off.index else None
    qb = extras.get("qb")
    qlab = qb.loc[team].get("qb_style", "—") if qb is not None and not qb.empty and team in qb.index else "—"
    ident = f"{pi['base']} · {qlab}" if pi else qlab
    c_name.markdown(
        f"<div style='border-left:6px solid {color};padding:2px 0 2px 13px;'>"
        f"<h2 style='margin:0;'>{meta.get('name', team)}</h2>"
        f"<div style='color:var(--ink-dim);font-size:0.92rem;'>{thesis}</div>"
        f"<div style='color:var(--ink-faint);font-size:0.78rem;margin-top:2px;'>{ident}</div></div>",
        unsafe_allow_html=True)
    c_grade.markdown(
        f"<div style='text-align:center;border:1px solid {color};border-radius:12px;padding:6px 4px;"
        f"box-shadow:0 0 18px -6px {color};'>"
        f"<div style='font-family:\"IBM Plex Mono\",monospace;font-size:0.6rem;letter-spacing:.16em;"
        f"color:var(--ink-faint);'>GRADE</div>"
        f"<div style='font-family:\"Archivo\";font-size:2.1rem;font-weight:900;line-height:1;"
        f"color:{color};'>{grade}</div></div>",
        unsafe_allow_html=True)

    o = off.loc[team] if team in off.index else None
    d = deff.loc[team] if team in deff.index else None
    cols = st.columns(6)
    cols[0].markdown(_rank_tile("Offense", o["epa_play_rank"] if o is not None else None,
                                mv["off"].get(team)), unsafe_allow_html=True)
    cols[1].markdown(_rank_tile("Defense", d["epa_play_rank"] if d is not None else None,
                                mv["def"].get(team)), unsafe_allow_html=True)
    net_acc = "edge" if (net or 0) > 0.02 else ("fade" if (net or 0) < -0.02 else "accent")
    cols[2].markdown(kit.kpi("Net EPA/100", f"{net*100:+.1f}" if net is not None else "—",
                             None, None, net_acc), unsafe_allow_html=True)
    cols[3].markdown(_rank_tile("Sharp power", sharp_rank.get(team) if sharp_rank is not None else None,
                                help_accent="violet"), unsafe_allow_html=True)
    cols[4].markdown(_rank_tile("Pace", pace_rank.get(team) if pace_rank is not None else None,
                                help_accent="sharp"), unsafe_allow_html=True)
    sos_val = f"{float(sos.get(team)):+.3f}" if sos is not None and team in sos.index else "—"
    cols[5].markdown(kit.kpi("Sched (SOS)", sos_val, None, None, "accent"), unsafe_allow_html=True)

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


# --- Sharp caption helpers (surface the new data in the glance layer) --------
def _sharp_off_caption(team: str, extras: dict) -> None:
    sharp = extras.get("sharp") or {}
    if not sv.available(sharp):
        return
    bits = []
    pp = sv.pass_pro_ranks(sharp)
    if not pp.empty and team in pp.index:
        bits.append(f"pass pro **{ordinal(int(pp.loc[team]))}**")
    ol = sharp.get("off_line")
    if ol is not None and team in ol.index:
        ttt = sv._series(ol, "time to throw")
        if ttt is not None and team in ttt.index and pd.notna(ttt.loc[team]):
            bits.append(f"TTT {ttt.loc[team]:.2f}s")
    pers = sharp.get("off_personnel")
    if pers is not None and team in pers.index:
        p11 = sv._series(pers, "11")
        if p11 is not None and team in p11.index and pd.notna(p11.loc[team]):
            v = p11.loc[team]
            bits.append(f"11-personnel {v:.0f}%" if v > 1.5 else f"11-personnel {v*100:.0f}%")
    if bits:
        st.caption("**Sharp charting:** " + " · ".join(bits))


def _sharp_def_caption(team: str, extras: dict) -> None:
    sharp = extras.get("sharp") or {}
    if not sv.available(sharp):
        return
    bits = []
    pr = sv.pass_rush_ranks(sharp)
    if not pr.empty and team in pr.index:
        bits.append(f"pass rush **{ordinal(int(pr.loc[team]))}**")
    dt = sharp.get("def_tendencies")
    if dt is not None and team in dt.index:
        bl = sv._series(dt, "blitz")
        if bl is not None and team in bl.index and pd.notna(bl.loc[team]):
            v = bl.loc[team]
            bits.append(f"blitz {v:.0f}%" if v > 1.5 else f"blitz {v*100:.0f}%")
    cbp = sv.coverage_by_position(sharp)
    if not cbp.empty and team in cbp.index:
        # name the softest position coverage (highest YPT rank) as a warning
        rank_cols = {c: cbp.loc[team, c] for c in cbp.columns if c.endswith("_rank")}
        if rank_cols:
            worst = max(rank_cols, key=lambda c: rank_cols[c])
            pos = worst.replace("ypt_", "").replace("_rank", "")
            bits.append(f"softest vs **{pos}** ({ordinal(int(rank_cols[worst]))})")
    if bits:
        st.caption("**Sharp charting:** " + " · ".join(bits))


def _team_radar(team: str, off, deff, extras, side: str, title: str) -> None:
    cats, vals = _radar_values(team, off, deff, extras, side)
    if not cats:
        return
    color = loaders.team_meta().get(team, {}).get("color") or kit.PALETTE["accent"]
    st.plotly_chart(radar_chart(cats, [(team, vals, color)], title), width="stretch")


# --- offense / defense sections ----------------------------------------------
def _offense_section(off: pd.DataFrame, deff: pd.DataFrame, team: str, extras: dict) -> None:
    o = off.loc[team]
    st.markdown("### Offense")
    cc, cr = st.columns(2)
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
    with cr:
        _team_radar(team, off, deff, extras, "offense", "Offense fingerprint")
    if True:
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
            _sharp_off_caption(team, extras)
    _strengths_struggles(profiles.offense_facets(team, off, extras))


def _defense_section(deff: pd.DataFrame, blitz: pd.DataFrame, team: str,
                     extras: dict, scheme_row) -> None:
    d = deff.loc[team]
    st.markdown("### Defense")
    cc, cr = st.columns(2)
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
    with cr:
        _team_radar(team, None, deff, extras, "defense", "Defense fingerprint")
    if True:
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
            _sharp_def_caption(team, extras)
    _strengths_struggles(profiles.defense_facets(team, deff, extras))


# --- advanced: splits + NGS --------------------------------------------------
def _split_cell(v, higher_good: bool) -> str:
    """One diverging bar: value scaled to per-100, green when good, red when bad."""
    if v is None or pd.isna(v):
        return '<div class="k-cell"><div class="track"><span class="mid"></span></div>' \
               '<span class="sn">—</span></div>'
    per100 = v * 100
    good = per100 if higher_good else -per100
    mag = min(abs(per100) / 12.0 * 50.0, 50.0)
    color = "var(--edge)" if good >= 0 else "var(--fade)"
    side = f"left:50%;width:{mag:.0f}%" if per100 >= 0 else f"right:50%;width:{mag:.0f}%"
    return (f'<div class="k-cell"><div class="track"><span class="mid"></span>'
            f'<span class="fill" style="{side};background:{color}"></span></div>'
            f'<span class="sn">{per100:+.1f}</span></div>')


def _splits_section(team: str, extras: dict) -> None:
    st.markdown("### Situational splits")
    sp = splits.team_splits(extras.get("pbp"), extras.get("schedule"), team)
    if sp.empty:
        st.info("Splits need play-by-play for the current season — they populate once games are played.")
        return
    html = ['<div class="k-splits">',
            '<div class="k-srow k-shead"><span></span><span>Offense · pts/100</span>'
            '<span>Defense allowed · pts/100</span></div>']
    for _, r in sp.iterrows():
        html.append(
            f'<div class="k-srow"><span class="sl">{r["Split"]}</span>'
            f'{_split_cell(r.get("Off EPA/play"), True)}'
            f'{_split_cell(r.get("Def EPA/play"), False)}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption("Points per **100 plays** by situation (bar from center; 0 = league average). "
               "Green = good for that team, red = bad — offense wants the bar right, defense wants it green. "
               "A team much better on early downs or at home is an edge the season number hides.")


def _mini(label: str, value: str, rank=None) -> str:
    r = f'<div class="r">{ordinal(rank)}</div>' if rank is not None and pd.notna(rank) else '<div class="r">&nbsp;</div>'
    return f'<div class="k-mini"><div class="l">{label}</div><div class="v">{value}</div>{r}</div>'


def _ngs_section(team: str, extras: dict) -> None:
    st.markdown("### NextGen tracking")
    npass, nrec = extras.get("ngs_pass"), extras.get("ngs_rec")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Passing (QB)**")
        if npass is not None and not npass.empty and team in npass.index:
            r = npass.loc[team]
            t = st.columns(3)
            t[0].markdown(_mini("Time to throw", f"{fmt(r.get('avg_time_to_throw'), 'num1')}s",
                                r.get("ttt_rank")), unsafe_allow_html=True)
            t[1].markdown(_mini("CPOE", fmt(r.get('completion_percentage_above_expectation'), 'num1'),
                                r.get("cpoe_rank")), unsafe_allow_html=True)
            t[2].markdown(_mini("Aggressive", f"{fmt(r.get('aggressiveness'), 'num1')}%",
                                r.get("aggr_rank")), unsafe_allow_html=True)
        else:
            st.caption("_NGS passing not available for this season yet._")
    with c2:
        st.markdown("**Receiving (targets-weighted)**")
        if nrec is not None and not nrec.empty and team in nrec.index:
            r = nrec.loc[team]
            t = st.columns(2)
            t[0].markdown(_mini("Separation", f"{fmt(r.get('avg_separation'), 'num1')} yd",
                                r.get("sep_rank")), unsafe_allow_html=True)
            t[1].markdown(_mini("YAC over exp", fmt(r.get('avg_yac_above_expectation'), 'num1'),
                                r.get("yac_rank")), unsafe_allow_html=True)
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
            _offense_section(off, deff, team, extras)
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
