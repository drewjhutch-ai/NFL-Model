"""The 'Game Bets' tab: pick a game, get the model's best bets for it.

The Picks tab ranks the whole slate; this drills into one game the way Matchups
does — select the week and matchup, and the Bet Engine surfaces that game's best
plays in three buckets:

  * Safest — highest model win probability (most likely to cash).
  * Most edge — biggest value vs the de-vigged line.
  * Same-game parlay — the best correlated combo, priced honestly.

When market lines aren't posted yet, it falls back to the model's straight read
(projected score, win %, our number) so the game is never blank.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betengine, betting, loaders, props, simulation
from ui.components import fmt, ordinal


def _banner(away, home, row) -> None:
    meta = loaders.team_meta()
    c1, cm, c2 = st.columns([5, 1, 5])
    for col, t in ((c1, away), (c2, home)):
        m = meta.get(t, {})
        with col:
            if m.get("logo"):
                st.image(m["logo"], width=52)
            st.markdown(f"<b style='border-left:5px solid {m.get('color') or '#1f77b4'};"
                        f"padding-left:8px;'>{m.get('name', t)}</b>", unsafe_allow_html=True)
    cm.markdown("<div style='text-align:center;font-size:1.4rem;margin-top:14px;color:#888;'>@</div>",
                unsafe_allow_html=True)
    if row is not None and pd.notna(row.get("gameday")):
        st.caption(f"{row['gameday']} · Week {int(row['week'])}")


def _bet_row(b, show_edge=True) -> str:
    conf = b["confidence"]
    color = "#2ecc71" if conf >= 50 else ("#f1c40f" if conf >= 32 else "#9aa0a6")
    edge = (f" · <span style='color:#2ecc71;'>{b['edge']*100:+.1f} pts edge</span>"
            if show_edge and pd.notna(b["edge"]) and b["edge"] > 0 else "")
    return (f"<div style='border-left:4px solid {color};padding:5px 0 5px 12px;margin:6px 0;'>"
            f"<span style='font-size:1.05rem;font-weight:700;'>{b['selection']}</span> "
            f"<span style='color:#8a8a8a;'>· {b['market']}</span><br>"
            f"<span style='color:{color};font-weight:600;'>{betengine.confidence_label(conf)} "
            f"({conf:.0f})</span> <span style='color:#9aa0a6;font-size:0.9rem;'>· "
            f"{b['model_prob']*100:.0f}% to hit · fair {betengine.fmt_odds(b['fair_odds'])}{edge}</span></div>")


def _model_read(off, deff, extras, row, away, home) -> None:
    """Fallback when no market line is posted: the straight model projection."""
    sim = simulation.simulate(off, deff, home, away, extras, row)
    if not sim:
        st.info("Not enough data to project this game yet.")
        return
    fav = home if sim["margin_mean"] > 0 else away
    st.markdown(f"#### The model's read")
    k = st.columns(3)
    k[0].metric("Projected score", f"{away} {sim['proj_away']:.0f} – {home} {sim['proj_home']:.0f}")
    k[1].metric(f"{fav} win", f"{max(sim['home_win'],1-sim['home_win'])*100:.0f}%")
    k[2].metric("Model line", betting.fmt_line(fav, abs(sim['margin_mean'])))
    st.caption("Categorized best bets (safest / edge / parlay) unlock once the book posts lines "
               "for this game — then the model prices every market against them.")


def _game_props(off, deff, extras, row) -> None:
    from ui.betting import _games_played
    stats = extras.get("players")
    if stats is None or stats.empty:
        return
    from data import props
    board = props.auto_prop_picks(stats, off, deff, extras, pd.DataFrame([row]),
                                  games_played=_games_played(extras))
    if board.empty:
        return
    st.divider()
    st.markdown("### Player prop leans")
    st.caption("Biggest projection-vs-baseline mismatches in this game — the model bets props too, "
               "not just the big three. Price exact lines in Players → Prop edge finder.")
    show = board.head(6)[["Player", "Pos", "Team", "Stat", "Side", "Projection",
                          "Baseline", "Hit%", "Matchup", "conf"]].rename(columns={"conf": "Conf"})
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Hit%": st.column_config.NumberColumn("Hit%", format="%d%%"),
        "Conf": st.column_config.NumberColumn("Conf", format="%d"),
    })


def _breakdown(off, deff, extras, row) -> None:
    away, home = row["away_team"], row["home_team"]
    _banner(away, home, row)
    st.divider()
    from ui.betting import _games_played
    gp = _games_played(extras)
    no_lines = pd.isna(row.get("spread_line")) and pd.isna(row.get("total_line"))
    game_list = [] if no_lines else betengine.game_bets(row, off, deff, extras, gp)
    prop_list = props.prop_bets_for_games(off, deff, extras, pd.DataFrame([row]), gp)
    bets = game_list + prop_list        # props compete in every bucket
    if no_lines:
        _model_read(off, deff, extras, row, away, home)  # projected-score context
    if not bets:
        _game_props(off, deff, extras, row)
        return

    safest = sorted(bets, key=lambda b: b["model_prob"], reverse=True)[:3]
    edges = [b for b in sorted(bets, key=lambda b: (b["edge"] if pd.notna(b["edge"]) else -1),
                               reverse=True) if pd.notna(b["edge"]) and b["edge"] > 0][:3]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Safest")
        st.caption("Most likely to cash, regardless of price.")
        for b in safest:
            st.markdown(_bet_row(b, show_edge=False), unsafe_allow_html=True)
    with c2:
        st.markdown("### Most edge")
        st.caption("Biggest value vs the de-vigged line.")
        if edges:
            for b in edges:
                st.markdown(_bet_row(b), unsafe_allow_html=True)
        else:
            st.info("No +EV bet in this game — the market has it priced tight.")

    st.divider()
    st.markdown("### Same-game parlay")
    pool = [b for b in bets if pd.notna(b["edge"]) and b["edge"] > 0] or safest
    legs = pool[:3] if len(pool) >= 2 else []
    if len(legs) >= 2:
        par = betengine.parlay(legs)
        k = st.columns(3)
        k[0].metric("Combined odds", betengine.fmt_odds(par["american"]))
        k[1].metric("Model hit %", f"{par['model_prob']*100:.0f}%")
        k[2].metric("EV / unit", f"{par['ev']*100:+.0f}%")
        st.markdown("**Legs:** " + " + ".join(f"{l['selection']}" for l in legs))
        st.caption("These legs share a game, so they're **correlated** — the model prices the joint "
                   "probability accordingly (not naïve multiplication). Same-game parlays are "
                   "high-variance; keep the ticket small.")
    else:
        st.info("Not enough +EV legs in this game for a parlay.")

    _game_props(off, deff, extras, row)


def render(off, deff, blitz, schedule, extras) -> None:
    st.subheader("Game Bets — the model's best plays, one game at a time")
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
