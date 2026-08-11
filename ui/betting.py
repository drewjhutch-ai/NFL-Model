"""The 'Betting' tab: our model vs the market.

Projects each game from our compiled efficiency data, lines it up against the
book's spread/total/moneyline, and surfaces where the value is — plus, when we
disagree with the market, *why* (our drivers) and what the book may be pricing
that we don't (injuries, rest, weather). Line movement / sharp-money signals
plug in via data/odds_providers.py once a live feed is connected.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, loaders
from data.odds_providers import get_odds_provider


def _spread_str(home, away, home_margin) -> str:
    if pd.isna(home_margin):
        return "—"
    return f"{home} -{home_margin:.1f}" if home_margin >= 0 else f"{away} -{abs(home_margin):.1f}"


def _overview(games: pd.DataFrame, off, deff, extras) -> None:
    rows = []
    for _, r in games.iterrows():
        a = betting.assess(r, off, deff, extras)
        val = "—"
        if a["value_side"] and pd.notna(a["edge_pts"]):
            val = f"{a['value_side']} ({abs(a['edge_pts']):.1f})"
        rows.append({
            "Game": f"{a['away']} @ {a['home']}",
            "Market": _spread_str(a["home"], a["away"], a["mkt_spread"]),
            "Our line": _spread_str(a["home"], a["away"], a["model_margin"]),
            "Value bet": val,
            "Δ pts": round(a["edge_pts"], 1) if pd.notna(a["edge_pts"]) else None,
            "Flag": ("⚠️ disagree" if a["disagree"] else ("🎯 value" if a["value_side"] else "")),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config={"Δ pts": st.column_config.NumberColumn(
                     "Δ pts", help="Our line minus market (home-relative). |Δ| ≥ "
                     f"{config.VALUE_SPREAD_PTS} flags value.", format="%+.1f")})
    st.caption("**Value bet** = the side our model favors by more than the market. "
               "**⚠️ disagree** = we and the book disagree on the outright favorite.")


def _detail(row: pd.Series, off, deff, extras) -> None:
    a = betting.assess(row, off, deff, extras)
    meta = loaders.team_meta()
    away, home = a["away"], a["home"]

    c1, cm, c2 = st.columns([5, 1, 5])
    for col, t in ((c1, away), (c2, home)):
        m = meta.get(t, {})
        if m.get("logo"):
            col.image(m["logo"], width=46)
        col.markdown(f"**{m.get('name', t)}**")
    cm.markdown("<div style='text-align:center;margin-top:14px;color:#888;'>@</div>",
                unsafe_allow_html=True)

    # market vs model
    mc, oc = st.columns(2)
    with mc:
        st.markdown("#### 🏦 Market")
        st.metric("Spread", _spread_str(home, away, a["mkt_spread"]))
        st.caption(f"Total {a['total_line'] if pd.notna(a['total_line']) else '—'} · "
                   f"ML {away} {row.get('away_moneyline')} / {home} {row.get('home_moneyline')}")
        if pd.notna(a["mkt_p_home"]):
            st.caption(f"Implied: {home} {a['mkt_p_home']*100:.0f}% · {away} {(1-a['mkt_p_home'])*100:.0f}%")
    with oc:
        st.markdown("#### 🧮 Our model")
        st.metric("Projected spread", _spread_str(home, away, a["model_margin"]))
        if pd.notna(a["model_p_home"]):
            st.caption(f"Win prob: {home} {a['model_p_home']*100:.0f}% · {away} {(1-a['model_p_home'])*100:.0f}%")
        pr = betting.power_ratings(off, deff)
        if home in pr.index and away in pr.index:
            st.caption(f"Power rank: {home} #{int(pr.loc[home,'power_rank'])} · "
                       f"{away} #{int(pr.loc[away,'power_rank'])}")

    # verdict
    if a["value_side"]:
        st.success(f"🎯 **Value:** {a['value_side']} — our line is {abs(a['edge_pts']):.1f} pts "
                   f"off the market" + (f", and {abs(a['edge_prob'])*100:.0f}% on the moneyline"
                                        if pd.notna(a["edge_prob"]) else "") + ".")
    else:
        st.info("🟰 Our number is close to the market — no clear spread value here.")

    if a["disagree"]:
        st.warning(f"⚠️ **We disagree with the book on who wins.** We favor **{a['our_fav']}**, "
                   f"the market favors **{a['mkt_fav']}**. Reasons below.")

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("##### 🔍 Why our number differs")
        if a["why"]:
            for e in a["why"]:
                st.markdown(f"- **{e['label']}** ({e['mag']:+.0f} × {e['weight']:g} "
                            f"= {e['impact']:+.0f}) · {e['detail']}")
        else:
            st.caption("No standout edges — our number is efficiency-driven and close.")
    with d2:
        st.markdown("##### 🏦 What the market may see that we don't")
        if a["context"]:
            for f in a["context"]:
                st.markdown(f"- {f}")
        else:
            st.caption("No obvious injury / rest / weather factors flagged.")

    st.divider()
    st.markdown("##### 📈 Line movement & sharp money")
    prov = get_odds_provider()
    if prov.is_available():
        st.caption("Live feed connected.")  # future: render movement + RLM
    else:
        st.caption("🔌 Not connected. Line movement (open→current) and sharp signals "
                   "(reverse line movement, money% vs bet%) need a live odds feed — "
                   "see `data/odds_providers.py`. The comparison above uses the "
                   "current consensus line.")


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
        st.info("No market lines posted yet for the current season (they populate "
                "as books release them). Meanwhile, the power ratings still work:")
        st.dataframe(betting.power_ratings(off, deff).sort_values("power_rank")
                     [["net", "power_rank"]], width="stretch")
        return

    s = schedule[(schedule["season"] == season) & schedule["spread_line"].notna()]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    idx = weeks.index(default_wk) if default_wk in weeks else 0
    wk = st.selectbox(f"Week ({season})", weeks, index=idx)
    games = s[s["week"] == wk]

    st.markdown("### 📊 This week: model vs market")
    _overview(games, off, deff, extras)

    st.divider()
    labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    pick = st.selectbox("Break down a game", labels)
    _detail(games.iloc[labels.index(pick)], off, deff, extras)
