"""Market-implied power ratings — team strength backed out of the betting lines.

The closing spread is the sharpest public estimate of a game's margin: it folds
in everything the market knows (injuries, matchups, situation, money). One line
is one game, but a whole *season* of lines is an over-determined system —

    spread(home, away) ≈ rating[home] - rating[away] + HFA

so we can solve for the set of team ratings that best reproduces every posted
spread. That's a market power rating: what the betting market thinks each team
is worth, in points, on a neutral field. It's the single strongest signal we can
add, because it's the aggregate of every sharp bettor's model, not just ours.

We solve it as a ridge-regularised least squares (a rating-difference system is a
graph Laplacian; ridge keeps it stable and shrinks toward average early in the
year when few games have been played). Schedules carry `spread_line` for *future*
games too, so this is usable from Week 1. Ratings are centred at 0 = average team,
and `expected_margin` turns a pair back into a neutral-field margin.

Used as an ensemble member in `betting.project_margin` (weight `MARKET_WEIGHT`)
and surfaced as a power ranking. It intentionally overlaps the game-level market
blend in `assess`; both pull toward market truth, which is the house edge we've
decided to respect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def market_power_ratings(schedule: pd.DataFrame, season: int | None = None,
                         hfa: float | None = None) -> pd.Series:
    """Team ratings (points vs an average team, neutral field) from closing spreads.

    Returns an empty Series when there aren't enough posted lines to solve.
    """
    if schedule is None or getattr(schedule, "empty", True) or "spread_line" not in schedule.columns:
        return pd.Series(dtype=float)
    hfa = config.HOME_FIELD_ADVANTAGE if hfa is None else hfa

    s = schedule[schedule["spread_line"].notna()].copy()
    if season is not None and "season" in s.columns:
        cur = s[s["season"] == season]
        # need a connected-enough graph; fall back to all seasons present as a prior
        s = cur if len(cur) >= 8 else s
    if len(s) < 4:
        return pd.Series(dtype=float)

    teams = sorted(set(s["home_team"].dropna()) | set(s["away_team"].dropna()))
    if len(teams) < 2:
        return pd.Series(dtype=float)
    idx = {t: i for i, t in enumerate(teams)}
    n, m = len(teams), len(s)

    A = np.zeros((m, n))
    b = np.zeros(m)
    for r, g in enumerate(s.itertuples(index=False)):
        h, a = getattr(g, "home_team"), getattr(g, "away_team")
        if h not in idx or a not in idx:
            continue
        A[r, idx[h]] = 1.0
        A[r, idx[a]] = -1.0
        # spread_line: + = home favored = expected home margin. Strip HFA -> neutral.
        b[r] = float(getattr(g, "spread_line")) - hfa

    lam = float(getattr(config, "MARKET_RATING_RIDGE", 1.0))
    try:
        x = np.linalg.solve(A.T @ A + lam * np.eye(n), A.T @ b)
    except np.linalg.LinAlgError:
        x, *_ = np.linalg.lstsq(A, b, rcond=None)
    x = x - float(np.mean(x))                       # centre: 0 = average team
    return pd.Series(x, index=teams).sort_values(ascending=False)


def expected_margin(ratings: pd.Series, home: str, away: str,
                    hfa: float | None = None) -> float:
    """Neutral ratings + home field -> expected home margin (+ = home favored)."""
    if ratings is None or len(ratings) == 0 or home not in ratings.index or away not in ratings.index:
        return np.nan
    hfa = config.HOME_FIELD_ADVANTAGE if hfa is None else hfa
    return float(ratings[home] - ratings[away]) + hfa
