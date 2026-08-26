"""The 'Betting' tab: a betting board, not a scoreboard.

Every market we can price — spread, total, moneyline (and props via the Bet
Engine) — ranked by edge against the de-vigged line, with a Kelly stake and a
confidence. Plus a sharp-money tracker (line movement, sharp-book signal, and
whether the smart money agrees with our model), closing-line-value tracking, and
the model's own report card from graded results.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from data import betengine, betting, history, loaders
from data import odds_providers as op

_BACKTEST_FILE = Path(__file__).resolve().parents[1] / "backtest_results.json"


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


@st.cache_data(ttl=300, show_spinner="Fetching live odds…")
def _live_odds() -> pd.DataFrame:
    prov = op.get_odds_provider()
    if not prov.is_available():
        return pd.DataFrame()
    try:
        return prov.current()
    except Exception as exc:  # noqa: BLE001
        print(f"[betting] live odds unavailable: {exc}")
        return pd.DataFrame()


def _effective_row(row: pd.Series, live_game: pd.DataFrame) -> pd.Series:
    if live_game is None or live_game.empty:
        return row
    c = op.consensus(live_game)
    r = row.copy()
    if c.get("home_spread") is not None:
        r["spread_line"] = c["home_spread"]
    if c.get("total") is not None:
        r["total_line"] = c["total"]
    if live_game["ml_home"].notna().any():
        r["home_moneyline"] = live_game["ml_home"].median()
    if live_game["ml_away"].notna().any():
        r["away_moneyline"] = live_game["ml_away"].median()
    return r


# --- the edge board ----------------------------------------------------------
def _edge_board(games, off, deff, extras, live, gp) -> None:
    st.markdown("### 📊 The edge board")
    rows = []
    for _, r in games.iterrows():
        lg = live[(live["away"] == r["away_team"]) & (live["home"] == r["home_team"])] \
            if not live.empty else pd.DataFrame()
        rows.extend(betengine.game_bets(_effective_row(r, lg), off, deff, extras, gp))
    if not rows:
        st.info("No priced bets yet for this slate.")
        return
    board = pd.DataFrame(rows)
    c1, c2 = st.columns([2, 1])
    markets = ["All"] + sorted(board["market"].unique())
    mk = c1.selectbox("Market", markets, key="bet_market")
    min_edge = c2.slider("Min edge", 0.0, 0.15, 0.0, 0.01, key="bet_minedge",
                         help="Model probability minus the de-vigged market price.")
    view = board.copy()
    if mk != "All":
        view = view[view["market"] == mk]
    view = view[view["edge"].fillna(-1) >= min_edge].sort_values("edge", ascending=False)
    if view.empty:
        st.info("No bets clear that edge threshold.")
        return
    show = pd.DataFrame({
        "Game": view["game"], "Market": view["market"], "Bet": view["selection"],
        "Model %": (view["model_prob"] * 100).round(0),
        "Fair": view["fair_odds"].map(betengine.fmt_odds),
        "Line": view["market_odds"].map(betengine.fmt_odds),
        "Edge": (view["edge"] * 100).round(1),
        "Conf": view["confidence"].round(0),
        "Kelly": (view["kelly"] * 100).round(1),
    })
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Model %": st.column_config.NumberColumn("Model %", format="%d%%"),
        "Edge": st.column_config.NumberColumn("Edge", format="%+.1f pts",
            help="vs the de-vigged line. Positive = value."),
        "Conf": st.column_config.NumberColumn("Conf", format="%d",
            help="0–100: decisiveness × edge, damped by sample size."),
        "Kelly": st.column_config.NumberColumn("Kelly", format="%.1fu",
            help="Quarter-Kelly units of a 100u bankroll."),
    })
    st.caption("Edge is measured against the **no-vig** price, so value means value vs the true "
               "line. Kelly is conservative quarter-Kelly. Not financial advice.")


# --- sharp-money tracker -----------------------------------------------------
def _sharp_tracker(away, home, live_game, a) -> None:
    st.markdown("##### 🦈 Sharp-money tracker")
    signals = []          # (badge, text)
    prov = op.get_odds_provider()

    # 1) line movement (open -> current), from odds snapshots
    mv = prov.movement(away, home) if prov.is_available() else {}
    move_dir = None
    if mv:
        d = mv["delta"]
        if abs(d) >= 0.5:
            move_dir = home if d > 0 else away
            signals.append(("STEAM" if abs(d) >= 1.5 else "MOVE",
                            f"Line moved {mv['open_spread']:+.1f} → {mv['current_spread']:+.1f} "
                            f"(toward **{move_dir}**)"))

    # 2) sharp book vs consensus
    if live_game is not None and not live_game.empty:
        c = op.consensus(live_game)
        if c.get("sharp_spread") is not None and c.get("home_spread") is not None:
            diff = c["sharp_spread"] - c["home_spread"]
            if abs(diff) >= 0.5:
                sb = home if diff > 0 else away
                signals.append(("SHARP", f"Sharp book(s) sit toward **{sb}** "
                                f"({c.get('sharp_book','?')}) vs the consensus"))

    # 3) public % backdoor (manual) → reverse line movement
    with st.expander("Enter public betting % (optional — powers RLM)"):
        pub_home = st.slider(f"% of tickets on {home}", 0, 100, 50, key=f"pub_{away}_{home}")
        if pub_home != 50 and move_dir:
            public_side = home if pub_home > 50 else away
            if move_dir != public_side and abs(pub_home - 50) >= 15:
                signals.append(("RLM", f"**Reverse line movement** — public on {public_side} "
                                f"({pub_home}%) but the line moved to {move_dir}. Classic sharp tell."))

    # 4) model agreement — the gold state
    our = a.get("value_side") or a.get("our_fav")
    if our and (move_dir == our):
        signals.append(("AGREE", f"✅ Sharp money **and our model** both lean **{our}** — "
                        "two independent edges pointing the same way."))

    if not signals:
        if not prov.is_available():
            st.caption("🔌 Connect a live odds feed (ODDS_API_KEY) for line movement & sharp-book "
                       "signals. Our model lean is shown above; enter public % to check for RLM.")
        else:
            st.caption("No sharp signal yet — line is stable and books agree.")
        return
    colors = {"RLM": "#2ecc71", "STEAM": "#2ecc71", "SHARP": "#f1c40f",
              "MOVE": "#9aa0a6", "AGREE": "#2ecc71"}
    for badge, text in signals:
        c = colors.get(badge, "#9aa0a6")
        st.markdown(f"<span style='background:{c};color:#111;border-radius:6px;padding:2px 8px;"
                    f"font-weight:700;font-size:0.72rem;font-family:monospace;'>{badge}</span> "
                    f"{text}", unsafe_allow_html=True)


# --- report card + performance ----------------------------------------------
def _report_card(extras) -> None:
    schedule = extras.get("schedule")
    proj = history.load_projections(config.CURRENT_SEASON)
    grade = history.grade_projections(proj, schedule) if not proj.empty else {}
    with st.expander("🧾 Live report card & backtest (the learning loop)"):
        if grade:
            st.markdown("**This season — our graded picks:**")
            cols = st.columns(len(grade))
            for col, (k, v) in zip(cols, grade.items()):
                col.metric(k.upper(), f"{v['pct']*100:.0f}%", f"{v['hit']}/{v['n']}")
        else:
            st.caption("The live report card fills in as the season's picks are graded "
                       "(the Evolution Engine logs projections each week).")
        if _BACKTEST_FILE.exists():
            data = json.loads(_BACKTEST_FILE.read_text())
            s = data.get("summary", {})
            st.markdown(f"**Out-of-sample backtest — {data.get('season')}** "
                        f"({s.get('games','?')} games)")
            c1, c2, c3, c4 = st.columns(4)
            if s.get("model_mae") is not None:
                c1.metric("Our margin error", f"{s['model_mae']:.1f} pts")
            if s.get("market_mae") is not None:
                c2.metric("Market error", f"{s['market_mae']:.1f} pts")
            if s.get("ats_pct") is not None:
                c3.metric("Raw ATS", f"{s['ats_pct']:.0f}%")
            if s.get("su_pct") is not None:
                c4.metric("Straight-up", f"{s['su_pct']:.0f}%")
            facets = data.get("facets", [])
            if facets:
                st.markdown("**What's working** — facet correlation with real margins vs weight:")
                st.dataframe(pd.DataFrame(facets), width="stretch", hide_index=True)


# --- per-game detail ---------------------------------------------------------
def _spread_str(home, away, home_margin) -> str:
    if pd.isna(home_margin):
        return "—"
    return f"{home} -{home_margin:.1f}" if home_margin >= 0 else f"{away} -{abs(home_margin):.1f}"


def _markets_panel(a) -> None:
    sp, tot, ml = st.columns(3)
    with sp:
        st.markdown("**📐 Spread**")
        st.caption(f"Market: {_spread_str(a['home'], a['away'], a['mkt_spread'])}")
        st.caption(f"Ours: {_spread_str(a['home'], a['away'], a['model_margin'])}")
        if a["value_side"]:
            st.markdown(f"🎯 **{a['value_side']}** (+{abs(a['edge_pts']):.1f}) · conf **{a.get('confidence','—')}**")
        if a.get("key_number"):
            st.caption(f"🔑 crosses the **{a['key_number']}**")
    with tot:
        st.markdown("**🔢 Total**")
        st.caption(f"Market: {a['total_line']:.1f}" if pd.notna(a["total_line"]) else "Market: —")
        st.caption(f"Ours: {a['model_total']:.0f}" if pd.notna(a["model_total"]) else "Ours: —")
        if a["total_side"]:
            st.markdown(f"🎯 **{a['total_side']}** (+{abs(a['total_edge']):.1f})")
    with ml:
        st.markdown("**💵 Moneyline**")
        if pd.notna(a["model_p_home"]):
            st.caption(f"Ours: {a['home']} {a['model_p_home']*100:.0f}% (fair {betting.fair_moneyline(a['model_p_home']):+d})")
        if a["ml_side"]:
            st.markdown(f"🎯 **{a['ml_side']}** (+{abs(a['edge_prob'])*100:.0f}%)")


def _live_section(away, home, live_game) -> None:
    if live_game is None or live_game.empty:
        return
    c = op.consensus(live_game)
    show = live_game[["book", "home_spread", "total", "ml_home", "ml_away"]].copy()
    show = show.rename(columns={"home_spread": f"{home} spread", "ml_home": f"{home} ML",
                                "ml_away": f"{away} ML"})
    with st.expander(f"📈 Line shopping across {c.get('n_books','?')} books"):
        st.dataframe(show.sort_values(f"{home} spread"), width="stretch", hide_index=True)
        if c.get("best_home_spread") is not None:
            cc = st.columns(2)
            cc[0].metric(f"Best {home} number", f"{c['best_home_spread']:+.1f}")
            cc[1].metric(f"Best {away} number", f"{c['best_away_spread']:+.1f}")


def _detail(row, off, deff, extras, live) -> None:
    away, home = row["away_team"], row["home_team"]
    lg = live[(live["away"] == away) & (live["home"] == home)] if not live.empty else pd.DataFrame()
    a = betting.assess(_effective_row(row, lg), off, deff, extras)
    meta = loaders.team_meta()
    c1, cm, c2 = st.columns([5, 1, 5])
    for col, t in ((c1, away), (c2, home)):
        m = meta.get(t, {})
        if m.get("logo"):
            col.image(m["logo"], width=46)
        col.markdown(f"**{m.get('name', t)}**")
    cm.markdown("<div style='text-align:center;margin-top:14px;color:#888;'>@</div>", unsafe_allow_html=True)

    _markets_panel(a)
    if a["disagree"]:
        st.warning(f"⚠️ We favor **{a['our_fav']}**, the market favors **{a['mkt_fav']}**.")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("##### 🔍 Why our number differs")
        if a["why"]:
            for e in a["why"]:
                st.markdown(f"- **{e['label']}** ({e['impact']:+.0f}) · {e['detail']}")
        else:
            st.caption("Efficiency-driven and close to market.")
    with d2:
        st.markdown("##### 🏦 What the market may see")
        if a["context"]:
            for f in a["context"]:
                st.markdown(f"- {f}")
        else:
            st.caption("No obvious injury / rest / weather factors.")
    st.divider()
    _sharp_tracker(away, home, lg, a)
    _live_section(away, home, lg)


def render(off, deff, schedule, extras) -> None:
    st.subheader("Betting — the edge board")
    if off.empty or deff.empty:
        st.warning("Need team data loaded first.")
        return
    season = config.CURRENT_SEASON
    have = (schedule is not None and not schedule.empty
            and (schedule["season"] == season).any()
            and schedule.loc[schedule["season"] == season, "spread_line"].notna().any())
    if not have:
        st.info("No market lines posted yet for the current season. Power ratings still work:")
        st.dataframe(betting.power_ratings(off, deff).sort_values("power_rank")[["net", "power_rank"]],
                     width="stretch")
        return

    live = _live_odds()
    if not live.empty:
        st.caption(f"🟢 Live odds connected ({live['book'].nunique()} books).")
    gp = _games_played(extras)

    s = schedule[(schedule["season"] == season) & schedule["spread_line"].notna()]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0)
    games = s[s["week"] == wk]

    _report_card(extras)
    _edge_board(games, off, deff, extras, live, gp)
    st.divider()
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    pick = st.selectbox("Break down a game", labels)
    _detail(games.iloc[labels.index(pick)], off, deff, extras, live)
