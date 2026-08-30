"""NFL Elo — an independent power rating for the ensemble.

Elo is the classic, robust team-strength model (FiveThirtyEight's NFL ratings are
Elo). It's valuable here for two reasons the EPA model can't cover on its own:

  * **Diversity** — it's built purely from game *results* (who beat whom, by how
    much), an orthogonal signal to play-by-play efficiency. Averaging two
    uncorrelated models beats either alone.
  * **A principled early-season prior** — at each season's start every team is
    regressed a third of the way back to the mean, so Week 1 carries last year
    (regressed), and the rating firms up as games are played. That's exactly the
    Bayesian "shrink to a prior, scaled by sample" behavior early-season models
    need, for free.

Ratings map to points at the standard ~25 Elo ≈ 1 point.
"""
from __future__ import annotations

import math

import pandas as pd

BASE = 1500.0
K = 20.0                 # update speed
HFA_ELO = 48.0           # home edge in Elo points (~1.9 pts)
REVERT = 0.33            # season-start regression toward the mean (the prior)
PTS_PER_ELO = 25.0       # ~25 Elo points = 1 point of margin


def _mov_mult(margin: float, elo_diff: float) -> float:
    """538's margin-of-victory multiplier — bigger wins move more, with an
    autocorrelation correction so favorites blowing out weak teams don't run away."""
    return math.log(abs(margin) + 1) * (2.2 / ((elo_diff * 0.001) + 2.2))


def elo_ratings(schedule: pd.DataFrame, before_season: int | None = None,
                before_week: int | None = None) -> pd.Series:
    """Current Elo rating per team from played games, processed chronologically.

    ``before_season``/``before_week`` cap the games used (train-honest for the
    backtest): only games strictly before that (season, week) count.
    """
    if schedule is None or schedule.empty or "result" not in schedule.columns:
        return pd.Series(dtype=float)
    played = schedule[schedule["result"].notna()].copy()
    if played.empty:
        return pd.Series(dtype=float)
    played = played.sort_values(["season", "week"])
    rating: dict[str, float] = {}
    last_season: dict[str, int] = {}
    for _, g in played.iterrows():
        s, wk = int(g["season"]), int(g["week"])
        if before_season is not None:
            if s > before_season or (s == before_season and before_week is not None and wk >= before_week):
                continue
        h, a = g.get("home_team"), g.get("away_team")
        margin = g.get("result")  # home - away
        if not isinstance(h, str) or not isinstance(a, str) or pd.isna(margin):
            continue
        for t in (h, a):
            if t not in rating:
                rating[t] = BASE
            # regress toward the mean at the start of a new season (the prior)
            if last_season.get(t) is not None and s > last_season[t]:
                rating[t] = BASE + (1 - REVERT) * (rating[t] - BASE)
            last_season[t] = s
        rh, ra = rating[h] + HFA_ELO, rating[a]
        exp_h = 1.0 / (1.0 + 10 ** (-(rh - ra) / 400))
        res_h = 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
        mult = _mov_mult(margin if margin != 0 else 1, (rh - ra) if res_h else (ra - rh))
        delta = K * mult * (res_h - exp_h)
        rating[h] += delta
        rating[a] -= delta
    return pd.Series(rating)


def expected_margin(elo: pd.Series, home: str, away: str) -> float:
    """Neutral-field expected home margin in points (HFA added separately upstream)."""
    if elo is None or len(elo) == 0 or home not in elo.index or away not in elo.index:
        return float("nan")
    return float((elo[home] - elo[away]) / PTS_PER_ELO)
