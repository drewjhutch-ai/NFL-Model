"""Backtesting, calibration, and the learning loop.

This is what makes the model *evolve* instead of sit on hand-picked numbers:

  * ``walk_forward`` re-derives ratings from only the games played *before* each
    week and projects that week — honest, out-of-sample accuracy (margin error,
    ATS, straight-up, calibration, and how we compare to the market).
  * ``facet_predictiveness`` measures how well each matchup facet's edge actually
    tracked real game margins, and suggests weights from that — so the model can
    learn which signals are working this era, not just what we assumed.

Runs offline (scripts/backtest.py) and caches results the app can display.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data import adjust, betting, edges, positional, situational, tendencies


def _season_pbp(pbp_all: pd.DataFrame, season: int) -> pd.DataFrame:
    df = pbp_all[pbp_all["season"] == season].copy()
    df["w"] = 1.0
    return df


def _ratings(train: pd.DataFrame):
    off = tendencies.compute_offense(train)
    deff = tendencies.compute_defense(train)
    off, deff = adjust.apply_epa_adjustment(off, deff, train)
    tendencies.compute_qb_rank(off)
    pace = None
    if not train.empty:
        p = train.groupby("posteam").agg(n=("epa", "size"), g=("game_id", "nunique"))
        pace = (p["n"] / p["g"]).rename("pace")
    return off, deff, pace


def walk_forward(pbp_all: pd.DataFrame, schedule: pd.DataFrame, season: int,
                 start_week: int = 5) -> pd.DataFrame:
    """Out-of-sample: train on prior weeks, project each week, score vs results."""
    sp = _season_pbp(pbp_all, season)
    games = schedule[(schedule["season"] == season) & schedule["result"].notna()
                     & schedule["spread_line"].notna()]
    rows = []
    for wk in sorted(int(w) for w in games["week"].unique()):
        if wk < start_week:
            continue
        train = sp[sp["week"] < wk]
        if train.empty:
            continue
        off, deff, pace = _ratings(train)
        # points differential from games played *before* this week (honest)
        pts = betting.points_ratings(schedule, season, before_week=wk)
        extras = {"pace": pace, "points_rtg": pts}
        for _, r in games[games["week"] == wk].iterrows():
            a = betting.assess(r, off, deff, extras)
            if pd.isna(a["model_margin"]):
                continue
            actual = r["result"]                       # home margin
            mkt = a["mkt_spread"]
            rows.append({
                "week": wk, "game": f"{a['away']}@{a['home']}",
                "model": a["model_margin"], "market": mkt, "actual": actual,
                "p_home": a["model_p_home"], "home_win": int(actual > 0),
                "ats_hit": int((a["model_margin"] > mkt) == (actual > mkt)) if pd.notna(mkt) else np.nan,
                "su_hit": int((a["model_margin"] > 0) == (actual > 0)),
            })
    return pd.DataFrame(rows)


def summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {}
    out = {
        "games": len(res),
        "model_mae": float((res["model"] - res["actual"]).abs().mean()),
        "market_mae": float((res["market"] - res["actual"]).abs().mean())
        if res["market"].notna().any() else None,
        "ats_pct": float(res["ats_hit"].mean() * 100) if res["ats_hit"].notna().any() else None,
        "su_pct": float(res["su_hit"].mean() * 100),
    }
    # win-prob calibration (predicted vs actual by bucket)
    r = res.dropna(subset=["p_home"])
    if not r.empty:
        buckets = pd.cut(r["p_home"], [0, .35, .5, .65, .8, 1.0])
        cal = r.groupby(buckets, observed=True).agg(pred=("p_home", "mean"),
                                                    actual=("home_win", "mean"),
                                                    n=("home_win", "size"))
        out["calibration"] = cal.round(3).reset_index().astype(str).to_dict("records")
    return out


def facet_predictiveness(pbp_all: pd.DataFrame, schedule: pd.DataFrame, season: int) -> pd.DataFrame:
    """Correlate each facet's net edge with actual game margin (single-fit).

    Suggested weight ∝ how well that facet tracked real outcomes — the basis for
    letting the weights learn from results.
    """
    sp = _season_pbp(pbp_all, season)
    off, deff, pace = _ratings(sp)
    posmap = {}
    try:
        from data import loaders
        posmap = loaders.position_map((season,))
    except Exception:  # noqa: BLE001
        pass
    extras = {
        "dvp": positional.defense_vs_position(sp, posmap),
        "usage": positional.offense_usage(sp, posmap),
        "off_sit": situational.offense_situational(sp),
        "def_sit": situational.defense_situational(sp),
        "pace": pace,
    }
    games = schedule[(schedule["season"] == season) & schedule["result"].notna()]
    recs = []
    for _, r in games.iterrows():
        home, away = r["home_team"], r["away_team"]
        he = {e["label"]: e["mag"] for e in edges.facet_edges(home, away, off, deff, extras)}
        ae = {e["label"]: e["mag"] for e in edges.facet_edges(away, home, off, deff, extras)}
        row = {"margin": r["result"]}
        for label in set(he) | set(ae):
            row[label] = he.get(label, 0) - ae.get(label, 0)   # net, home-relative
        recs.append(row)
    df = pd.DataFrame(recs)
    if df.empty:
        return pd.DataFrame()
    cors = {}
    for c in df.columns:
        if c == "margin":
            continue
        if df[c].std() > 0:
            cors[c] = df[c].corr(df["margin"])
    s = pd.Series(cors).sort_values(ascending=False)
    out = pd.DataFrame({"correlation": s})
    pos = s.clip(lower=0)
    out["suggested_weight"] = (pos / pos.sum() * len(pos) * 1.2).round(2) if pos.sum() else 0
    out["current_weight"] = [config.EDGE_WEIGHTS.get(i, config.DEFAULT_EDGE_WEIGHT) for i in out.index]
    return out
