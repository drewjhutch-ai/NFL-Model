"""The 'Betting' tab: our model vs the market, across all three markets.

Projects spread / total / moneyline from our compiled data, lines each up
against the book, and flags value + favorite disagreements — with *why* (our
drivers) and what the market prices that we don't (injuries, rest, weather).
When a live odds feed is connected (The Odds API), adds multi-book line shopping,
a sharp-book-vs-consensus signal, and line movement.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, loaders
from data import odds_providers as op


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


def _spread_str(home, away, home_margin) -> str:
    if pd.isna(home_margin):
        return "—"
    return f"{home} -{home_margin:.1f}" if home_margin >= 0 else f"{away} -{abs(home_margin):.1f}"


def _effective_row(row: pd.Series, live_game: pd.DataFrame) -> pd.Series:
    """Overlay live consensus onto the schedule row when we have a live feed."""
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


def _overview(games: pd.DataFrame, off, deff, extras, live: pd.DataFrame) -> None:
    rows = []
    for _, r in games.iterrows():
        lg = live[(live["away"] == r["away_team"]) & (live["home"] == r["home_team"])] \
            if not live.empty else pd.DataFrame()
        a = betting.assess(_effective_row(r, lg), off, deff, extras)
        vals = []
        if a["value_side"] and pd.notna(a["edge_pts"]):
            vals.append(f"{a['value_side']} {abs(a['edge_pts']):.1f}")
        if a["total_side"]:
            vals.append(f"{a['total_side']} {abs(a['total_edge']):.1f}")
        rows.append({
            "Game": f"{a['away']} @ {a['home']}",
            "Market": _spread_str(a["home"], a["away"], a["mkt_spread"]),
            "Our line": _spread_str(a["home"], a["away"], a["model_margin"]),
            "Total (mkt/ours)": (f"{a['total_line']:.1f} / {a['model_total']:.0f}"
                                 if pd.notna(a["total_line"]) and pd.notna(a["model_total"]) else "—"),
            "Value": " · ".join(vals) if vals else "—",
            "Flag": ("⚠️ disagree" if a["disagree"] else ("🎯 value" if vals else "")),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("**Value** = a side our model likes more than the market (spread or total). "
               "**⚠️ disagree** = we and the book disagree on the outright favorite.")


def _markets_panel(a: dict, row: pd.Series) -> None:
    sp, tot, ml = st.columns(3)
    with sp:
        st.markdown("**📐 Spread**")
        st.caption(f"Market: {_spread_str(a['home'], a['away'], a['mkt_spread'])}")
        st.caption(f"Ours: {_spread_str(a['home'], a['away'], a['model_margin'])}")
        if a["value_side"]:
            st.markdown(f"🎯 **{a['value_side']}** (+{abs(a['edge_pts']):.1f})")
    with tot:
        st.markdown("**🔢 Total**")
        st.caption(f"Market: {a['total_line']:.1f}" if pd.notna(a["total_line"]) else "Market: —")
        st.caption(f"Ours: {a['model_total']:.0f}" if pd.notna(a["model_total"]) else "Ours: —")
        if a["total_side"]:
            st.markdown(f"🎯 **{a['total_side']}** (+{abs(a['total_edge']):.1f})")
    with ml:
        st.markdown("**💵 Moneyline**")
        if pd.notna(a["mkt_p_home"]):
            st.caption(f"Market: {a['home']} {a['mkt_p_home']*100:.0f}% / {a['away']} {(1-a['mkt_p_home'])*100:.0f}%")
        if pd.notna(a["model_p_home"]):
            fair_h = betting.fair_moneyline(a["model_p_home"])
            st.caption(f"Ours: {a['home']} {a['model_p_home']*100:.0f}% (fair {fair_h:+d})")
        if a["ml_side"]:
            st.markdown(f"🎯 **{a['ml_side']}** (+{abs(a['edge_prob'])*100:.0f}%)")


def _live_section(away: str, home: str, live_game: pd.DataFrame) -> None:
    st.markdown("##### 📈 Live odds, line shopping & sharp action")
    if live_game is None or live_game.empty:
        prov = op.get_odds_provider()
        if prov.is_available():
            st.caption("No live line for this game yet.")
        else:
            st.caption("🔌 Live feed not connected. Add a free **The Odds API** key "
                       "(ODDS_API_KEY in Streamlit secrets) to unlock multi-book line "
                       "shopping, a sharp-book signal, and line movement. "
                       "See `data/odds_providers.py`.")
        return

    c = op.consensus(live_game)
    show = live_game[["book", "home_spread", "total", "ml_home", "ml_away"]].copy()
    show = show.rename(columns={"home_spread": f"{home} spread", "ml_home": f"{home} ML",
                                "ml_away": f"{away} ML"})
    st.dataframe(show.sort_values(f"{home} spread"), width="stretch", hide_index=True)

    cols = st.columns(3)
    if c.get("best_home_spread") is not None:
        cols[0].metric(f"Best {home} number", f"{c['best_home_spread']:+.1f}")
        cols[1].metric(f"Best {away} number", f"{c['best_away_spread']:+.1f}")
    if c.get("sharp_spread") is not None:
        diff = c["sharp_spread"] - c["home_spread"]
        lean = home if diff > 0 else away
        cols[2].metric("Sharp vs consensus", f"{c['sharp_spread']:+.1f}",
                       f"leans {lean}" if abs(diff) >= 0.5 else "in line",
                       help=f"Sharp book(s): {c.get('sharp_book','?')}. They move on sharp money.")

    mv = op.get_odds_provider().movement(away, home)
    if mv:
        d = mv["delta"]
        toward = home if d > 0 else away
        st.caption(f"📉 **Movement:** {home} spread {mv['open_spread']:+.1f} → "
                   f"{mv['current_spread']:+.1f} (toward {toward})")
    else:
        st.caption("Movement builds as the app collects odds snapshots over time.")


def _detail(row: pd.Series, off, deff, extras, live: pd.DataFrame) -> None:
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
    cm.markdown("<div style='text-align:center;margin-top:14px;color:#888;'>@</div>",
                unsafe_allow_html=True)

    pr = betting.power_ratings(off, deff)
    if home in pr.index and away in pr.index:
        st.caption(f"Power rank: {home} #{int(pr.loc[home,'power_rank'])} · "
                   f"{away} #{int(pr.loc[away,'power_rank'])}")

    _markets_panel(a, row)
    st.divider()

    if a["disagree"]:
        st.warning(f"⚠️ **We disagree with the book on who wins.** We favor **{a['our_fav']}**, "
                   f"the market favors **{a['mkt_fav']}**.")
    elif a["value_side"] or a["total_side"] or a["ml_side"]:
        st.success("🎯 Value spots flagged above.")
    else:
        st.info("🟰 Our numbers are close to the market — no clear edge here.")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("##### 🔍 Why our number differs")
        if a["why"]:
            for e in a["why"]:
                st.markdown(f"- **{e['label']}** ({e['mag']:+.0f} × {e['weight']:g} "
                            f"= {e['impact']:+.0f}) · {e['detail']}")
        else:
            st.caption("Efficiency-driven and close to market.")
    with d2:
        st.markdown("##### 🏦 What the market may see that we don't")
        if a["context"]:
            for f in a["context"]:
                st.markdown(f"- {f}")
        else:
            st.caption("No obvious injury / rest / weather factors flagged.")

    st.divider()
    _live_section(away, home, lg)


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Betting — our model vs the market")
    if off.empty or deff.empty:
        st.warning("Need team data loaded first.")
        return
    season = config.CURRENT_SEASON
    have = (schedule is not None and not schedule.empty
            and (schedule["season"] == season).any()
            and schedule.loc[schedule["season"] == season, "spread_line"].notna().any())
    if not have:
        st.info("No market lines posted yet for the current season. Power ratings still work:")
        st.dataframe(betting.power_ratings(off, deff).sort_values("power_rank")
                     [["net", "power_rank"]], width="stretch")
        return

    live = _live_odds()
    if not live.empty:
        st.caption(f"🟢 Live odds connected ({live['book'].nunique()} books).")

    s = schedule[(schedule["season"] == season) & schedule["spread_line"].notna()]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    idx = weeks.index(default_wk) if default_wk in weeks else 0
    wk = st.selectbox(f"Week ({season})", weeks, index=idx)
    games = s[s["week"] == wk]

    st.markdown("### 📊 This week: model vs market")
    _overview(games, off, deff, extras, live)

    st.divider()
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    pick = st.selectbox("Break down a game", labels)
    _detail(games.iloc[labels.index(pick)], off, deff, extras, live)
