"""Early-season talent prior — empirical-Bayes shrinkage for team ratings.

One noisy game shouldn't crown a bad team. In Week 2 the model has a single
current-season game per team, and with the prior season weighted to a whisper it
would let that lone game drive every ranking, spread, and prop — so a bad team
that beat a worse one can look like a live underdog when it's really just noise.

This module regresses the (still thin) current-season ratings toward a **preseason
talent prior** and decays that anchor as real games accumulate:

    weight_current = games_played / (games_played + K)      # K ≈ 5 pseudo-games

At 0 games the ratings are all prior (last year's proven quality + Vegas win
totals); by ~Week 6 they're mostly current; by ~Week 12 the prior has faded out.
The prior itself is:

    * prior-season EPA/play per team (offense and defense) — proven, stable, and
      already loaded, so it needs no network, and
    * Vegas win totals (optional committed file) — the market's distilled read on
      talent and pedigree, which catches offseason changes last year's EPA can't.

It's applied to the shared offense/defense frames in the pipeline, so **every**
consumer inherits the anchored ratings: rankings (Team Data, League), matchup
edges (Matchups, Picks), spreads/totals/moneylines (Betting, Game Bets, Long
Odds), and player props / touchdowns (whose projections read the opponent's
defensive ranks and the game script). The point-differential rating is anchored
the same way so the margin's scoreboard signal doesn't reintroduce one-game noise.
"""
from __future__ import annotations

import pandas as pd

import config

_EPA_COLS = ("epa_play", "pass_epa", "rush_epa")
_WT_MIDPOINT = 8.5   # a .500 season; win totals above this imply a positive team


def current_games_played(pbp: pd.DataFrame, season: int) -> int:
    """How many games each team has ~played this season (completed weeks)."""
    if pbp is None or getattr(pbp, "empty", True) or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == season]
    if cur.empty or "week" not in cur.columns:
        return 0
    return int(cur["week"].dropna().nunique())


def blend_alpha(games_played: int, k: float | None = None) -> float:
    """Current-season weight g/(g+k): 0 = all prior, 1 = all current-season."""
    k = config.EARLY_SEASON_PRIOR_K if k is None else k
    g = max(0, int(games_played))
    return g / (g + k) if (g + k) > 0 else 1.0


def prior_epa(pbp_all: pd.DataFrame, prior_season: int) -> tuple[pd.Series, pd.Series]:
    """Prior-season offense & defense EPA/play per team — the stable talent base.

    Returns (off_prior, def_prior) in EPA/play (offense: higher is better; defense:
    lower/negative is better). Empty Series if the prior season isn't loaded.
    """
    empty = (pd.Series(dtype=float), pd.Series(dtype=float))
    if pbp_all is None or getattr(pbp_all, "empty", True) or "season" not in pbp_all.columns:
        return empty
    p = pbp_all[(pbp_all["season"] == prior_season) & pbp_all["epa"].notna()]
    if p.empty:
        return empty
    off = p.groupby("posteam")["epa"].mean()
    deff = p.groupby("defteam")["epa"].mean()
    return off, deff


def _wt_epa_shift(win_totals: pd.Series | None, teams) -> pd.Series:
    """Per-team EPA/play shift implied by Vegas win totals (0 where absent).

    A win total above the .500 midpoint implies a positive net team; each win is
    worth ~``POINTS_PER_WIN`` points of net margin, converted to EPA/play over a
    game's plays. Split half to offense, half to defense by the caller.
    """
    if win_totals is None or len(win_totals) == 0:
        return pd.Series(0.0, index=teams)
    net_pts = (win_totals - _WT_MIDPOINT) * config.POINTS_PER_WIN
    net_epa = net_pts / config.PLAYS_PER_TEAM
    return net_epa.reindex(teams).fillna(0.0)


def prior_net_rating(off_prior: pd.Series, def_prior: pd.Series,
                     win_totals: pd.Series | None = None) -> pd.Series:
    """Preseason net rating per team in POINTS (expected margin vs an average team).

    Prior-season net EPA converted to points, blended with the win-total net when
    a win-totals file is present. Used to anchor the point-differential rating.
    """
    if off_prior is None or off_prior.empty:
        if win_totals is not None and len(win_totals):
            return ((win_totals - _WT_MIDPOINT) * config.POINTS_PER_WIN).fillna(0.0)
        return pd.Series(dtype=float)
    teams = off_prior.index.union(def_prior.index)
    net_epa = off_prior.reindex(teams).fillna(0.0) - def_prior.reindex(teams).fillna(0.0)
    net_pts = net_epa * config.PLAYS_PER_TEAM
    if win_totals is not None and len(win_totals):
        wt_pts = ((win_totals - _WT_MIDPOINT) * config.POINTS_PER_WIN).reindex(teams)
        net_pts = 0.6 * net_pts + 0.4 * wt_pts.fillna(net_pts)
    return net_pts.fillna(0.0)


def shrink_ratings(off_df: pd.DataFrame, def_df: pd.DataFrame,
                   off_prior: pd.Series, def_prior: pd.Series, alpha: float,
                   win_totals: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blend current EPA ratings toward the prior and re-rank. ``alpha`` = current weight.

    Mutates and returns (off_df, def_df). A no-op when the prior is unavailable or
    alpha ≈ 1 (mid/late season). Re-ranks the EPA columns and the QB score so every
    downstream rank reflects the anchored rating.
    """
    if off_df is None or getattr(off_df, "empty", True) or alpha >= 0.999:
        return off_df, def_df
    if (off_prior is None or off_prior.empty) and (win_totals is None or len(win_totals) == 0):
        return off_df, def_df
    from data.tendencies import _rank, compute_qb_rank
    teams = off_df.index
    wt_shift = _wt_epa_shift(win_totals, teams)

    for col in _EPA_COLS:
        if col in off_df.columns:
            prior = off_df.index.to_series().map(off_prior) if not off_prior.empty else pd.Series(index=teams, dtype=float)
            prior = prior + 0.5 * wt_shift               # better team → higher offense EPA
            prior = prior.fillna(off_df[col])            # no prior for a team → keep current
            off_df[col] = alpha * off_df[col] + (1 - alpha) * prior
            off_df[col + "_rank"] = _rank(off_df[col], best_high=True)
        if col in def_df.columns:
            prior = def_df.index.to_series().map(def_prior) if not def_prior.empty else pd.Series(index=def_df.index, dtype=float)
            prior = prior - 0.5 * wt_shift.reindex(def_df.index).fillna(0.0)  # better team → allows less
            prior = prior.fillna(def_df[col])
            def_df[col] = alpha * def_df[col] + (1 - alpha) * prior
            def_df[col + "_rank"] = _rank(def_df[col], best_high=False)
    compute_qb_rank(off_df)   # QB score rides on pass_epa — recompute after shrink
    return off_df, def_df


def shrink_points(points_rtg: pd.Series, prior_net: pd.Series, alpha: float) -> pd.Series:
    """Blend the point-differential rating toward the preseason net rating.

    Keeps the margin's scoreboard signal from swinging on one game's result early.
    """
    if points_rtg is None or len(points_rtg) == 0:
        return prior_net if prior_net is not None and len(prior_net) else points_rtg
    if prior_net is None or len(prior_net) == 0 or alpha >= 0.999:
        return points_rtg
    teams = points_rtg.index.union(prior_net.index)
    cur = points_rtg.reindex(teams).fillna(0.0)
    pri = prior_net.reindex(teams).fillna(0.0)
    return alpha * cur + (1 - alpha) * pri


def load_win_totals(season: int) -> pd.Series | None:
    """Vegas preseason win totals from data/win_totals_<season>.csv, or None.

    File format: two columns, ``team`` (abbr) and ``win_total`` (e.g. 10.5). It's
    a preseason constant, so it's committed once and edited by hand. Absent → the
    prior falls back to prior-season EPA alone.
    """
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / f"win_totals_{season}.csv"
    if not path.exists():
        return None
    try:
        from data.teams import normalize_team
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        tcol = cols.get("team")
        wcol = cols.get("win_total") or cols.get("wins") or cols.get("total")
        if not tcol or not wcol:
            return None
        df["_t"] = df[tcol].map(lambda x: normalize_team(x) if isinstance(x, str) else x)
        df["_w"] = pd.to_numeric(df[wcol], errors="coerce")
        s = df.dropna(subset=["_t", "_w"]).set_index("_t")["_w"]
        return s[s > 0] if not s.empty else None
    except Exception:  # noqa: BLE001 - a bad file must never break the build
        return None
