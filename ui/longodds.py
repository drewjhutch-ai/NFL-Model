"""The 'Long Odds' tab — +200 plays with conviction.

Not an excuse for bad longshots. This board takes the same priced bets every
other tab uses and keeps only genuine long prices (+200 or longer) where the
model *still* has a positive expected value against the de-vigged market. High
odds alone never qualify — the guardrail is EV, not price.

Three sections:
  1. Conviction longshots — every qualifying straight, ranked by EV at the long
     price, tagged by whether the market, the model, or both see a dog.
  2. Reading between the lines — for game-level dogs, the matchup facets
     (scheme fit, trenches, pace…) that argue for the upset, from the edge engine.
  3. Correlated long parlays — small stacks from the conviction pool for the
     big-payout swing, correlation-priced.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betengine, edges, loaders, props

# A "long" price. +200 = 3.00 decimal = the market implies <= 33%.
_LONG_AMERICAN = 200
_LONG_DECIMAL = betengine.american_to_decimal(_LONG_AMERICAN)


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


def _ev(model_prob: float, american: float) -> float:
    """Expected value per 1 unit staked at ``american`` odds given model_prob."""
    if pd.isna(model_prob) or pd.isna(american):
        return float("nan")
    dec = betengine.american_to_decimal(american)
    return model_prob * (dec - 1) - (1 - model_prob)


def _long_pool(board: pd.DataFrame) -> pd.DataFrame:
    """Qualifying long bets: long price (market or fair) AND +EV vs the market."""
    if board is None or board.empty:
        return pd.DataFrame()
    b = board.copy()
    b["ev"] = [
        _ev(p, o) for p, o in zip(b["model_prob"], b["market_odds"])
    ]
    market_long = b["market_odds"].fillna(-1000) >= _LONG_AMERICAN
    fair_long = b["fair_odds"].fillna(-1000) >= _LONG_AMERICAN
    # The guardrail: the model must beat the de-vigged price (edge > 0) AND the
    # bet must actually be +EV at the offered long number.
    qualifies = (market_long | fair_long) & (b["edge"].fillna(-1) > 0) & (b["ev"] > 0)
    pool = b[qualifies].copy()
    if pool.empty:
        return pool

    def _tag(row):
        m, f = row["market_odds"], row["fair_odds"]
        m_long = pd.notna(m) and m >= _LONG_AMERICAN
        f_long = pd.notna(f) and f >= _LONG_AMERICAN
        if m_long and f_long:
            return "Model + market dog"
        if m_long:
            return "Market overpricing"   # market longer than our fair → value
        return "Model longshot"
    pool["tag"] = pool.apply(_tag, axis=1)
    return pool.sort_values("ev", ascending=False).reset_index(drop=True)


_TAG_RAIL = {"Model + market dog": "edge", "Market overpricing": "sharp",
             "Model longshot": "violet"}


def _hero_cards(pool: pd.DataFrame) -> None:
    """The top conviction plays as number-forward cards before the full table."""
    from ui import kit
    top = pool.head(3)
    cols = st.columns(len(top))
    for col, (_, r) in zip(cols, top.iterrows()):
        rail = _TAG_RAIL.get(r["tag"], "accent")
        price = betengine.fmt_odds(r["market_odds"])
        ev_chip = kit.chip(f"EV {r['ev'] * 100:+.0f}%", "edge")
        line1 = f"{r['selection']}"
        meta = f"{r['market']} · {r['game']}"
        sub = f"model {r['model_prob'] * 100:.0f}% · edge {r['edge'] * 100:+.1f} · {r['tag']}"
        col.markdown(
            f'<div class="k-bet" style="--kbet:var(--{rail})">'
            f'<div class="sel">{line1}</div>'
            f'<div class="meta">{meta}</div>'
            f'<div class="row">'
            f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:1.35rem;font-weight:700;'
            f'color:var(--edge)">{price}</span>{ev_chip}</div>'
            f'<div class="row"><span class="meta">{sub}</span></div>'
            f'</div>', unsafe_allow_html=True)


def _conviction(pool: pd.DataFrame) -> None:
    st.markdown("### Conviction longshots")
    st.caption("Every straight priced **+200 or longer** where the model still shows positive EV against "
               "the de-vigged line — ranked by expected value at the long price. Price alone never "
               "qualifies a bet here.")
    if pool.empty:
        st.info("No +200-or-longer plays clear the EV guardrail on this slate. That's the discipline "
                "working — no garbage longshots.")
        return
    _hero_cards(pool)
    view = pool.head(14)
    show = pd.DataFrame({
        "Bet": view["selection"], "Market": view["market"], "Game": view["game"],
        "Type": view["tag"],
        "Model %": (view["model_prob"] * 100).round(0),
        "Fair": view["fair_odds"].map(betengine.fmt_odds),
        "Price": view["market_odds"].map(betengine.fmt_odds),
        "Edge %": (view["edge"] * 100).round(1),
        "EV": (view["ev"] * 100).round(1),
        "Kelly": (view["kelly"] * 100).round(2),
    })
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "Model %": st.column_config.NumberColumn("Model %", format="%d%%",
            help="Model probability the bet cashes."),
        "Edge %": st.column_config.NumberColumn("Edge %", format="%+.1f",
            help="Model probability minus the de-vigged market price."),
        "EV": st.column_config.NumberColumn("EV", format="%+.1f%%",
            help="Expected value per unit staked at the offered price."),
        "Kelly": st.column_config.NumberColumn("Kelly", format="%.2fu"),
    })
    st.caption("Size these small — long prices are high-variance by nature. EV is the reason they're "
               "here, not the payout.")


def _ev_scatter(pool: pd.DataFrame) -> None:
    """Risk/reward map: market-implied chance vs our model chance. Above the line = value."""
    if pool.empty:
        return
    import plotly.graph_objects as go
    from ui import kit
    P = kit.PALETTE
    st.markdown("### Risk / reward map")
    st.caption("Each play: the market's implied chance (x) vs our model's chance (y). Points **above the "
               "line** are ones we think hit more often than the price implies — the value is up and to the left.")
    xs = [betengine.implied_prob(o) * 100 for o in pool["market_odds"]]
    ys = [p * 100 for p in pool["model_prob"]]
    labels = [str(s).split(" ")[0] for s in pool["selection"]]
    hover = [f"{r.selection} · {betengine.fmt_odds(r.market_odds)} · EV {r.ev*100:+.0f}%"
             for r in pool.itertuples()]
    hi = max(xs + ys + [40]) + 6
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, hi], y=[0, hi], mode="lines", hoverinfo="skip",
                             line=dict(color=P["ink_faint"], dash="dash"), showlegend=False))
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=labels, textposition="top center",
        textfont=dict(color=P["ink_dim"], size=10), hovertext=hover, hoverinfo="text",
        marker=dict(size=[max(9, min(30, e * 120)) for e in pool["ev"]],
                    color=P["accent"], opacity=.85, line=dict(color=P["accent_bright"], width=1)),
        showlegend=False))
    fig.update_layout(height=380, margin=dict(l=6, r=6, t=6, b=6),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=P["ink_dim"]),
                      xaxis=dict(title="Market implied %", gridcolor=P["line"], zeroline=False),
                      yaxis=dict(title="Model %", gridcolor=P["line"], zeroline=False))
    st.plotly_chart(fig, width="stretch")


def _between_lines(pool: pd.DataFrame, off, deff, extras) -> None:
    st.markdown("### Reading between the lines")
    st.caption("For the game-level dogs above, the matchup facets that argue for the upset — scheme fit, "
               "trenches, pace, and the rest of the edge engine. A live dog that *wins the mismatches* "
               "is the play this tab is built for.")
    game_dogs = pool[pool["market"].isin(["Moneyline", "Spread", "Total"])].head(6)
    if game_dogs.empty:
        st.info("No game-level longshots to break down this week (the pool is props-only).")
        return
    shown = 0
    seen = set()
    for _, b in game_dogs.iterrows():
        gid = b["corr_group"]
        if gid in seen:
            continue
        seen.add(gid)
        # the underdog side is the team named first in the selection
        game = b["game"]
        try:
            away, home = [t.strip() for t in game.split("@")]
        except ValueError:
            continue
        # gather both directions' facet edges, show the ones favoring the dog side
        angles = []
        for o_team, d_team in ((away, home), (home, away)):
            for e in edges.facet_edges(o_team, d_team, off, deff, extras):
                if e["impact"] >= 8:
                    angles.append((o_team, e))
        angles.sort(key=lambda x: x[1]["impact"], reverse=True)
        if not angles:
            continue
        shown += 1
        top = angles[:4]
        chips = " · ".join(f"<b>{o}</b> {e['label']} ({e['detail']})" for o, e in top)
        st.markdown(
            f"<div style='border-left:3px solid var(--edge);padding:6px 0 6px 12px;margin:8px 0;'>"
            f"<b>{b['selection']}</b> <span style='color:var(--ink-faint);'>· {b['market']} · {game} · "
            f"{betengine.fmt_odds(b['market_odds'])}</span><br>"
            f"<span style='color:var(--ink-dim);font-size:0.9rem;'>{chips}</span></div>",
            unsafe_allow_html=True)
    if shown == 0:
        st.info("No standout supporting angles cleared the bar for this week's longshots.")


def _long_parlays(pool: pd.DataFrame) -> None:
    st.markdown("### Correlated long parlays")
    st.caption("Small stacks from the conviction pool for the big-payout swing — one leg per game first "
               "to limit correlation, then priced with the same correlation model as the Picks parlays.")
    if len(pool) < 2:
        st.info("Need at least 2 conviction longshots to stack a parlay.")
        return
    # diversify across games
    seen, ordered = set(), []
    for _, b in pool.iterrows():
        if b["corr_group"] not in seen:
            ordered.append(b.to_dict())
            seen.add(b["corr_group"])
    for _, b in pool.iterrows():
        if b["corr_group"] in seen and b.to_dict() not in ordered:
            ordered.append(b.to_dict())
    rows, details = [], {}
    for k in (2, 3, 4):
        if len(ordered) < k:
            break
        legs = ordered[:k]
        par = betengine.parlay(legs)
        rows.append({
            "Stack": f"{k}-leg",
            "Combined": betengine.fmt_odds(par["american"]),
            "Model hit %": round(par["model_prob"] * 100, 1),
            "EV": round(par["ev"] * 100, 1),
            "Kelly": round(par["kelly"] * 100, 2),
        })
        details[f"{k}-leg"] = legs
    if not rows:
        st.info("Not enough diversified legs to build a long parlay.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
        "Model hit %": st.column_config.NumberColumn("Model hit %", format="%.1f%%"),
        "EV": st.column_config.NumberColumn("EV", format="%+.1f%%"),
        "Kelly": st.column_config.NumberColumn("Kelly", format="%.2fu"),
    })
    for name, legs in details.items():
        with st.expander(f"{name} — the legs"):
            st.dataframe(pd.DataFrame({
                "Leg": [l["selection"] for l in legs],
                "Market": [l["market"] for l in legs],
                "Game": [l["game"] for l in legs],
                "Model %": [round(l["model_prob"] * 100) for l in legs],
                "Price": [betengine.fmt_odds(l["market_odds"]) for l in legs],
            }), width="stretch", hide_index=True)
    st.caption("A tiny ticket only — the combined price is the point, and long parlays bust often. "
               "Never the bankroll.")


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Long Odds — +200 with conviction")
    st.caption("The model's creative freedom: high-conviction plays at a long price that don't fit the "
               "safe or edge boards. Same engine as every other tab — game bets and prop projections "
               "priced against the de-vigged market — kept only where the EV survives at +200 or longer.")
    if off.empty or deff.empty:
        st.info("Load data first (needs offensive & defensive numbers).")
        return
    season = config.CURRENT_SEASON
    if schedule is None or schedule.empty or not (schedule["season"] == season).any():
        st.info("Schedule not loaded for the current season yet.")
        return
    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    wk = st.selectbox(f"Week ({season})", weeks,
                      index=weeks.index(default_wk) if default_wk in weeks else 0, key="long_week")
    games = s[s["week"] == wk]
    gp = _games_played(extras)

    priced = games[games["spread_line"].notna()] if "spread_line" in games.columns else games.iloc[0:0]
    rows = []
    for _, r in priced.iterrows():
        rows.extend(betengine.game_bets(r, off, deff, extras, gp))
    board = pd.DataFrame(rows) if rows else pd.DataFrame()
    stats = extras.get("players")
    prop_df = (props.auto_prop_picks(stats, off, deff, extras, games, games_played=gp)
               if stats is not None and not stats.empty else pd.DataFrame())
    prop_bets = props.leans_to_bets(prop_df, gp)
    if prop_bets:
        board = pd.concat([board, pd.DataFrame(prop_bets)], ignore_index=True)

    pool = _long_pool(board)
    from ui import kit
    c1, c2, c3 = st.columns(3)
    c1.markdown(kit.kpi("Qualifying longshots", str(len(pool)),
                        "+EV at a long price", None, "accent" if len(pool) else "mute"),
                unsafe_allow_html=True)
    c2.markdown(kit.kpi("Best EV", f"{pool['ev'].max()*100:+.0f}%" if not pool.empty else "—",
                        "top play", "up" if not pool.empty else None,
                        "edge" if not pool.empty else "mute"), unsafe_allow_html=True)
    c3.markdown(kit.kpi("Longest price",
                        betengine.fmt_odds(pool["market_odds"].max()) if not pool.empty else "—",
                        "biggest swing", None, "violet" if not pool.empty else "mute"),
                unsafe_allow_html=True)
    st.divider()
    _conviction(pool)
    if not pool.empty:
        st.divider()
        _ev_scatter(pool)
    st.divider()
    _between_lines(pool, off, deff, extras)
    st.divider()
    _long_parlays(pool)
