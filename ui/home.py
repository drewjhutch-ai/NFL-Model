"""The Home command center — 'This Week'.

The front door. The moment you land you know what matters: how the model is
doing (report card), this week's slate as an edge board, the top plays, and
tickers for line moves and injuries. Every card routes into the deep tab that
owns it. Built entirely on the design kit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from data import betengine, betting, clv as clvmod, history, injuries as injmod, loaders, props
from ui import kit

_BACKTEST_FILE = Path(__file__).resolve().parents[1] / "backtest_results.json"


def _go(section: str, **targets) -> None:
    """Navigate to another section, carrying pre-selection targets, then rerun."""
    st.session_state["_nav_to"] = section
    for k, v in targets.items():
        st.session_state[k] = v
    st.rerun()


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


# --- report card ------------------------------------------------------------
def _report_card(extras) -> None:
    schedule = extras.get("schedule")
    proj = history.load_projections(config.CURRENT_SEASON)
    grade = history.grade_projections(proj, schedule) if not proj.empty else {}
    roi = clvmod.grade_roi(proj, schedule) if not proj.empty else {}
    clv = clvmod.grade_clv(proj, schedule) if not proj.empty else {}
    bt = json.loads(_BACKTEST_FILE.read_text()).get("summary", {}) if _BACKTEST_FILE.exists() else {}

    ats = grade.get("ats") if grade else None
    ats_txt = f"{ats['pct']*100:.0f}%" if ats else (f"{bt['ats_pct']:.0f}%" if bt.get("ats_pct") else "—")
    ats_sub = f"{ats['hit']}/{ats['n']} this yr" if ats else ("backtest" if bt.get("ats_pct") else "no games yet")
    roi_txt = f"{roi['overall']['roi']:+.1f}%" if roi.get("overall") else "—"
    roi_sub = (f"{roi['overall']['units']:+.1f}u" if roi.get("overall") else "fills in-season")
    clv_txt = f"{clv['avg_clv']:+.1f}" if clv else "—"
    clv_sub = f"beat {clv['beat_pct']:.0f}%" if clv else "closing-line value"
    mae_txt = f"{bt['model_mae']:.1f}" if bt.get("model_mae") else "—"
    mae_sub = (f"mkt {bt['market_mae']:.1f}" if bt.get("market_mae") else "margin error")

    c = st.columns(4)
    with c[0]:
        st.markdown(kit.kpi("Against the spread", ats_txt, ats_sub, "up" if ats else None,
                            "edge"), unsafe_allow_html=True)
    with c[1]:
        st.markdown(kit.kpi("ROI", roi_txt, roi_sub,
                            "up" if roi.get("overall", {}).get("roi", 0) > 0 else None, "accent"),
                    unsafe_allow_html=True)
    with c[2]:
        st.markdown(kit.kpi("Avg CLV", clv_txt, clv_sub, "up" if clv else None, "sharp"),
                    unsafe_allow_html=True)
    with c[3]:
        st.markdown(kit.kpi("Margin error", mae_txt, mae_sub, None, "violet"),
                    unsafe_allow_html=True)


# --- slate edge board -------------------------------------------------------
def _logo(meta, team) -> str:
    m = meta.get(team, {})
    if m.get("logo"):
        return f'<img src="{m["logo"]}" alt="{team}">'
    return ""


def _slate(off, deff, schedule, extras, meta, games, wk) -> None:
    st.markdown("### This week's slate")
    st.caption("Every game: our projected line vs the market, the edge, and a confidence read. "
               "**Click a game below** to open its full breakdown in Matchups.")
    rows = []
    for _, r in games.iterrows():
        a = betting.assess(r, off, deff, extras)
        if pd.isna(a["model_margin"]):
            continue
        rows.append((r, a))
    if not rows:
        st.info("Projections appear here once the slate and lines are posted.")
        return
    # sort by |edge| when present, else by confidence
    rows.sort(key=lambda x: (abs(x[1]["edge_pts"]) if pd.notna(x[1]["edge_pts"]) else -1,
                             x[1]["confidence"]), reverse=True)

    st.markdown('<div class="k-ghead"><span>Matchup</span><span>Model line</span>'
                '<span>Market</span><span>Edge · confidence</span></div>', unsafe_allow_html=True)
    html = ['<div class="k-slate">']
    for r, a in rows:
        away, home = a["away"], a["home"]
        fav = a["our_fav"] or home
        model_line = betting.fmt_line(fav, a["model_margin"])
        mkt = (betting.fmt_line(a["mkt_fav"], a["mkt_spread"])
               if pd.notna(a["mkt_spread"]) and a["mkt_fav"] else "—")
        ep = a["edge_pts"]
        edge_chip = (kit.chip(f"{ep:+.1f} {a['value_side']}", "edge" if ep > 0 else "fade")
                     if pd.notna(ep) and a.get("value_side") else kit.chip("no edge", "mute"))
        pin = {"High": 86, "Medium": 58, "Low": 32}.get(a["confidence"], 10)
        matchup = (f'<div class="mu">{_logo(meta, away)} {away} '
                   f'<span class="at">@</span> {_logo(meta, home)} {home}</div>')
        html.append(
            f'<div class="k-game">{matchup}'
            f'<div class="ln">{model_line}<br><span class="mut">{a["model_p_home"]*100:.0f}% {home}</span></div>'
            f'<div class="ln">{mkt}</div>'
            f'<div>{edge_chip}<div class="mini" style="margin-top:6px">'
            f'<span class="pin" style="left:{pin:.0f}%"></span></div></div></div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    # clickable jump row — one button per game → the game in Matchups, pre-selected
    st.caption("Open a matchup →")
    per_row = 3
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, (r, a) in zip(cols, rows[i:i + per_row]):
            label = f"{a['away']} @ {a['home']}"
            if col.button(label, key=f"slate_go_{a['away']}_{a['home']}",
                          use_container_width=True):
                _go("Matchups", mu_jump_week=int(wk), mu_jump_game=label)


# --- top plays --------------------------------------------------------------
def _top_plays(off, deff, schedule, extras, games, gp, wk) -> None:
    st.markdown("### Top plays")
    st.caption("Highest-conviction bets on the board — any market. Click one for its game, "
               "or open the full card in Picks.")
    priced = games[games["spread_line"].notna()] if "spread_line" in games.columns else games.iloc[0:0]
    board_rows = []
    for _, r in priced.iterrows():
        board_rows.extend(betengine.game_bets(r, off, deff, extras, gp))
    board = pd.DataFrame(board_rows) if board_rows else pd.DataFrame()
    stats = extras.get("players")
    prop_df = (props.auto_prop_picks(stats, off, deff, extras, games, games_played=gp)
               if stats is not None and not stats.empty else pd.DataFrame())
    prop_bets = props.leans_to_bets(prop_df, gp)
    if prop_bets:
        board = pd.concat([board, pd.DataFrame(prop_bets)], ignore_index=True)
    if board.empty:
        st.info("Top plays populate once game lines are posted.")
        return
    view = board.sort_values("confidence", ascending=False).head(5)
    for idx, b in view.reset_index(drop=True).iterrows():
        conf = b["confidence"]
        col = "edge" if conf >= 50 else ("sharp" if conf >= 32 else "accent")
        accent = {"edge": "var(--edge)", "sharp": "var(--sharp)", "accent": "var(--accent)"}[col]
        edge_txt = f"{b['edge']*100:+.1f}% edge" if pd.notna(b.get("edge")) else ""
        st.markdown(
            f'<div class="k-bet" style="--kbet:{accent}">'
            f'<div class="sel">{b["selection"]} {kit.chip(betengine.confidence_label(conf), col)}</div>'
            f'<div class="meta">{b["market"]} · {b["game"]}</div>'
            f'<div class="row"><span class="mono">{b["model_prob"]*100:.0f}%</span>'
            f'<span class="mono">fair {betengine.fmt_odds(b["fair_odds"])}</span>'
            f'<span style="color:var(--ink-faint)">{edge_txt}</span></div></div>',
            unsafe_allow_html=True)
        game = str(b.get("game", ""))
        if " @ " in game and st.button(f"→ {game}", key=f"play_go_{idx}", use_container_width=True):
            _go("Matchups", mu_jump_week=int(wk), mu_jump_game=game)
    if st.button("Full card in Picks of the Week →", key="open_picks",
                 use_container_width=True):
        _go("Picks of the Week")


# --- tickers ----------------------------------------------------------------
def _injury_pulse(extras, meta) -> None:
    st.markdown("### Injury pulse")
    imap = extras.get("injuries") or {}
    # Year-round now: IR / PUP / suspensions from the live feed, plus the weekly
    # game report once the season starts. Rank absences first, by point-dock.
    from data import injury_value
    items = []
    for team, lst in imap.items():
        for p in lst:
            pts = injury_value.player_value(p.get("pos", ""), p.get("pct"), p.get("status", ""),
                                            p.get("practice", ""), p.get("weeks_lingering", 0))
            items.append((team, p, pts))
    if not items:
        st.caption("No injuries on the board yet — the feed fills in as designations post.")
        if st.button("Open Injuries →", key="open_inj_empty", use_container_width=True):
            _go("Injuries")
        return
    items.sort(key=lambda x: (injmod.STATUS_ORDER.get(x[1]["status"], 9), -x[2]))
    tone = {"Out": "var(--fade)", "IR": "var(--fade)", "Doubtful": "var(--sharp)",
            "PUP": "var(--sharp)", "Suspended": "var(--sharp)", "Questionable": "var(--sharp)"}
    html = ['<div class="k-tick">']
    for team, p, pts in items[:6]:
        c = tone.get(p["status"], "var(--ink-faint)")
        dock = f' · −{pts:.1f}' if pts >= 0.1 else ""
        html.append(
            f'<div class="it"><span class="dot" style="background:{c}"></span>'
            f'<span class="t"><b>{team}</b> {p["name"]} <span style="color:var(--ink-faint)">'
            f'{p.get("pos","")}</span></span>'
            f'<span class="s">{p["status"]}{dock}</span></div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    if st.button("Open Injuries →", key="open_inj", use_container_width=True):
        _go("Injuries")


def _line_moves(games, meta) -> None:
    st.markdown("### Biggest line moves")
    from data import odds_providers as op
    prov = op.get_odds_provider()
    if not prov.is_available():
        st.caption("Waiting on live odds — line movement needs an Odds-API key and in-season "
                   "snapshots to compare open→now. It fills in once games are on the board.")
        if st.button("Open Betting desk →", key="open_bet_nokey", use_container_width=True):
            _go("Betting")
        return
    moves = []
    for _, r in games.iterrows():
        mv = prov.movement(r["away_team"], r["home_team"])
        if mv and abs(mv.get("delta", 0)) >= 0.5:
            moves.append((r["away_team"], r["home_team"], mv))
    if not moves:
        st.caption("No significant moves yet — the market's quiet (movement builds through the week).")
        if st.button("Open Betting desk →", key="open_bet_quiet", use_container_width=True):
            _go("Betting")
        return
    moves.sort(key=lambda x: abs(x[2]["delta"]), reverse=True)
    html = ['<div class="k-tick">']
    for away, home, mv in moves[:6]:
        d = mv["delta"]
        c = "var(--edge)" if d > 0 else "var(--fade)"
        html.append(
            f'<div class="it"><span class="dot" style="background:{c}"></span>'
            f'<span class="t">{away} @ {home}</span>'
            f'<span class="s">{mv["open_spread"]:+.1f} → {mv["current_spread"]:+.1f} ({d:+.1f})</span></div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    if st.button("Open Betting desk →", key="open_bet", use_container_width=True):
        _go("Betting")


# --- entry ------------------------------------------------------------------
def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict, live: bool) -> None:
    if off.empty or deff.empty:
        st.info("Load data first — the command center needs offensive & defensive numbers.")
        return
    _report_card(extras)
    st.divider()

    season = config.CURRENT_SEASON
    meta = loaders.team_meta()
    gp = _games_played(extras)
    has_slate = (schedule is not None and not schedule.empty
                 and (schedule["season"] == season).any())
    if not has_slate:
        st.info("The weekly slate appears once the current-season schedule is posted.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0, key="home_week")
    games = s[s["week"] == wk]

    left, right = st.columns([1.55, 1])
    with left:
        _slate(off, deff, schedule, extras, meta, games, wk)
    with right:
        _top_plays(off, deff, schedule, extras, games, gp, wk)
    st.divider()
    a, b = st.columns(2)
    with a:
        _injury_pulse(extras, meta)
    with b:
        _line_moves(games, meta)
