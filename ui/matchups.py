"""The 'Matchups' tab: a layered, pro-style head-to-head.

Handicapping is layered — no single number decides a game — so this reads top
to bottom: a projected lean with confidence, the weighted "where's the edge"
chart, then drill-down dropdowns (trenches, WR tiers, situational, environment,
coverage scheme), and scouting notes that tie it together. The trenches
(O-line vs D-line) get their own layer because they're the most undervalued
factor in the sport. Coverage-scheme calculations are wired but dormant until
PFF data is connected.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, edges, injuries, loaders, positional, pressure, rushing
from data.providers import load_coverage
from data.weather import weather_effects
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


def _injuries_row(away, home, extras) -> None:
    imap = extras.get("injuries", {})
    if extras.get("injury_week") is None:
        st.caption("🩺 Injury reports appear here once the season starts.")
        return
    c1, c2 = st.columns(2)
    c1.markdown(f"**{away}** 🩺 {injuries.summary_line(imap.get(away, []))}")
    c2.markdown(f"**{home}** 🩺 {injuries.summary_line(imap.get(home, []))}")


# --- headline verdict --------------------------------------------------------
def _stars(margin: float) -> tuple[str, str]:
    m = abs(margin)
    if m >= 7:
        return "★★★", "Strong lean"
    if m >= 3.5:
        return "★★☆", "Lean"
    if m >= 1.5:
        return "★☆☆", "Slight lean"
    return "☆☆☆", "Coin flip"


def _verdict(away, home, off, deff, extras) -> None:
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    margin = betting.project_margin(off, deff, home, away, st_ppg, qb)  # + = home
    ae = edges.facet_edges(away, home, off, deff, extras)
    he = edges.facet_edges(home, away, off, deff, extras)
    a_net, h_net = edges.direction_net(ae), edges.direction_net(he)

    if pd.notna(margin):
        winner = home if margin > 0 else away
        stars, label = _stars(margin)
        st.markdown(f"## Projected lean: {winner} by {abs(margin):.1f} &nbsp; "
                    f"<span style='color:#f1c40f'>{stars}</span> "
                    f"<span style='color:#888;font-size:1rem'>({label})</span>",
                    unsafe_allow_html=True)

    st.markdown(edge_meter_html(away, home, a_net, h_net), unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)
    k1.metric(f"{away} attack", f"{a_net:+.1f}", help="Importance-weighted attack edge")
    k2.metric(f"{home} attack", f"{h_net:+.1f}", help="Importance-weighted attack edge")
    diff = h_net - a_net
    k3.metric("Attack lean", home if diff > 0 else away, f"+{abs(diff):.1f}" if diff else None)

    qa = next((e for e in ae if e["label"] == "QB / Passing"), None)
    qh = next((e for e in he if e["label"] == "QB / Passing"), None)
    if qa or qh:
        bits = []
        if qa:
            bits.append(f"{away} {qa['mag']:+.0f}")
        if qh:
            bits.append(f"{home} {qh['mag']:+.0f}")
        st.caption(f"🎯 **QB / Passing (highest weight):** {' · '.join(bits)}")

    allx = [(away, e) for e in ae] + [(home, e) for e in he]
    if allx:
        team, big = max(allx, key=lambda x: x[1]["impact"])
        if big["impact"] >= 10:
            st.success(f"🔑 **Biggest edge:** {team} — {big['label']} · {big['detail']}")


# --- attack direction (edge chart + positional + notes) ----------------------
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
        d3 = f" vs {d_team} {ordinal(ds_.loc[d_team, 'third_rank'])}" if ds_ is not None and d_team in ds_.index else ""
        st.caption(f"**3rd down:** {fmt(o3['third_conv'], 'pct')} ({ordinal(o3['third_rank'])}){d3} · "
                   f"**Red zone:** {fmt(o3['rz_td_rate'], 'pct')} TD ({ordinal(o3['rz_rank'])})")
    if not blitz.empty and d_team in blitz.index:
        b = blitz.loc[d_team]
        st.caption(f"**{d_team} blitz:** {fmt(b['blitz_rate'], 'pct')} ({b.get('blitz_tendency', '—')})")


# --- drill-down dropdowns ----------------------------------------------------
def _trench_rows(o_team, d_team, deff, extras) -> list[dict]:
    prot, prs = extras.get("protection"), extras.get("pressure")
    rush = extras.get("rush")
    rows = []
    if prot is not None and o_team in prot.index and prs is not None and d_team in prs.index:
        pr = int(prot.loc[o_team, "protection_rank"]); dr = int(prs.loc[d_team, "pressure_rate_rank"])
        rows.append({"Battle": "Pass protection", f"{o_team} O-line": ordinal(pr),
                     f"{d_team} pass rush": ordinal(dr),
                     "Edge": _edge_word(dr - pr)})
    if rush is not None and o_team in rush.index and "rush_epa_rank" in deff.columns and d_team in deff.index:
        rr = rush.loc[o_team].get("ryoe_rank")
        dr = int(deff.loc[d_team, "rush_epa_rank"])
        if pd.notna(rr):
            rows.append({"Battle": "Run blocking (RYOE)", f"{o_team} O-line": ordinal(int(rr)),
                         f"{d_team} pass rush": ordinal(dr),  # column label reused; it's run D
                         "Edge": _edge_word(dr - int(rr))})
    return rows


def _edge_word(mag) -> str:
    if mag >= 8:
        return "🟢 Strong offense"
    if mag >= 3:
        return "🟢 Offense"
    if mag <= -8:
        return "🔴 Strong defense"
    if mag <= -3:
        return "🔴 Defense"
    return "🟡 Even"


def _dropdowns(away, home, off, deff, extras) -> None:
    st.markdown("### 🔬 Deeper breakdown")

    with st.expander("⚔️ Trenches — O-line vs D-line (the undervalued battle)"):
        for o, d in ((away, home), (home, away)):
            rows = _trench_rows(o, d, deff, extras)
            if rows:
                st.markdown(f"**{o} blocking vs {d} front**")
                df = pd.DataFrame(rows).rename(columns={f"{d} pass rush": f"{d} front"})
                st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Pass protection = sacks allowed vs pressure generated. Run blocking = "
                   "rush yards over expected vs run defense. An underdog winning the trenches "
                   "is one of the strongest angles in football.")

    with st.expander("🎯 WR1 / WR2 / WR3 detail"):
        for o, d in ((away, home), (home, away)):
            wr = positional.wr_tier_matchup(o, d, extras.get("wr_off", pd.DataFrame()),
                                            extras.get("wr_def", {}))
            if not wr.empty:
                st.markdown(f"**{o} receivers vs {d} coverage**")
                st.dataframe(wr, width="stretch", hide_index=True)

    with st.expander("📊 Situational & pace"):
        os_, ds_ = extras.get("off_sit"), extras.get("def_sit")
        pace = extras.get("pace")
        rows = []
        for o, d in ((away, home), (home, away)):
            if os_ is not None and o in os_.index:
                r = os_.loc[o]
                rows.append({
                    "Team": o,
                    "3rd down": f"{fmt(r['third_conv'], 'pct')} ({ordinal(r['third_rank'])})",
                    "Red zone TD": f"{fmt(r['rz_td_rate'], 'pct')} ({ordinal(r['rz_rank'])})",
                    "Pace (plays/gm)": f"{pace.get(o, float('nan')):.0f}" if pace is not None else "—",
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with st.expander("🌦️ Environment — weather, rest, home field"):
        _environment(away, home, extras)

    with st.expander("🔒 Coverage scheme (unlocks with PFF)"):
        scheme = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
        if scheme is not None and not getattr(scheme, "empty", True):
            rows = []
            for t in (away, home):
                if t in scheme.index:
                    rows.append({"Team": t, "Zone": fmt(scheme.loc[t, "zone_rate"], "pct"),
                                 "Man": fmt(scheme.loc[t, "man_rate"], "pct")})
            if rows:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("Zone/man rates show here from the blended feed. The **scheme-fit edge** "
                   "(a zone-beating offense vs a zone-heavy defense, weighted into the chart "
                   "above) activates automatically once a PFF offense-vs-coverage export is "
                   "uploaded — the calculation is already wired.")


def _environment(away, home, extras) -> None:
    row = extras.get("_game_row")
    notes = []
    if row is not None:
        wx = weather_effects(row)
        if wx["note"]:
            notes.append(wx["note"])
        hr, ar = row.get("home_rest"), row.get("away_rest")
        if pd.notna(hr) and pd.notna(ar) and abs(hr - ar) >= 3:
            notes.append(f"🛌 Rest edge: {home if hr > ar else away} (+{int(abs(hr - ar))} days)")
        if row.get("div_game") == 1:
            notes.append("🤝 Division game — historically tighter.")
    hfa = betting.home_field(home)
    notes.append(f"🏟️ {home} home field ≈ {hfa:.1f} pts")
    imap = extras.get("injuries", {})
    for t in (away, home):
        outs = [p for p in imap.get(t, []) if p["status"] == "Out"]
        if outs:
            notes.append(f"🩺 {t} without {', '.join(p['name'] for p in outs[:3])}")
    for n in notes:
        st.markdown(f"- {n}")


# --- scouting notes (bottom) -------------------------------------------------
def _scouting(away, home, off, deff, extras) -> None:
    st.markdown("### 📝 Scouting notes")
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    margin = betting.project_margin(off, deff, home, away, st_ppg, qb)
    bullets = []
    if pd.notna(margin):
        w = home if margin > 0 else away
        bullets.append(f"Model leans **{w} by {abs(margin):.1f}** (efficiency + HFA + ST/QB).")
    # trenches read
    for o, d in ((away, home), (home, away)):
        rows = _trench_rows(o, d, deff, extras)
        strong = [r for r in rows if "Strong offense" in r["Edge"]]
        if strong:
            bullets.append(f"**{o}** owns the trenches on {strong[0]['Battle'].lower()}.")
    # biggest positional mismatch
    allx = [(t, e) for t, opp in ((away, home), (home, away))
            for e in edges.facet_edges(t, opp, off, deff, extras)]
    if allx:
        team, big = max(allx, key=lambda x: x[1]["impact"])
        if big["impact"] >= 8:
            bullets.append(f"Key mismatch: **{team} {big['label']}** — {big['detail']}.")
    # environment / injuries
    row = extras.get("_game_row")
    if row is not None:
        wx = weather_effects(row)
        if wx["note"] and wx["total_adj"]:
            bullets.append(f"Weather: {wx['note']} (total nudged {wx['total_adj']:+.1f}).")
    imap = extras.get("injuries", {})
    for t in (away, home):
        qout = [p for p in imap.get(t, []) if p["status"] == "Out" and p["pos"] == "QB"]
        if qout:
            bullets.append(f"⚠️ **{t} QB {qout[0]['name']} OUT** — model has docked their projection.")
    for b in bullets:
        st.markdown(f"- {b}")
    st.caption("Layered read — trenches, skill, situational, and environment together. "
               "A decision aid, not a lock.")


# --- assembly ----------------------------------------------------------------
def _breakdown(away, home, off, deff, blitz, extras, game_row=None) -> None:
    if away == home:
        st.info("Pick two different teams.")
        return
    extras = {**extras, "_game_row": game_row}
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
    st.caption("🟢 offense edge · 🔴 defense edge. Bar length = raw edge; thickness = "
               "how much the facet decides games; ordered by weighted impact.")
    st.divider()
    _dropdowns(away, home, off, deff, extras)
    st.divider()
    _scouting(away, home, off, deff, extras)


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
