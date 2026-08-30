"""The 'Picks of the Week' tab — three sections.

  1. Most Edge — every priced bet ranked by edge vs the de-vigged line.
  2. Parlay Builder — 3-to-7-leg parlays from the top +EV legs, priced with
     correlation awareness (same-game legs don't multiply as if independent).
  3. Confidence Straights — the 3–8 bets the model is most confident in, any
     market, any price.

Every bet type the Bet Engine can price competes here — moneyline, spread,
total (and player props once lines are supplied). Confidence is calibrated
probability × edge, not the odds.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betengine, loaders, props


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


def _board(games, off, deff, extras, gp) -> pd.DataFrame:
    rows = []
    for _, r in games.iterrows():
        rows.extend(betengine.game_bets(r, off, deff, extras, gp))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _most_likely(board) -> None:
    st.markdown("### Favorites — most likely to hit")
    st.caption("The model's highest win-probability plays this week, **regardless of price or value** "
               "— purely what's most likely to cash. Any market.")
    view = board.sort_values("model_prob", ascending=False).head(8)
    if view.empty:
        st.info("No priced bets to rank yet.")
        return
    show = pd.DataFrame({
        "Bet": view["selection"], "Market": view["market"], "Game": view["game"],
        "Hit %": (view["model_prob"] * 100).round(0),
        "Fair": view["fair_odds"].map(betengine.fmt_odds),
        "Line": view["market_odds"].map(betengine.fmt_odds),
    })
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Hit %": st.column_config.NumberColumn("Hit %", format="%d%%",
            help="Model probability the bet cashes — sorted highest first, value ignored."),
    })
    st.caption("These are chalk by design — high hit-rate, low payout. Great parlay anchors; "
               "for value, see Most Edge below.")


def _most_edge(board) -> None:
    st.markdown("### Most edge")
    st.caption("The pure +EV board — model probability minus the de-vigged market price, any market.")
    view = board[board["edge"].fillna(-1) > 0].sort_values("edge", ascending=False).head(12)
    if view.empty:
        st.info("No +EV bets on the board this week.")
        return
    show = pd.DataFrame({
        "Bet": view["selection"], "Market": view["market"], "Game": view["game"],
        "Model %": (view["model_prob"] * 100).round(0),
        "Fair": view["fair_odds"].map(betengine.fmt_odds),
        "Line": view["market_odds"].map(betengine.fmt_odds),
        "Edge %": (view["edge"] * 100).round(1),
        "Kelly": (view["kelly"] * 100).round(1),
    })
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Edge %": st.column_config.NumberColumn("Edge %", format="%+.1f"),
        "Kelly": st.column_config.NumberColumn("Kelly", format="%.1fu"),
    })


def _parlays(board) -> None:
    st.markdown("### Parlay builder")
    st.caption("Built only from +EV legs, then priced for correlation — same-game legs don't "
               "multiply as if independent. Parlays are high-variance; size tiny.")
    legs_pool = board[board["edge"].fillna(-1) > 0].sort_values("edge", ascending=False)
    # diversify: prefer one leg per game first (lower correlation), then fill
    seen, primary, extra = set(), [], []
    for _, b in legs_pool.iterrows():
        (primary if b["corr_group"] not in seen else extra).append(b)
        seen.add(b["corr_group"])
    ordered = primary + extra
    if len(ordered) < 3:
        st.info("Need at least 3 +EV legs to build a parlay — not enough edge on the board yet.")
        return
    rows, details = [], {}
    for k in range(3, 8):
        if len(ordered) < k:
            break
        legs = ordered[:k]
        par = betengine.parlay(legs)
        rows.append({
            "Parlay": f"{k}-leg",
            "Combined": betengine.fmt_odds(par["american"]),
            "Model hit %": round(par["model_prob"] * 100, 1),
            "EV": round(par["ev"] * 100, 1),
            "Kelly": round(par["kelly"] * 100, 2),
            "Same-game legs": par["same_game_legs"],
        })
        details[f"{k}-leg"] = legs
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
        "Model hit %": st.column_config.NumberColumn("Model hit %", format="%.1f%%"),
        "EV": st.column_config.NumberColumn("EV", format="%+.1f%%",
            help="Expected value per unit staked, using the model's joint probability."),
        "Kelly": st.column_config.NumberColumn("Kelly", format="%.2fu"),
    })
    for name, legs in details.items():
        with st.expander(f"{name} — the legs"):
            st.dataframe(pd.DataFrame({
                "Leg": [l["selection"] for l in legs],
                "Market": [l["market"] for l in legs],
                "Game": [l["game"] for l in legs],
                "Model %": [round(l["model_prob"] * 100) for l in legs],
                "Odds": [betengine.fmt_odds(l["market_odds"]) for l in legs],
            }), width="stretch", hide_index=True)
    st.caption("Combined odds compound the price; EV uses the model's correlation-adjusted joint "
               "probability. A positive EV parlay is rare and worth a small ticket — not the bankroll.")


def _confidence(board, gp) -> None:
    st.markdown("### Confidence straights")
    note = "" if gp > 0 else " _(offseason: ranked off the phantom baseline)_"
    st.caption(f"The 3–8 straights the model is most confident in — any market, any price. "
               f"Confidence = decisiveness × edge, damped by sample size.{note}")
    view = board.sort_values("confidence", ascending=False)
    view = view[view["confidence"] > 0].head(8)
    if len(view) < 3:
        view = board.sort_values("confidence", ascending=False).head(3)
    if view.empty:
        st.info("No confident straights yet.")
        return
    meta = loaders.team_meta()
    for _, b in view.iterrows():
        conf = b["confidence"]
        label = betengine.confidence_label(conf)
        color = "#2ecc71" if conf >= 50 else ("#f1c40f" if conf >= 32 else "#9aa0a6")
        edge_txt = f"{b['edge']*100:+.1f} pts edge" if pd.notna(b["edge"]) else ""
        st.markdown(
            f"<div style='border-left:4px solid {color};padding:6px 0 6px 12px;margin:7px 0;'>"
            f"<span style='font-size:1.05rem;font-weight:700;'>{b['selection']}</span> "
            f"<span style='color:#8a8a8a;'>· {b['market']} · {b['game']}</span><br>"
            f"<span style='color:{color};font-weight:600;'>{label} ({conf:.0f})</span> "
            f"<span style='color:#9aa0a6;font-size:0.9rem;'>· {b['model_prob']*100:.0f}% "
            f"· fair {betengine.fmt_odds(b['fair_odds'])} · {edge_txt} · {b['rationale']}</span></div>",
            unsafe_allow_html=True)
    st.caption("Not chosen for odds — a −180 favorite and a +150 dog can both rank high. "
               "The model's best guesses, whatever the market.")


def _prop_leans(prop_df) -> None:
    st.markdown("### Player prop leans")
    st.caption("The strongest player-prop mismatches for the slate (projection vs baseline). These "
               "also compete in Most Edge, Parlays, and Confidence above. Price the exact line in "
               "Players → Prop edge finder.")
    if prop_df is None or prop_df.empty:
        st.info("No prop leans surfaced for this slate.")
        return
    show = prop_df.head(10)[["Player", "Pos", "Team", "Stat", "Side", "Projection",
                             "Baseline", "Hit%", "Matchup", "conf"]].rename(columns={"conf": "Conf"})
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Hit%": st.column_config.NumberColumn("Hit%", format="%d%%"),
        "Conf": st.column_config.NumberColumn("Conf", format="%d"),
    })


def _pick_log() -> None:
    with st.expander("Your pick log"):
        if "picks" not in st.session_state:
            st.session_state["picks"] = []
        with st.form("add_pick", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            game = c1.text_input("Game / player", placeholder="KC @ BUF — Kelce over 60.5")
            pick = c2.text_input("Your pick", placeholder="Kelce OVER")
            conf = c3.selectbox("Confidence", ["★", "★★", "★★★"], index=1)
            notes = st.text_input("Why (optional)")
            if st.form_submit_button("Add pick") and (game or pick):
                st.session_state["picks"].append(
                    {"Game/Player": game, "Pick": pick, "Confidence": conf, "Notes": notes})
        picks = st.session_state["picks"]
        if not picks:
            st.caption("No picks logged yet.")
            return
        df = pd.DataFrame(picks)
        st.dataframe(df, width="stretch", hide_index=True)
        c1, c2 = st.columns([1, 5])
        c1.download_button("Export CSV", df.to_csv(index=False).encode(),
                           file_name="my_picks.csv", mime="text/csv")
        if c2.button("Clear all"):
            st.session_state["picks"] = []
            st.rerun()


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Picks of the Week")
    st.caption("Everything a book offers is fair game — moneyline, spread, totals, and player props "
               "all compete on one board.")
    if off.empty or deff.empty:
        st.info("Load data first (needs offensive & defensive numbers).")
        return
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded for the current season yet.")
        _pick_log()
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0, key="picks_week")
    games = s[s["week"] == wk]
    gp = _games_played(extras)
    # game-market board needs posted lines; prop leans do not — merge both so
    # every bet type competes for Most Edge, Parlays, and Confidence.
    priced = games[games["spread_line"].notna()] if "spread_line" in games.columns else games.iloc[0:0]
    board = _board(priced, off, deff, extras, gp) if not priced.empty else pd.DataFrame()
    stats = extras.get("players")
    prop_df = (props.auto_prop_picks(stats, off, deff, extras, games, games_played=gp)
               if stats is not None and not stats.empty else pd.DataFrame())
    prop_bets = props.leans_to_bets(prop_df, gp)
    if prop_bets:
        board = pd.concat([board, pd.DataFrame(prop_bets)], ignore_index=True)

    if not board.empty:
        _most_likely(board)
        st.divider()
        _most_edge(board)
        st.divider()
        _parlays(board)
        st.divider()
        _confidence(board, gp)
    else:
        st.info("No priced bets yet — game lines aren't posted and no player data for props.")
    st.divider()
    _prop_leans(prop_df)
    st.divider()
    _pick_log()
