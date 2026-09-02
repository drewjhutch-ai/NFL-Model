"""The 'Game Bets' tab — one game, every exploitable edge the engine can find.

Where the model shows off. Beyond the priced markets, an **Edge Sheet** sifts the
game for points of interest the base numbers miss — a heavily-used weapon meeting
a soft coverage, a pace/total tilt, a trench mismatch — and surfaces each as a
candidate bet, ranked. Then the priced board: safest, most edge, and a
correlation-aware same-game parlay. Every number is engine-priced (the full
ensemble incl. Sharp), never hand-set.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betengine, betting, loaders, mismatch, props, simulation
from data import sharp_value as sv
from ui import kit


# --- broadcast header --------------------------------------------------------
def _gb_header(off, deff, extras, row) -> dict | None:
    away, home = row["away_team"], row["home_team"]
    meta = loaders.team_meta()
    sim = simulation.simulate(off, deff, home, away, extras, row)
    am, hm = meta.get(away, {}), meta.get(home, {})
    a_logo = f'<img src="{am["logo"]}">' if am.get("logo") else ""
    h_logo = f'<img src="{hm["logo"]}">' if hm.get("logo") else ""
    score = (f'<div class="sc">{sim["proj_away"]:.0f} <span class="at">–</span> {sim["proj_home"]:.0f}</div>'
             f'<div class="lb">projected score</div>') if sim else '<div class="sc"><span class="at">@</span></div>'
    st.markdown(
        f'<div class="k-vs"><div class="side">{a_logo}<div><div class="nm">{am.get("name", away)}</div></div></div>'
        f'<div class="mid">{score}</div>'
        f'<div class="side right"><div><div class="nm">{hm.get("name", home)}</div></div>{h_logo}</div></div>',
        unsafe_allow_html=True)
    if sim:
        margin = sim["margin_mean"]
        fav = home if margin > 0 else away
        win = max(sim["home_win"], 1 - sim["home_win"])
        wteam = home if sim["home_win"] >= 0.5 else away
        k = st.columns(4)
        k[0].markdown(kit.kpi("Model line", betting.fmt_line(fav, abs(margin)), None, None, "accent"),
                      unsafe_allow_html=True)
        k[1].markdown(kit.kpi("Proj. total", f"{sim['total_mean']:.1f}", None, None, "sharp"),
                      unsafe_allow_html=True)
        k[2].markdown(kit.kpi(f"{wteam} win", f"{win*100:.0f}%", None, None, "edge"),
                      unsafe_allow_html=True)
        if pd.notna(row.get("spread_line")):
            a = betting.assess(row, off, deff, extras)
            ep = a.get("edge_pts")
            if pd.notna(ep) and a.get("value_side"):
                k[3].markdown(kit.kpi("Model edge", f"{a['value_side']} {ep:+.1f}", "vs market",
                                      "up" if ep > 0 else "down", "violet"), unsafe_allow_html=True)
            else:
                k[3].markdown(kit.kpi("Model edge", "none", "≈ market", None, "mute"), unsafe_allow_html=True)
        else:
            k[3].markdown(kit.kpi("Market", "—", "no line posted", None, "mute"), unsafe_allow_html=True)
    return sim


# --- the edge sheet (points of interest) -------------------------------------
def _edge_sheet(away, home, off, deff, extras, sim) -> None:
    st.markdown("### Edge sheet")
    st.caption("The engine sifting the game for exploitable spots — a used weapon vs a soft coverage, a "
               "pace tilt, a trench win. These are candidate bets, ranked by how big the mismatch is.")

    ms = mismatch.game_mismatches(away, home, off, deff, extras)
    ms = [m for m in ms if m["score"] >= 0.20][:6]
    if ms:
        for m in ms:
            lbl = mismatch.strength_label(m["score"])
            color = "var(--edge)" if m["score"] >= 0.30 else "var(--accent)"
            who = m["player"] or f'{m["off"]} {m["pos"]}s'
            epa = f' · {m["epa_tgt"]*100:+.0f} EPA/tgt' if m.get("epa_tgt") is not None else ""
            st.markdown(
                f'<div class="k-bet" style="--kbet:{color}">'
                f'<div class="sel">{who} {kit.chip(lbl, "edge" if m["score"] >= 0.30 else "accent")}</div>'
                f'<div class="meta">{m["off"]} {m["pos"]} · {m["share"]*100:.0f}% of team targets '
                f'(#{m["share_rank"]}){epa}</div>'
                f'<div class="row"><span>vs <b>{m["def"]}</b> coverage <b>#{m["cov_rank"]:.0f}</b> '
                f'(1=tough, 32=soft)</span> · <span style="color:{color}">lean: '
                f'<b>{who} {m["stat"]} Over</b></span></div></div>',
                unsafe_allow_html=True)
    else:
        st.caption("No standout receiving mismatch in this game — coverage is tight both ways.")

    # pace / total tilt + trench note (Sharp), compact
    extras_notes = _sheet_notes(away, home, extras, sim)
    if extras_notes:
        st.markdown("".join(extras_notes), unsafe_allow_html=True)


def _sheet_notes(away, home, extras, sim) -> list[str]:
    sharp = extras.get("sharp") or {}
    pace = extras.get("pace")
    rows = []
    if pace is not None and away in pace.index and home in pace.index:
        combined = pace.get(away) + pace.get(home)
        lg = float(pace.mean()) * 2
        tilt = combined - lg
        if abs(tilt) >= 4:
            side = "Over" if tilt > 0 else "Under"
            rows.append(f'<div class="k-spec"><span class="sk">Pace</span><span class="sv">'
                        f'combined <b>{combined:.0f}</b> plays/gm vs league {lg:.0f} → total leans '
                        f'<b>{side}</b></span></div>')
    if sv.available(sharp):
        pr, pp = sv.pass_rush_ranks(sharp), sv.pass_pro_ranks(sharp)
        for o, d in ((away, home), (home, away)):
            if not pp.empty and o in pp.index and not pr.empty and d in pr.index:
                po, dr = int(pp.loc[o]), int(pr.loc[d])
                if dr - po >= 10:   # offense line much better than the rush it faces
                    rows.append(f'<div class="k-spec"><span class="sk">Trenches</span><span class="sv">'
                                f'<b>{o}</b> pass-pro (#{po}) clearly beats <b>{d}</b> pass-rush (#{dr}) '
                                f'→ clean pocket, back the passing game</span></div>')
    return [f'<div class="k-speclist" style="margin-top:10px">'] + rows + ["</div>"] if rows else []


# --- priced board (kept) -----------------------------------------------------
def _bet_row(b, show_edge=True) -> str:
    conf = b["confidence"]
    color = "var(--edge)" if conf >= 50 else ("var(--accent)" if conf >= 32 else "var(--ink-faint)")
    edge = (f" · <span style='color:var(--edge);'>{b['edge']*100:+.1f} pts edge</span>"
            if show_edge and pd.notna(b["edge"]) and b["edge"] > 0 else "")
    return (f"<div style='border-left:4px solid {color};padding:5px 0 5px 12px;margin:6px 0;'>"
            f"<span style='font-size:1.05rem;font-weight:700;'>{b['selection']}</span> "
            f"<span style='color:var(--ink-faint);'>· {b['market']}</span><br>"
            f"<span style='color:{color};font-weight:600;'>{betengine.confidence_label(conf)} "
            f"({conf:.0f})</span> <span style='color:var(--ink-dim);font-size:0.9rem;'>· "
            f"{b['model_prob']*100:.0f}% to hit · fair {betengine.fmt_odds(b['fair_odds'])}{edge}</span></div>")


def _priced_board(off, deff, extras, row, away, home, sim) -> None:
    from ui.betting import _games_played
    gp = _games_played(extras)
    no_lines = pd.isna(row.get("spread_line")) and pd.isna(row.get("total_line"))
    game_list = [] if no_lines else betengine.game_bets(row, off, deff, extras, gp)
    prop_list = props.prop_bets_for_games(off, deff, extras, pd.DataFrame([row]), gp)
    bets = game_list + prop_list
    if not bets:
        _game_props(off, deff, extras, row)
        return
    safest = sorted(bets, key=lambda b: b["model_prob"], reverse=True)[:3]
    edges = [b for b in sorted(bets, key=lambda b: (b["edge"] if pd.notna(b["edge"]) else -1),
                               reverse=True) if pd.notna(b["edge"]) and b["edge"] > 0][:3]
    st.markdown("### Priced board")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Safest** — most likely to cash")
        for b in safest:
            st.markdown(_bet_row(b, show_edge=False), unsafe_allow_html=True)
    with c2:
        st.markdown("**Most edge** — biggest value vs the line")
        if edges:
            for b in edges:
                st.markdown(_bet_row(b), unsafe_allow_html=True)
        else:
            st.info("No +EV bet — the market has this game priced tight.")

    st.markdown("**Same-game parlay** — correlation-priced")
    pool = [b for b in bets if pd.notna(b["edge"]) and b["edge"] > 0] or safest
    legs = pool[:3] if len(pool) >= 2 else []
    if len(legs) >= 2:
        par = betengine.parlay(legs)
        k = st.columns(3)
        k[0].metric("Combined odds", betengine.fmt_odds(par["american"]))
        k[1].metric("Model hit %", f"{par['model_prob']*100:.0f}%")
        k[2].metric("EV / unit", f"{par['ev']*100:+.0f}%")
        st.caption("Legs: " + " + ".join(l["selection"] for l in legs) + " — priced for correlation, not "
                   "naïve multiplication. High variance; keep the ticket small.")
    else:
        st.info("Not enough +EV legs for a parlay in this game.")
    _game_props(off, deff, extras, row)


def _game_props(off, deff, extras, row) -> None:
    from ui.betting import _games_played
    stats = extras.get("players")
    if stats is None or stats.empty:
        return
    board = props.auto_prop_picks(stats, off, deff, extras, pd.DataFrame([row]),
                                  games_played=_games_played(extras))
    if board.empty:
        return
    with st.expander("All player prop leans (full table)"):
        show = board.head(12)[["Player", "Pos", "Team", "Stat", "Side", "Projection",
                               "Baseline", "Hit%", "Matchup", "conf"]].rename(columns={"conf": "Conf"})
        st.dataframe(show, width="stretch", hide_index=True, column_config={
            "Hit%": st.column_config.NumberColumn("Hit%", format="%d%%"),
            "Conf": st.column_config.NumberColumn("Conf", format="%d"),
        })


def _advantage(off, deff, extras, away, home) -> None:
    from data import edges as _edges
    from ui.components import matchup_advantage_grid
    ae = _edges.facet_edges(away, home, off, deff, extras)
    he = _edges.facet_edges(home, away, off, deff, extras)
    if ae or he:
        st.markdown("##### Matchup advantage grid")
        st.markdown(matchup_advantage_grid(away, home, ae, he), unsafe_allow_html=True)


def _breakdown(off, deff, extras, row) -> None:
    away, home = row["away_team"], row["home_team"]
    sim = _gb_header(off, deff, extras, row)
    st.divider()
    _edge_sheet(away, home, off, deff, extras, sim)
    st.divider()
    _advantage(off, deff, extras, away, home)
    st.divider()
    _priced_board(off, deff, extras, row, away, home, sim)


def render(off, deff, blitz, schedule, extras) -> None:
    st.subheader("Game Bets — every edge in one game")
    if off.empty or deff.empty:
        st.warning("Need team data loaded first.")
        return
    season = config.CURRENT_SEASON
    have = schedule is not None and not schedule.empty and (schedule["season"] == season).any()
    if not have:
        st.info("Schedule not loaded for the current season yet.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    cwk, cgm = st.columns([1, 3])
    wk = cwk.selectbox(f"Week ({season})", weeks,
                       index=weeks.index(default_wk) if default_wk in weeks else 0, key="gb_wk")
    games = s[s["week"] == wk].sort_values("gameday" if "gameday" in s.columns else "week")
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    if not labels:
        st.info("No games listed for this week.")
        return
    pick = cgm.selectbox("Game", labels, key="gb_game")
    _breakdown(off, deff, extras, games.iloc[labels.index(pick)])
