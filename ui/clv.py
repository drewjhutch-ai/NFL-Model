"""The 'CLV' tab — line-shopping across the books, live.

Elite betting isn't only the right side, it's the *best number*. This tab pulls
live multi-book odds (The Odds API) and hunts price discrepancies: which book
has the best price on each side, how wide the market is (a wide spread = a soft,
beatable line), where a book is pricing a side better than the de-vigged
consensus (true CLV value), and a single-bet lookup for the best available odds.

Live: an optional auto-refresh re-pulls on a cadence (a Streamlit fragment), plus
a manual "Refresh now". Polling burns Odds-API quota, so auto-refresh defaults
off and warns; game lines are cheap, continuous polling wants the paid tier.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import betengine, betting, odds_providers


@st.cache_data(ttl=90, show_spinner="Pulling live multi-book odds…")
def _fetch_odds() -> tuple[pd.DataFrame, str]:
    """Return (odds, status). status ∈ ok | no_key | empty | error:<msg>."""
    prov = odds_providers.get_odds_provider()
    if not prov.is_available():
        return pd.DataFrame(), "no_key"
    try:
        df = prov.current()
    except Exception as exc:  # noqa: BLE001 - network/quota issues degrade to empty
        return pd.DataFrame(), f"error:{exc}"
    return (df, "ok") if not df.empty else (pd.DataFrame(), "empty")


def _best_american(series: pd.Series):
    """Best (most favorable to the bettor) American price in a column."""
    s = series.dropna()
    return float(s.max()) if not s.empty else None


def _devig_prob(a: float, b: float) -> float:
    """No-vig probability of side A from a two-way American market."""
    return betengine.novig_prob(a, b)


def _model_lean(off, deff, extras, away, home, cons_spread):
    """The model's home margin and its lean vs the consensus spread.

    Ties CLV back to the predictive engine: a soft line only matters if the model
    likes that side. Returns {margin, side, edge} or None.
    """
    if off is None or deff is None or off.empty or deff.empty:
        return None
    m = betting.project_margin(off, deff, home, away, extras.get("st_ppg"),
                               extras.get("qb_value"), extras.get("points_rtg"))
    if pd.isna(m):
        return None
    if cons_spread is None or pd.isna(cons_spread):
        return {"margin": float(m), "side": home if m > 0 else away, "edge": None}
    edge = float(m) - float(cons_spread)   # + = model favors home more than market
    return {"margin": float(m), "side": home if edge > 0 else away, "edge": abs(edge)}


def _discrepancy_board(df: pd.DataFrame, off=None, deff=None, extras=None) -> None:
    st.markdown("### Discrepancy board")
    st.caption("Every game, how far apart the books are, and the best number available on each side. "
               "A **wide spread across books = a soft line**; the ★ marks games where our model likes "
               "the side the soft number is on — a soft line on a side we already back is the play.")
    extras = extras or {}
    rows = []
    for (away, home), g in df.groupby(["away", "home"]):
        con = odds_providers.consensus(g)
        hs = g["home_spread"].dropna()
        tot = g["total"].dropna()
        spread_width = (float(hs.max()) - float(hs.min())) if len(hs) > 1 else 0.0
        total_width = (float(tot.max()) - float(tot.min())) if len(tot) > 1 else 0.0
        lean = _model_lean(off, deff, extras, away, home, con.get("home_spread"))
        # value = a soft market AND the model has a real lean with an edge
        starred = bool(lean and lean.get("edge") and lean["edge"] >= 1.0 and spread_width >= 1.0)
        model_txt = "—"
        if lean:
            model_txt = lean["side"] + (f" +{lean['edge']:.1f}" if lean.get("edge") else "")
        rows.append({
            "": "★" if starred else "", "Game": f"{away} @ {home}",
            "Books": int(g["book"].nunique()),
            "Model lean": model_txt,
            "Cons. spread": con.get("home_spread"),
            "Spread range": spread_width,
            "Best home line": con.get("best_home_spread"),
            "Best away line": con.get("best_away_spread"),
            "Cons. total": con.get("total"),
            "Total range": total_width,
            "Best home ML": _best_american(g["ml_home"]),
            "Best away ML": _best_american(g["ml_away"]),
            "_sort": (1 if starred else 0, max(spread_width, total_width)),
        })
    if not rows:
        st.info("No games in the live feed right now.")
        return
    board = (pd.DataFrame(rows).sort_values("_sort", ascending=False, key=lambda s: s.map(lambda t: t[0] * 100 + t[1]))
             .drop(columns="_sort"))
    st.dataframe(board, width="stretch", hide_index=True, column_config={
        "": st.column_config.TextColumn("", width="small",
            help="★ = soft line on the side our model already backs."),
        "Model lean": st.column_config.TextColumn("Model lean",
            help="Our projected side vs the consensus spread, with the points of edge."),
        "Cons. spread": st.column_config.NumberColumn("Cons. spread", format="%+.1f",
            help="Consensus home spread (+ = home favored by, − = home dog)."),
        "Spread range": st.column_config.NumberColumn("Spread Δ", format="%.1f",
            help="Points between the tightest and loosest book — bigger = softer market."),
        "Best home line": st.column_config.NumberColumn("Best home", format="%+.1f"),
        "Best away line": st.column_config.NumberColumn("Best away", format="%+.1f"),
        "Cons. total": st.column_config.NumberColumn("Cons. total", format="%.1f"),
        "Total range": st.column_config.NumberColumn("Total Δ", format="%.1f"),
        "Best home ML": st.column_config.NumberColumn("Best home ML", format="%+d"),
        "Best away ML": st.column_config.NumberColumn("Best away ML", format="%+d"),
    })
    st.caption("‘Best’ = the most favorable number in the market — fewest points laid, or the plus-est ML. "
               "★ games rank first: the model's edge and a soft line pointing the same way.")


def _book_grid(df: pd.DataFrame) -> None:
    st.markdown("### Book-by-book")
    games = sorted({f"{a} @ {h}" for a, h in zip(df["away"], df["home"])})
    if not games:
        return
    pick = st.selectbox("Game", games, key="clv_game")
    away, home = [t.strip() for t in pick.split("@")]
    g = df[(df["away"] == away) & (df["home"] == home)].copy()
    if g.empty:
        st.info("No book data for that game.")
        return
    grid = pd.DataFrame({
        "Book": g["book"],
        "Home spread": g["home_spread"], "Total": g["total"],
        "Home ML": g["ml_home"], "Away ML": g["ml_away"],
        "Sharp": g["is_sharp"].map({True: "★", False: ""}),
    }).sort_values("Book")
    # highlight the best number in each column
    best = {
        "Home spread": g["home_spread"].min() if g["home_spread"].notna().any() else None,  # fewest laid
        "Total": None,
        "Home ML": _best_american(g["ml_home"]), "Away ML": _best_american(g["ml_away"]),
    }

    def _hi(col):
        name = col.name
        target = best.get(name)
        if target is None:
            return ["" for _ in col]
        return ["background-color: rgba(34,211,238,0.18); font-weight:700"
                if pd.notna(v) and float(v) == float(target) else "" for v in col]

    sty = grid.style.apply(_hi, subset=["Home spread", "Home ML", "Away ML"])
    st.dataframe(sty, width="stretch", hide_index=True, column_config={
        "Home spread": st.column_config.NumberColumn(format="%+.1f"),
        "Total": st.column_config.NumberColumn(format="%.1f"),
        "Home ML": st.column_config.NumberColumn(format="%+d"),
        "Away ML": st.column_config.NumberColumn(format="%+d"),
    })

    # de-vig value vs consensus on the moneyline
    two = g.dropna(subset=["ml_home", "ml_away"])
    if len(two) >= 2:
        fair_home = two.apply(lambda r: _devig_prob(r["ml_home"], r["ml_away"]), axis=1).mean()
        fair_away = 1 - fair_home
        bh, ba = _best_american(g["ml_home"]), _best_american(g["ml_away"])
        msgs = []
        for side, price, fair in ((home, bh, fair_home), (away, ba, fair_away)):
            if price is None or pd.isna(fair):
                continue
            imp = betengine.implied_prob(price)
            edge = fair - imp
            if edge > 0.005:
                msgs.append(f"**{side} ML {betengine.fmt_odds(price)}** — "
                            f"fair {fair*100:.1f}%, priced {imp*100:.1f}% → "
                            f"**{edge*100:+.1f}%** vs consensus")
        if msgs:
            st.markdown("**Value vs consensus (de-vigged):**")
            for m in msgs:
                st.markdown(f"- {m}")
        else:
            st.caption("No book is beating the de-vigged consensus on the moneyline for this game.")


def _single_lookup(df: pd.DataFrame) -> None:
    st.markdown("### Single-bet lookup — best price")
    st.caption("Pick a bet; see which book has the best number and how much you gain vs the field.")
    games = sorted({f"{a} @ {h}" for a, h in zip(df["away"], df["home"])})
    if not games:
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    pick = c1.selectbox("Game", games, key="clv_lookup_game")
    market = c2.selectbox("Market", ["Moneyline", "Spread"], key="clv_lookup_mkt")
    away, home = [t.strip() for t in pick.split("@")]
    side = c3.selectbox("Side", [home, away], key="clv_lookup_side")
    g = df[(df["away"] == away) & (df["home"] == home)]
    if g.empty:
        return
    if market == "Moneyline":
        col = "ml_home" if side == home else "ml_away"
        prices = g[["book", col]].dropna()
        if prices.empty:
            st.info("No moneyline prices posted for that side.")
            return
        best_row = prices.loc[prices[col].idxmax()]
        field_avg = prices[col].mean()
        st.success(f"Best: **{side} {betengine.fmt_odds(best_row[col])}** at **{best_row['book']}** "
                   f"· field avg {betengine.fmt_odds(field_avg)}")
        gain = betengine.american_to_decimal(best_row[col]) - betengine.american_to_decimal(field_avg)
        st.caption(f"On a 1-unit win that's **{gain:+.2f}u** more than the field average — the CLV of shopping.")
    else:
        # spread: home_spread is points home lays; best for home = fewest, for away = most
        prices = g[["book", "home_spread"]].dropna()
        if prices.empty:
            st.info("No spreads posted for that game.")
            return
        if side == home:
            best_row = prices.loc[prices["home_spread"].idxmin()]
            num = best_row["home_spread"]
        else:
            best_row = prices.loc[prices["home_spread"].idxmax()]
            num = -best_row["home_spread"]
        st.success(f"Best: **{side} {num:+.1f}** at **{best_row['book']}**")
        rng = prices["home_spread"].max() - prices["home_spread"].min()
        st.caption(f"The market spans {rng:.1f} pts on this line — worth the shop.")


def _clv_tracking(df: pd.DataFrame) -> None:
    st.markdown("### Line movement (open → now)")
    st.caption("From this session's odds snapshots — how the consensus home spread has moved since the "
               "first pull. Beating the close is the long-run edge; this shows which way it's going.")
    prov = odds_providers.get_odds_provider()
    rows = []
    for (away, home), _ in df.groupby(["away", "home"]):
        mv = prov.movement(away, home)
        if mv:
            rows.append({"Game": f"{away} @ {home}", "Open": mv["open_spread"],
                         "Now": mv["current_spread"], "Move": mv["delta"]})
    if not rows:
        st.info("Not enough snapshots yet — movement builds as the feed is pulled over time.")
        return
    mvdf = pd.DataFrame(rows).sort_values("Move", key=lambda s: s.abs(), ascending=False)
    st.dataframe(mvdf, width="stretch", hide_index=True, column_config={
        "Open": st.column_config.NumberColumn(format="%+.1f"),
        "Now": st.column_config.NumberColumn(format="%+.1f"),
        "Move": st.column_config.NumberColumn("Move", format="%+.1f",
            help="Positive = home line moved toward the home favorite since open."),
    })


def _empty_state(status: str) -> None:
    if status == "no_key":
        st.warning("**No odds feed connected.** The CLV tab needs a live multi-book feed to shop "
                   "lines — it can't be built from the single consensus number in the schedule.")
        st.markdown(
            "**Turn it on (free):**\n"
            "1. Get a free key at [the-odds-api.com](https://the-odds-api.com) — the free tier is "
            "~500 requests/month, plenty for weekly line-shopping.\n"
            "2. In Streamlit Cloud: **Manage app → Settings → Secrets**, add\n"
            "   ```toml\n   ODDS_API_KEY = \"your-key-here\"\n   ```\n"
            "3. Reboot the app. This tab lights up across every US, UK, AU & EU book automatically.\n\n"
            "Your key stays in Streamlit Secrets — never paste it into the app or commit it.")
    elif status.startswith("error:"):
        st.error(f"The odds feed is connected but the last pull failed — likely out of monthly "
                 f"quota or a temporary network issue. It'll recover on the next refresh.\n\n"
                 f"`{status[6:][:200]}`")
    else:  # empty
        st.info("The feed is connected but no NFL games are posted right now (typical between the "
                "weekly slates and in the offseason). Lines return once books post the next slate.")


def _body(auto: bool, off=None, deff=None, extras=None) -> None:
    df, status = _fetch_odds()
    if df.empty:
        _empty_state(status)
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Games", int((df[["away", "home"]].drop_duplicates()).shape[0]))
    c2.metric("Books", int(df["book"].nunique()))
    c3.metric("Feed", "Auto-refreshing ✓" if auto else "Manual")
    st.divider()
    _discrepancy_board(df, off, deff, extras)
    st.divider()
    _book_grid(df)
    st.divider()
    _single_lookup(df)
    st.divider()
    _clv_tracking(df)


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("CLV — line-shopping the books")
    st.caption("Live multi-book odds. Find the softest lines, the best price on any side, where a book "
               "beats the de-vigged consensus, and track how the number moves. Best price + right side "
               "= closing-line value.")

    ctop = st.columns([1, 2, 2])
    if ctop[0].button("↻ Refresh now"):
        _fetch_odds.clear()
        st.rerun()
    auto = ctop[1].toggle("Auto-refresh (live)", value=False, key="clv_auto",
                          help="Re-pulls on a cadence. Burns Odds-API quota — leave off unless you want "
                               "a live feed and have the quota for it.")
    cadence = ctop[2].selectbox("Cadence", [60, 120, 300], index=1, format_func=lambda s: f"{s}s",
                                key="clv_cadence", disabled=not auto)

    if auto:
        st.caption("⚡ Live: continuous polling uses quota fast — the paid Odds-API tier (~$30/mo) is the "
                   "comfortable way to run this always-on.")

        @st.fragment(run_every=cadence)
        def _live():
            _fetch_odds.clear()
            _body(auto=True, off=off, deff=deff, extras=extras)
        _live()
    else:
        _body(auto=False, off=off, deff=deff, extras=extras)
