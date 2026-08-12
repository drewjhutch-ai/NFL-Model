"""The 'Picks of the Week' tab.

Two halves:
  * **Auto-surfaced leans** — the week's biggest unit + positional mismatches,
    ranked, so the model points you at the strongest spots.
  * **Your pick log** — record your own game/player picks with reasoning and
    export them; a running record to hold yourself accountable.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, edges, loaders, simulation


def _value_plays(off, deff, games, extras) -> None:
    st.markdown("### 💎 Value plays — model vs market (with Kelly sizing)")
    rows = []
    for _, r in games.iterrows():
        if pd.isna(r.get("spread_line")):
            continue
        sim = simulation.simulate(off, deff, r["home_team"], r["away_team"], extras, r)
        if not sim:
            continue
        home, away = r["home_team"], r["away_team"]
        # spread
        if "home_cover" in sim:
            p = max(sim["home_cover"], 1 - sim["home_cover"])
            side = home if sim["home_cover"] >= 0.5 else away
            if p >= 0.53:
                rows.append(("Spread", f"{away}@{home}", f"{side} {r['spread_line']:+.1f}"
                             if side == home else f"{side} {-r['spread_line']:+.1f}", p))
        # total
        if "over" in sim:
            p = max(sim["over"], 1 - sim["over"])
            side = "Over" if sim["over"] >= 0.5 else "Under"
            if p >= 0.53:
                rows.append(("Total", f"{away}@{home}", f"{side} {r.get('total_line')}", p))
    if not rows:
        st.info("No spread/total plays clear the value threshold this week.")
        return
    out = []
    for kind, game, bet, p in sorted(rows, key=lambda x: -x[3]):
        stake = betting.kelly_stake(p)
        out.append({"Market": kind, "Game": game, "Play": bet,
                    "Model win%": f"{p*100:.0f}%", "Edge vs 52.4%": f"{(p-0.524)*100:+.1f} pts",
                    "Kelly stake": f"{stake*100:.1f}u" if stake else "—"})
    st.dataframe(pd.DataFrame(out), width="stretch", hide_index=True)
    st.caption("Win% from the game simulation; **Kelly stake** is quarter-Kelly units "
               "(of a 100-unit bankroll) at -110 — conservative sizing. Not financial advice.")


def _auto_leans_games(off, deff, games, extras) -> None:
    st.markdown("### 🔎 Model leans — biggest edges this week")
    leans = edges.week_leans(games, off, deff, extras)
    if leans.empty:
        st.info("No standout edges for this week yet (early-season / offseason data).")
        return
    show = leans[["Game", "Edge", "Detail"]].copy()
    show.insert(0, "#", range(1, len(show) + 1))
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption(
        "Edges rank offense-side mismatches (featured unit vs. a soft opponent). "
        "A starting point for your own read — not a guarantee."
    )


def _pick_log() -> None:
    st.markdown("### 📝 Your picks")
    if "picks" not in st.session_state:
        st.session_state["picks"] = []

    with st.form("add_pick", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        game = c1.text_input("Game / player", placeholder="e.g. KC @ BUF — Kelce over 60.5 yds")
        pick = c2.text_input("Your pick", placeholder="e.g. Kelce OVER")
        conf = c3.selectbox("Confidence", ["★", "★★", "★★★"], index=1)
        notes = st.text_input("Why (optional)", placeholder="e.g. BUF soft vs TE, KC pass-heavy")
        if st.form_submit_button("Add pick") and (game or pick):
            st.session_state["picks"].append(
                {"Game/Player": game, "Pick": pick, "Confidence": conf, "Notes": notes}
            )

    picks = st.session_state["picks"]
    if not picks:
        st.caption("No picks logged yet. Add one above.")
        return
    df = pd.DataFrame(picks)
    st.dataframe(df, width="stretch", hide_index=True)
    c1, c2 = st.columns([1, 5])
    c1.download_button("⬇️ Export CSV", df.to_csv(index=False).encode(),
                       file_name="my_picks.csv", mime="text/csv")
    if c2.button("Clear all picks"):
        st.session_state["picks"] = []
        st.rerun()
    st.caption("Picks are saved for this session. Export to keep them.")


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Picks of the Week")
    if off.empty or deff.empty:
        st.info("Load data first (needs offensive & defensive numbers).")
        return
    season = config.CURRENT_SEASON
    if schedule is not None and not schedule.empty and (schedule["season"] == season).any():
        s = schedule[schedule["season"] == season]
        weeks = sorted(int(w) for w in s["week"].unique())
        default_wk = loaders.current_week(schedule, season) or weeks[0]
        wk = st.selectbox(f"Week ({season})", weeks,
                          index=weeks.index(default_wk) if default_wk in weeks else 0,
                          key="picks_week")
        games = s[s["week"] == wk]
        _value_plays(off, deff, games, extras)
        st.divider()
        _auto_leans_games(off, deff, games, extras)
    else:
        st.info("Schedule not loaded — weekly plays unavailable. Use Matchups to compare teams.")
    st.divider()
    _pick_log()
