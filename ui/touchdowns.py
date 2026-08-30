"""The 'Touchdowns' tab — an anytime-scorer model and picks.

Geared purely at who finds the end zone: goal-line and red-zone usage, the
opponent's run/pass defense, the team's projected points (spread + total +
weather), and how TDs split run vs pass. It surfaces the strongest anytime-TD
plays as cards, ranks every meaningful scorer, and prices the exact edge when you
enter a book's anytime-TD number.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import loaders, touchdowns as td


def _card(col, r) -> None:
    a = r["Anytime%"]
    color = "#2dd4bf" if a >= 55 else ("#5eb3f0" if a >= 38 else "#8b98a5")
    col.markdown(
        f"<div style='border:1px solid #1e2732;border-left:4px solid {color};border-radius:12px;"
        f"padding:13px 15px;height:100%;background:#141b23;'>"
        f"<div style='font-weight:700;font-size:1.04rem;'>{r['Player']} "
        f"<span style='color:#8b98a5;font-weight:400;font-size:0.82rem;'>{r['Pos']} · {r['Team']} vs {r['Opp']}</span></div>"
        f"<div style='display:flex;gap:16px;align-items:baseline;margin:8px 0 4px;'>"
        f"<div><span style='font-size:1.5rem;font-weight:800;color:{color};'>{a:.0f}%</span>"
        f"<span style='color:#8b98a5;font-size:0.78rem;'> anytime</span></div>"
        f"<div style='color:#8b98a5;font-size:0.85rem;'>fair {r['fair']:+d} · {r['xTD']:.2f} xTD · 2+ {r['2+%']:.0f}%</div></div>"
        f"<div style='font-size:0.82rem;color:#8b98a5;'>{r['Driver']} · {int(r['GL touches'])} GL touches · "
        f"team total {r['TeamTotal']:.0f}{(' · ' + r['Weather']) if r['Weather'] else ''}</div></div>",
        unsafe_allow_html=True)


def _board_section(board, games) -> None:
    st.markdown("### Top anytime-TD plays")
    st.caption("Ranked by expected TDs — goal-line role, matchup, team total, and weather baked in.")
    f1, f2 = st.columns([2, 2])
    positions = sorted(board["Pos"].dropna().unique())
    pos_sel = f1.multiselect("Position", positions, default=positions, key="td_pos")
    game_opts = ["All games"] + sorted(board["Game"].unique())
    game_sel = f2.selectbox("Game", game_opts, key="td_game")
    view = board[board["Pos"].isin(pos_sel)]
    if game_sel != "All games":
        view = view[view["Game"] == game_sel]
    if view.empty:
        st.info("No scorers match those filters.")
        return
    top = view.head(6).reset_index(drop=True)
    for i in range(0, len(top), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(top):
                _card(col, top.iloc[i + j])
    with st.expander(f"All {len(view)} scorers (ranked)"):
        show = view[["Player", "Pos", "Team", "Opp", "xTD", "Anytime%", "2+%", "fair",
                     "GL touches", "TeamTotal", "Driver"]].rename(columns={"fair": "Fair"})
        st.dataframe(show, width="stretch", hide_index=True, column_config={
            "Anytime%": st.column_config.NumberColumn("Anytime%", format="%d%%"),
            "2+%": st.column_config.NumberColumn("2+%", format="%d%%"),
            "Fair": st.column_config.NumberColumn("Fair", format="%+d"),
            "TeamTotal": st.column_config.NumberColumn("Team pts", format="%.0f"),
        })
    st.caption("**xTD** = expected touchdowns (rush + receiving). **Anytime%** = 1 − e^−xTD. "
               "**Fair** is the no-vig price — beat it at the book and you have value.")


def _two_plus(board) -> None:
    st.markdown("### Multi-score longshots (2+ TD)")
    view = board[board["2+%"] >= 8].sort_values("2+%", ascending=False).head(6)
    if view.empty:
        st.caption("No strong 2+ TD candidates on this slate.")
        return
    show = view[["Player", "Pos", "Team", "Opp", "2+%", "xTD", "GL touches"]]
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "2+%": st.column_config.NumberColumn("2+ TD%", format="%d%%")})
    st.caption("Big prices, but the goal-line workhorses on high-total teams are where multi-TD games live.")


def _finder(board) -> None:
    st.markdown("### Anytime-TD edge finder")
    st.caption("Enter a book's anytime-TD price to get the edge, fair odds, and Kelly stake.")
    who = st.selectbox("Player", list(board["Player"]), key="td_finder")
    r = board[board["Player"] == who].iloc[0]
    c1, c2 = st.columns([1, 3])
    odds = c1.number_input("Book odds (american)", value=int(r["fair"]), step=5, key="td_odds")
    res = td.edge_vs_odds(r["_anytime"], odds)
    m = st.columns(4)
    m[0].metric("Model anytime", f"{r['Anytime%']:.0f}%")
    m[1].metric("Fair odds", f"{res['fair']:+d}")
    m[2].metric("Edge", f"{res['edge']*100:+.1f} pts" if pd.notna(res["edge"]) else "—")
    m[3].metric("Kelly", f"{res['kelly']*100:.1f}u" if res["kelly"] else "—")
    if pd.notna(res["edge"]) and res["edge"] > 0.03:
        st.success(f"Value — model {r['Anytime%']:.0f}% vs {res['implied']*100:.0f}% implied at {odds:+d}.")
    else:
        st.info("No clear edge at this price.")


def render(off, deff, blitz, schedule, extras) -> None:
    st.subheader("Touchdowns — anytime scorer model")
    if off.empty or deff.empty or extras.get("rz_usage") is None or extras["rz_usage"].empty:
        st.info("Touchdown model needs play-by-play usage — it loads once games are played.")
        return
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded for the current season yet.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0, key="td_wk")
    games = s[s["week"] == wk]
    board = td.td_board(off, deff, extras, games)
    if board.empty:
        st.info("No touchdown projections for this week yet (need the week's matchups).")
        return
    _board_section(board, games)
    st.divider()
    _two_plus(board)
    st.divider()
    _finder(board)
