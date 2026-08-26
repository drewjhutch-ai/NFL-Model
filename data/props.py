"""Player-prop projections as distributions, not point numbers.

A 62-yard projection isn't a bet — P(over 54.5) is. This turns each player's
matchup-adjusted projected mean into an over/under probability by modeling the
stat's game-to-game spread: yards are wide (a normal around the mean with a
stat-specific spread), touchdowns are rare events (Poisson). Feed it a line and
it returns the probability and a fair price; with no line it just projects.

Means come from data.players.project (usage × matchup). Game script and pace from
the Matchups sim can scale volume before we compute the distribution.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from data import betengine, players

# Coefficient of variation (sd / mean) for a single game, by stat. Rough but
# grounded: yardage is high-variance, volume counts less so, passing yards tight.
_CV = {
    "Rec yds": 0.62, "Rush yds": 0.58, "Pass yds": 0.24,
    "Rec": 0.42, "Targets": 0.34, "Carries": 0.30,
}
_POISSON = {"Pass TD"}
# The props worth surfacing, in display order.
PROP_STATS = ["Pass yds", "Pass TD", "Rush yds", "Carries", "Rec yds", "Rec", "Targets"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def over_prob(mean: float, line: float, stat: str) -> float:
    """P(stat > line) for a projected ``mean``. Normal for yards/volume, Poisson for TDs."""
    if pd.isna(mean) or pd.isna(line) or mean <= 0:
        return np.nan
    if stat in _POISSON:
        # P(X > line) with X ~ Poisson(mean); line usually 0.5/1.5
        k = math.floor(line)
        cdf = sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(k + 1))
        return float(1 - cdf)
    cv = _CV.get(stat, 0.45)
    sd = max(mean * cv, 1e-6)
    return float(1 - _norm_cdf((line - mean) / sd))


def project_player(player: pd.Series, opp: str, deff: pd.DataFrame, dvp: dict,
                   script: float = 0.0) -> dict:
    """Matchup-adjusted projected means, optionally nudged by game script.

    ``script`` is the team's projected margin (+ = favored). A favored team runs
    more late (bump carries, trim pass volume); an underdog throws more.
    """
    proj = players.project(player, opp, deff, dvp)
    if script and proj:
        pass_bump = 1 - min(max(script, -14), 14) / 100.0   # dog throws more
        rush_bump = 1 + min(max(script, -14), 14) / 120.0   # favorite runs more
        for k in ("Pass yds", "Rec yds", "Rec", "Targets"):
            if k in proj:
                proj[k] *= pass_bump
        for k in ("Rush yds", "Carries"):
            if k in proj:
                proj[k] *= rush_bump
    return proj


def prop_bets(player: pd.Series, proj: dict, game_id: str, game: str, opp: str,
              lines: dict | None = None, games_played: int = 0) -> list[dict]:
    """Turn a player's projections into Bet-Engine rows (edge needs a line).

    ``lines``: {stat: line}. For each stat with a line, the over/under side the
    model prefers becomes a bet at -110 both ways. Without a line, nothing is
    emitted (a projection isn't a bet).
    """
    if not proj or not lines:
        return []
    out = []
    name = player.get("name", "?")
    for stat, line in lines.items():
        mean = proj.get(stat)
        if mean is None or pd.isna(mean) or line is None or pd.isna(line):
            continue
        p_over = over_prob(mean, float(line), stat)
        if pd.isna(p_over):
            continue
        if p_over >= 0.5:
            sel, p = f"{name} {stat} Over {line:g}", p_over
        else:
            sel, p = f"{name} {stat} Under {line:g}", 1 - p_over
        out.append(betengine._bet(
            game_id, game, "Player prop", sel, p, -110, -110, game_id, games_played,
            f"Projected {mean:.1f} vs line {line:g} ({stat}) vs {opp}."))
    return out
