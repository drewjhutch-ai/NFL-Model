"""The 'Matchups' tab: the week's games, each as a pro-level head-to-head.

A branded banner, a headline verdict (who's favored + the single biggest
mismatch), a diverging "where's the edge" chart per direction, the positional
matchup tables, and styled scouting notes.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import edges, injuries, loaders, positional, pressure, rushing
from ui.components import edge_bar_chart, edge_meter_html, fmt, ordinal


# --- banner ------------------------------------------------------------------
def _team_head(col, abbr: str, meta: dict) -> None:
    m = meta.get(abbr, {})
    color = m.get("color") or "#1f77b4"
    with col:
        if m.get("logo"):
            st.image(m["logo"], width=52)
        st.markdown(
            f"<span style='border-left:5px solid {color};padding-left:8px;"
            f"font-size:1.05rem;font-weight:700;'>{m.get('name', abbr)}</span>",
            unsafe_allow_html=True)


def _banner(away: str, home: str, game_row) -> None:
    meta = loaders.team_meta()
    c1, cm, c2 = st.columns([5, 1, 5])
    _team_head(c1, away, meta)
    cm.markdown("<div style='text-align:center;font-size:1.4rem;margin-top:14px;"
                "color:#888;'>@</div>", unsafe_allow_html=True)
    _team_head(c2, home, meta)
    if game_row is not None and "gameday" in game_row and pd.notna(game_row.get("gameday")):
        st.caption(f"📅 {game_row['gameday']} · Week {int(game_row['week'])}")


# --- headline verdict --------------------------------------------------------
def _verdict(away, home, off, deff, extras) -> None:
    ae = edges.facet_edges(away, home, off, deff, extras)
    he = edges.facet_edges(home, away, off, deff, extras)
    a_net, h_net = edges.direction_net(ae), edges.direction_net(he)
    diff = h_net - a_net
    fav = home if diff > 0 else away

    st.markdown(edge_meter_html(away, home, a_net, h_net), unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)
    k1.metric(f"{away} attack", f"{a_net:+.1f}", help="Importance-weighted attack edge, away offense vs home defense")
    k2.metric(f"{home} attack", f"{h_net:+.1f}", help="Importance-weighted attack edge, home offense vs away defense")
    k3.metric("Projected lean", fav, f"+{abs(diff):.1f}" if diff else None, help="Bigger weighted attack edge")

    # QB is the highest-weighted facet — surface it explicitly.
    qa = next((e for e in ae if e["label"] == "QB / Passing"), None)
    qh = next((e for e in he if e["label"] == "QB / Passing"), None)
    if qa or qh:
        bits = []
        if qa:
            bits.append(f"{away} {'+' if qa['mag'] >= 0 else ''}{qa['mag']:.0f}")
        if qh:
            bits.append(f"{home} {'+' if qh['mag'] >= 0 else ''}{qh['mag']:.0f}")
        st.caption("🎯 **QB / Passing edge (highest weight ×%.1f):** %s"
                   % (qa["weight"] if qa else qh["weight"], " · ".join(bits)))

    allx = [(away, e) for e in ae] + [(home, e) for e in he]
    if allx:
        team, big = max(allx, key=lambda x: x[1]["impact"])
        if big["impact"] >= 10:
            st.success(f"🔑 **Biggest edge:** {team} — {big['label']} · {big['detail']} "
                       f"(edge {big['mag']:+.0f} × weight {big['weight']:g})")
        else:
            st.info("🟡 No lopsided edges — a close, balanced matchup on paper.")


# --- one attack direction ----------------------------------------------------
def _direction(o_team, d_team, off, deff, blitz, extras) -> None:
    meta = loaders.team_meta().get(o_team, {})
    color = meta.get("color") or "#1f77b4"
    st.markdown(f"<div style='border-left:5px solid {color};padding-left:10px;'>"
                f"<b>{o_team} offense → {d_team} defense</b></div>", unsafe_allow_html=True)

    fe = edges.facet_edges(o_team, d_team, off, deff, extras)
    if fe:
        st.plotly_chart(edge_bar_chart(fe), use_container_width=True)

    pos_tbl = positional.matchup_table(o_team, d_team, extras.get("usage", pd.DataFrame()),
                                       extras.get("dvp", {}))
    if not pos_tbl.empty:
        st.dataframe(pos_tbl.drop(columns=[c for c in ["_mag"] if c in pos_tbl.columns]),
                     width="stretch", hide_index=True)

    wr_tbl = positional.wr_tier_matchup(o_team, d_team, extras.get("wr_off", pd.DataFrame()),
                                        extras.get("wr_def", {}))
    if not wr_tbl.empty:
        with st.expander("WR1 / WR2 / WR3 detail"):
            st.dataframe(wr_tbl, width="stretch", hide_index=True)

    with st.container(border=True):
        _notes(o_team, d_team, off, deff, blitz, extras)


def _notes(o_team, d_team, off, deff, blitz, extras) -> None:
    qb, prs = extras.get("qb"), extras.get("pressure")
    if qb is not None and not qb.empty and o_team in qb.index and \
       prs is not None and not prs.empty and d_team in prs.index:
        q, p = qb.loc[o_team], prs.loc[d_team]
        st.caption(f"**QB vs rush:** {q.get('qb_style', '—')} "
                   f"({fmt(q['qb_rush_rate'], 'pct')}) vs {pressure.pressure_label(p['pressure_rate_rank'])} "
                   f"({fmt(p['pressure_rate'], 'pct')} pressure)")
    rush = extras.get("rush")
    if rush is not None and not rush.empty and o_team in rush.index and d_team in deff.index:
        r = rush.loc[o_team]
        st.caption(f"**Ground game:** {rushing.rushing_label(r.get('ryoe_rank'))} "
                   f"({r.get('ryoe_per_att', float('nan')):+.2f} RYOE/att) vs "
                   f"{d_team} run D {ordinal(deff.loc[d_team, 'rush_epa_rank'])}")
    os_, ds_ = extras.get("off_sit"), extras.get("def_sit")
    if os_ is not None and not os_.empty and o_team in os_.index:
        o3 = os_.loc[o_team]
        d3txt = ""
        if ds_ is not None and not ds_.empty and d_team in ds_.index:
            d3txt = f" vs {d_team} allows {ordinal(ds_.loc[d_team, 'third_rank'])}"
        st.caption(f"**3rd down:** {fmt(o3['third_conv'], 'pct')} convert "
                   f"({ordinal(o3['third_rank'])}){d3txt}")
        rztxt = ""
        if ds_ is not None and not ds_.empty and d_team in ds_.index:
            rztxt = f" vs {d_team} allows {ordinal(ds_.loc[d_team, 'rz_rank'])}"
        st.caption(f"**Red zone:** {fmt(o3['rz_td_rate'], 'pct')} TD rate "
                   f"({ordinal(o3['rz_rank'])}){rztxt}")
    if not blitz.empty and d_team in blitz.index:
        b = blitz.loc[d_team]
        st.caption(f"**{d_team} blitz:** {fmt(b['blitz_rate'], 'pct')} "
                   f"({b.get('blitz_tendency', '—')})")


def _injuries_row(away, home, extras) -> None:
    imap = extras.get("injuries", {})
    wk = extras.get("injury_week")
    if wk is None:
        st.caption("🩺 Injury reports appear here once the season starts.")
        return
    c1, c2 = st.columns(2)
    ai, hi = imap.get(away, []), imap.get(home, [])
    c1.markdown(f"**{away}** 🩺 {injuries.summary_line(ai)}")
    c2.markdown(f"**{home}** 🩺 {injuries.summary_line(hi)}")
    if any(p["status"] == "Out" for p in ai + hi):
        outs = [f"{p['name']} ({away if p in ai else home})" for p in ai + hi if p["status"] == "Out"]
        st.warning("🔴 **Ruled out:** " + " · ".join(outs))


def _breakdown(away, home, off, deff, blitz, extras, game_row=None) -> None:
    if away == home:
        st.info("Pick two different teams.")
        return
    _banner(away, home, game_row)
    _injuries_row(away, home, extras)
    _verdict(away, home, off, deff, extras)
    st.divider()
    st.markdown("### ⚔️ Attack breakdowns")
    la, ra = st.columns(2)
    with la:
        _direction(away, home, off, deff, blitz, extras)
    with ra:
        _direction(home, away, off, deff, blitz, extras)
    st.caption("🟢 offense edge · 🔴 defense edge. Bar **length** = raw edge; bar "
               "**thickness** = how much that facet decides NFL games (QB/passing "
               "weighted highest, RB receiving lowest). Ordered by weighted impact. "
               "A decision aid — the pick is yours.")


def _custom(off, deff, blitz, extras, teams) -> None:
    c1, c2 = st.columns(2)
    away = c1.selectbox("Away / Team A", teams, index=0, key="mu_away")
    home = c2.selectbox("Home / Team B", teams, index=1 if len(teams) > 1 else 0, key="mu_home")
    _breakdown(away, home, off, deff, blitz, extras)


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           schedule: pd.DataFrame, extras: dict) -> None:
    if off.empty or deff.empty:
        st.warning("Need offensive and defensive data to compare matchups.")
        return

    teams = sorted(set(off.index) | set(deff.index))
    season = config.CURRENT_SEASON
    have_sched = (schedule is not None and not schedule.empty
                  and (schedule["season"] == season).any())

    if have_sched:
        s = schedule[schedule["season"] == season]
        weeks = sorted(int(w) for w in s["week"].unique())
        default_wk = loaders.current_week(schedule, season) or weeks[0]
        idx = weeks.index(default_wk) if default_wk in weeks else 0
        cwk, cgm = st.columns([1, 3])
        wk = cwk.selectbox(f"Week ({season})", weeks, index=idx)
        games = s[s["week"] == wk].sort_values("gameday" if "gameday" in s.columns else "week")
        labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
        if not labels:
            st.info("No games listed for this week.")
            return
        pick = cgm.selectbox("Game", labels)
        row = games.iloc[labels.index(pick)]
        _breakdown(row["away_team"], row["home_team"], off, deff, blitz, extras, row)

        with st.expander("Or build a custom matchup (any two teams)"):
            _custom(off, deff, blitz, extras, teams)
    else:
        st.info("Schedule not loaded — pick any two teams to compare.")
        _custom(off, deff, blitz, extras, teams)
