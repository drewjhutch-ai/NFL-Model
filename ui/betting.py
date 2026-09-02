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
from data import betengine, betting, history, loaders, props
from data import odds_providers as op

_BACKTEST_FILE = Path(__file__).resolve().parents[1] / "backtest_results.json"


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


def _live_odds() -> pd.DataFrame:
    from data import odds_feed
    df, _status = odds_feed.fetch()   # shared cache with the CLV tab — one pull, both tabs
    return df


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
    st.markdown("### The ticket board")
    st.caption("Every market we can price — spread, total, moneyline, props — against the no-vig "
               "line, ranked by edge with a Kelly stake. The desk's full order book.")
    rows = []
    for _, r in games.iterrows():
        lg = live[(live["away"] == r["away_team"]) & (live["home"] == r["home_team"])] \
            if not live.empty else pd.DataFrame()
        rows.extend(betengine.game_bets(_effective_row(r, lg), off, deff, extras, gp))
    # player props compete on the same board
    rows.extend(props.prop_bets_for_games(off, deff, extras, games, gp))
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
    st.caption("This board auto-prices the markets that carry posted lines (spread, total, "
               "moneyline). **Player props** surface as leans in the Players & Picks tabs and get "
               "exact edges in the prop finder — the model isn't limited to the big three.")


# --- sharp-money tracker -----------------------------------------------------
_SIGNAL_KIND = {"RLM": "edge", "STEAM": "edge", "AGREE": "edge",
                "SHARP": "sharp", "MOVE": "mute"}
_SIGNAL_DOT = {"RLM": "var(--edge)", "STEAM": "var(--edge)", "AGREE": "var(--edge)",
               "SHARP": "var(--sharp)", "MOVE": "var(--ink-faint)"}


def _compute_signals(away, home, live_game, a, prov, pub_home: int | None = None):
    """Automated sharp-money read for one game from odds snapshots — no paid data.

    Returns (signals, move_dir, agree_side). Each signal is (badge, text, score);
    score ranks the whole slate. Detects: line movement (steam), sharp-book vs
    consensus divergence, reverse line movement (if public % supplied), and the
    gold state where movement and our model agree.
    """
    signals = []
    move_dir = None
    mv = prov.movement(away, home) if prov.is_available() else {}
    if mv:
        d = mv["delta"]
        if abs(d) >= 0.5:
            move_dir = home if d > 0 else away
            steam = abs(d) >= 1.5
            signals.append(("STEAM" if steam else "MOVE",
                            f"Line moved {mv['open_spread']:+.1f} → {mv['current_spread']:+.1f} "
                            f"(toward {move_dir})", (3.0 if steam else 1.2) + abs(d) * 0.3))
    if live_game is not None and not live_game.empty:
        c = op.consensus(live_game)
        if c.get("sharp_spread") is not None and c.get("home_spread") is not None:
            diff = c["sharp_spread"] - c["home_spread"]
            if abs(diff) >= 0.5:
                sb = home if diff > 0 else away
                signals.append(("SHARP", f"Sharp book(s) sit toward {sb} "
                                f"({c.get('sharp_book','?')}) vs consensus", 2.0 + abs(diff) * 0.4))
    if pub_home is not None and pub_home != 50 and move_dir:
        public_side = home if pub_home > 50 else away
        if move_dir != public_side and abs(pub_home - 50) >= 15:
            signals.append(("RLM", f"Reverse line movement — public on {public_side} "
                            f"({pub_home}%) but line moved to {move_dir}. Classic sharp tell.", 4.0))
    our = a.get("value_side") or a.get("our_fav")
    agree_side = None
    if our and move_dir == our:
        agree_side = our
        signals.append(("AGREE", f"Sharp money and our model both lean {our} — "
                        "two independent edges aligned.", 3.5))
    return signals, move_dir, agree_side


def _signal_html(signals) -> str:
    from ui import kit
    rows = []
    for badge, text, _ in signals:
        rows.append(f'<div class="it"><span class="dot" style="background:{_SIGNAL_DOT.get(badge,"var(--ink-faint)")}"></span>'
                    f'{kit.chip(badge, _SIGNAL_KIND.get(badge, "mute"))}'
                    f'<span class="t">{text}</span></div>')
    return f'<div class="k-tick">{"".join(rows)}</div>'


def _sharp_tracker(away, home, live_game, a) -> None:
    st.markdown("##### Sharp-money tracker")
    prov = op.get_odds_provider()
    pub_home = None
    with st.expander("Enter public betting % (optional — powers RLM)"):
        pub_home = st.slider(f"% of tickets on {home}", 0, 100, 50, key=f"pub_{away}_{home}")
    signals, *_ = _compute_signals(away, home, live_game, a, prov, pub_home)
    if not signals:
        if not prov.is_available():
            st.caption("Connect a live odds feed (ODDS_API_KEY in Streamlit secrets) for line "
                       "movement & sharp-book signals. Model lean is shown above; enter public % for RLM.")
        else:
            st.caption("No sharp signal yet — line is stable and books agree.")
        return
    st.markdown(_signal_html(signals), unsafe_allow_html=True)


# --- report card + performance ----------------------------------------------
def _self_tuning() -> None:
    from data import tuning
    t = tuning.load()
    st.markdown("**Self-tuning** — the model re-fits itself from results each week.")
    if not t:
        st.caption(f"Holding safe defaults · points-blend **{config.POINTS_WEIGHT:.2f}**. "
                   "The weekly Action starts re-fitting once the season has enough graded games.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Points blend", f"{config.POINTS_WEIGHT:.2f}",
              help="EPA↔scoreboard weight, learned from the backtest.")
    c2.metric("Learned from", f"{t.get('graded_games','?')} games")
    c3.metric("As of", str(t.get("as_of", "—")))
    log = tuning.load_log()
    if not log.empty:
        st.caption("Tuning history:")
        st.dataframe(log.tail(8), width="stretch", hide_index=True)


def _facet_review() -> None:
    """The auditable half of the loop: which flagged mismatches actually hit."""
    from data import review as reviewmod
    rlog = reviewmod.load_review_log()
    st.markdown("**Game review** — for every facet edge we flagged, did the flagged side win?")
    if rlog.empty or "as_of" not in rlog.columns:
        st.caption("Per-facet hit rates fill in after the weekly review Action runs on played games "
                   "(cross-references each mismatch against the result).")
        return
    latest = rlog[rlog["as_of"] == rlog["as_of"].max()]
    latest = latest.dropna(subset=["facet"]).sort_values("hit_rate", ascending=False)
    if latest.empty:
        st.caption("No graded facets in the latest review yet.")
        return
    show = latest[["facet", "n_flagged", "hit_rate", "correlation"]].rename(columns={
        "facet": "Facet", "n_flagged": "Flagged", "hit_rate": "Hit %", "correlation": "r"})
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Hit %": st.column_config.NumberColumn("Hit %", format="%.0f%%",
            help="Of games where this facet flagged a side, how often that side won."),
    })
    st.caption("This is how the loop stays honest — a facet that stops hitting gets down-weighted "
               "automatically by the self-tuner. 50% = coin flip.")


def _report_card(extras) -> None:
    schedule = extras.get("schedule")
    proj = history.load_projections(config.CURRENT_SEASON)
    grade = history.grade_projections(proj, schedule) if not proj.empty else {}
    from data import clv as clvmod
    roi = clvmod.grade_roi(proj, schedule) if not proj.empty else {}
    clv = clvmod.grade_clv(proj, schedule) if not proj.empty else {}
    with st.expander("Live report card, self-tuning & backtest (the learning loop)"):
        _self_tuning()
        st.divider()
        _facet_review()
        st.divider()
        if grade:
            st.markdown("**This season — our graded picks:**")
            cols = st.columns(len(grade))
            for col, (k, v) in zip(cols, grade.items()):
                col.metric(k.upper(), f"{v['pct']*100:.0f}%", f"{v['hit']}/{v['n']}")
        else:
            st.caption("The live report card fills in as the season's picks are graded "
                       "(the Evolution Engine logs projections each week).")
        if roi.get("overall") or clv:
            st.markdown("**Profit & closing-line value** — the scoreboard that matters:")
            c = st.columns(3)
            if roi.get("overall"):
                o = roi["overall"]
                c[0].metric("ROI", f"{o['roi']:+.1f}%", f"{o['units']:+.1f}u / {o['bets']} bets")
            if clv:
                c[1].metric("Avg CLV", f"{clv['avg_clv']:+.1f} pts",
                            help="Points we beat the closing line by — the best sign of a real edge.")
                c[2].metric("Beat the close", f"{clv['beat_pct']:.0f}%", f"{clv['n']} picks")
            st.caption("ROI settles spread/total picks at -110. CLV compares the number we captured "
                       "(logged at pick time) to the closing line. Both fill in as the season plays.")
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
        st.markdown("**Spread**")
        st.caption(f"Market: {_spread_str(a['home'], a['away'], a['mkt_spread'])}")
        st.caption(f"Ours: {_spread_str(a['home'], a['away'], a['model_margin'])}")
        if a["value_side"]:
            st.markdown(f"**{a['value_side']}** (+{abs(a['edge_pts']):.1f}) · conf **{a.get('confidence','—')}**")
        if a.get("key_number"):
            st.caption(f"crosses the **{a['key_number']}**")
    with tot:
        st.markdown("**Total**")
        st.caption(f"Market: {a['total_line']:.1f}" if pd.notna(a["total_line"]) else "Market: —")
        st.caption(f"Ours: {a['model_total']:.0f}" if pd.notna(a["model_total"]) else "Ours: —")
        if a["total_side"]:
            st.markdown(f"**{a['total_side']}** (+{abs(a['total_edge']):.1f})")
    with ml:
        st.markdown("**Moneyline**")
        if pd.notna(a["model_p_home"]):
            st.caption(f"Ours: {a['home']} {a['model_p_home']*100:.0f}% (fair {betting.fair_moneyline(a['model_p_home']):+d})")
        if a["ml_side"]:
            st.markdown(f"**{a['ml_side']}** (+{abs(a['edge_prob'])*100:.0f}%)")


def _live_section(away, home, live_game) -> None:
    if live_game is None or live_game.empty:
        return
    c = op.consensus(live_game)
    show = live_game[["book", "home_spread", "total", "ml_home", "ml_away"]].copy()
    show = show.rename(columns={"home_spread": f"{home} spread", "ml_home": f"{home} ML",
                                "ml_away": f"{away} ML"})
    with st.expander(f"Line shopping across {c.get('n_books','?')} books"):
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
        st.warning(f"We favor **{a['our_fav']}**, the market favors **{a['mkt_fav']}**.")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("##### Why our number differs")
        if a["why"]:
            for e in a["why"]:
                st.markdown(f"- **{e['label']}** ({e['impact']:+.0f}) · {e['detail']}")
        else:
            st.caption("Efficiency-driven and close to market.")
    with d2:
        st.markdown("##### What the market may see")
        if a["context"]:
            for f in a["context"]:
                st.markdown(f"- {f}")
        else:
            st.caption("No obvious injury / rest / weather factors.")
    st.divider()
    _game_props(off, deff, extras, row)
    _sharp_tracker(away, home, lg, a)
    _live_section(away, home, lg)


def _game_props(off, deff, extras, row) -> None:
    from ui.betting import _games_played  # local: reuse the helper above
    bets = props.prop_bets_for_games(off, deff, extras, pd.DataFrame([row]),
                                     _games_played(extras))
    if not bets:
        return
    st.markdown("##### Player props in this game")
    top = sorted(bets, key=lambda b: (b["edge"] if pd.notna(b["edge"]) else -1), reverse=True)[:6]
    show = pd.DataFrame({
        "Prop": [b["selection"] for b in top],
        "Model %": [round(b["model_prob"] * 100) for b in top],
        "Fair": [betengine.fmt_odds(b["fair_odds"]) for b in top],
        "Edge %": [round(b["edge"] * 100, 1) if pd.notna(b["edge"]) else None for b in top],
        "Conf": [round(b["confidence"]) for b in top],
    })
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption("Projection-based leans at a baseline line — enter the book's number in "
               "Players → Prop edge finder for exact edge.")


# --- market desk: slate scan + header + boards -------------------------------
def _scan_slate(games, off, deff, extras, live, prov) -> list[dict]:
    """One market read per game: model vs line, edge, and automated sharp signals."""
    scan = []
    for _, r in games.iterrows():
        away, home = r["away_team"], r["home_team"]
        lg = live[(live["away"] == away) & (live["home"] == home)] \
            if live is not None and not live.empty else pd.DataFrame()
        a = betting.assess(_effective_row(r, lg), off, deff, extras)
        signals, move_dir, agree = _compute_signals(away, home, lg, a, prov)
        mm = a.get("blended_margin")
        if pd.isna(mm):
            mm = a.get("model_margin")
        scan.append({
            "away": away, "home": home, "a": a, "signals": signals,
            "move_dir": move_dir, "agree": agree,
            "model_margin": mm, "mkt_spread": a.get("mkt_spread"),
            "edge": a.get("edge_pts"), "value_side": a.get("value_side"),
            "top_score": max((s[2] for s in signals), default=0.0),
        })
    return scan


def _desk_header(scan, live) -> None:
    from ui import kit
    n_books = int(live["book"].nunique()) if live is not None and not live.empty else 0
    n_sig = sum(1 for g in scan if g["signals"])
    n_agree = sum(1 for g in scan if g["agree"])
    biggest = max(scan, key=lambda g: g["top_score"], default=None)
    k = st.columns(4)
    k[0].markdown(kit.kpi("Books live", str(n_books) if n_books else "—",
                          "line-shopping" if n_books else "no feed", None,
                          "accent" if n_books else "mute"), unsafe_allow_html=True)
    k[1].markdown(kit.kpi("Sharp signals", str(n_sig), "games moving", None,
                          "sharp" if n_sig else "mute"), unsafe_allow_html=True)
    k[2].markdown(kit.kpi("Model + market", str(n_agree), "aligned leans", None,
                          "edge" if n_agree else "mute"), unsafe_allow_html=True)
    if biggest and biggest["signals"]:
        b = biggest["signals"][0]
        k[3].markdown(kit.kpi("Top move", f"{biggest['away']}@{biggest['home']}",
                              b[0], "up", "violet"), unsafe_allow_html=True)
    else:
        k[3].markdown(kit.kpi("Top move", "—", "stable board", None, "mute"),
                      unsafe_allow_html=True)
    _quota_caption()


def _quota_caption() -> None:
    q = op.quota()
    rem = q.get("remaining")
    if rem is None:
        return
    cost = q.get("last_cost")
    extra = f" · last pull cost {cost}" if cost else ""
    warn = "  ⚠️ running low — pulls pause below 30" if rem < 60 else ""
    st.caption(f"Odds-API credits remaining this month: **{rem:,}**{extra}. "
               f"Betting & CLV share one 10-min cache, so both tabs cost a single pull.{warn}")


def _sharp_board(scan, prov) -> None:
    st.markdown("### Sharp-money board")
    st.caption("Automated from odds snapshots — steam, reverse line movement, and sharp-book "
               "divergence, ranked by signal. No paid handle data: the tape tells the story.")
    live_games = [g for g in scan if g["signals"]]
    if not live_games:
        if not prov.is_available():
            st.info("The sharp board runs on a live odds feed. Add **ODDS_API_KEY** to Streamlit "
                    "secrets (free tier at the-odds-api.com) — the model snapshots each pull and "
                    "builds line-movement, steam, and RLM signals automatically. The Model-vs-market "
                    "map below works right now on the posted line.")
        else:
            st.info("No sharp signals yet — the board is stable and books agree. Movement builds "
                    "as snapshots accumulate through the week.")
        return
    live_games.sort(key=lambda g: g["top_score"], reverse=True)
    for g in live_games:
        head = (f"**{g['away']} @ {g['home']}**"
                + (f" · model likes **{g['value_side']}** {g['edge']:+.1f}" if g["value_side"]
                   and pd.notna(g["edge"]) else ""))
        st.markdown(head)
        st.markdown(_signal_html([(b, t, s) for b, t, s in g["signals"]]),
                    unsafe_allow_html=True)


def _market_map(scan) -> None:
    from ui import kit
    st.markdown("### Model vs market map")
    st.caption("Where our number most disagrees with the posted line — the desk's mispricings. "
               "A ✓ means sharp money is moving the same way we lean (the strongest state).")
    rated = [g for g in scan if pd.notna(g.get("edge")) and g.get("value_side")]
    if not rated:
        st.caption("No priced disagreements on this slate yet.")
        return
    rated.sort(key=lambda g: abs(g["edge"]), reverse=True)
    maxabs = max(6.0, max(abs(g["edge"]) for g in rated))
    rows = []
    for g in rated:
        side = g["value_side"]
        agree = " ✓" if g["agree"] == side else ""
        detail = f"vs {_spread_str(g['home'], g['away'], g['mkt_spread'])}" if pd.notna(g["mkt_spread"]) else ""
        rows.append(kit.diverging_bar(f"{g['away']}@{g['home']} → {side}{agree}",
                                      g["edge"], maxabs, detail))
    st.markdown('<div class="k-splits">' + "".join(rows) + "</div>", unsafe_allow_html=True)


def render(off, deff, schedule, extras) -> None:
    st.subheader("Betting — the market desk")
    st.caption("The market's-eye view: where lines are moving, where sharp money sits, and where "
               "our number disagrees with the book. Game-by-game bets live in **Game Bets**; the "
               "model's top plays live in **Picks** — this desk watches the market itself.")
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
    gp = _games_played(extras)
    prov = op.get_odds_provider()

    s = schedule[(schedule["season"] == season) & schedule["spread_line"].notna()]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0)
    games = s[s["week"] == wk]

    scan = _scan_slate(games, off, deff, extras, live, prov)
    _desk_header(scan, live)
    st.divider()
    _sharp_board(scan, prov)
    st.divider()
    _market_map(scan)
    st.divider()
    _edge_board(games, off, deff, extras, live, gp)
    st.divider()
    _report_card(extras)
    st.divider()
    st.markdown("### Single-game market read")
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    pick = st.selectbox("Break down a game", labels)
    _detail(games.iloc[labels.index(pick)], off, deff, extras, live)
