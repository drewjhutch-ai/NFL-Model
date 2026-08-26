"""The Bet Engine — one board every market competes on.

A "bet" is the same shape whether it's a moneyline, a spread, a total, a team
total, or a player prop: a selection with a model probability, a fair price, the
market price, the edge against the no-vig line, a Kelly stake, and a confidence.
Betting, Picks, and Parlays all read this one board, so nothing is priced twice
and every bet type — anything a book offers — competes head to head.

Probabilities come from the game simulation (sides/totals/ML) and the prop model
(players). Edge is always measured against the *de-vigged* market, so "value"
means value vs the true price, not the padded one.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config
from data import betting, simulation

# Standard flat juice for point-spread / total markets when a real price is absent.
_STD_ODDS = -110


# --- american-odds math ------------------------------------------------------
def american_to_decimal(a: float) -> float:
    a = float(a)
    return 1 + (100 / abs(a) if a < 0 else a / 100)


def decimal_to_american(dec: float) -> int:
    if dec <= 1:
        return 0
    return int(round(-100 / (dec - 1))) if dec < 2 else int(round((dec - 1) * 100))


def implied_prob(a: float) -> float:
    return betting.implied_prob(a)


def fair_odds(prob: float) -> int | None:
    return betting.fair_moneyline(prob)


def novig_prob(odds_side: float, odds_other: float) -> float:
    """De-vig a two-way market: this side's fair probability."""
    ps, po = implied_prob(odds_side), implied_prob(odds_other)
    if pd.isna(ps) or pd.isna(po) or (ps + po) == 0:
        return np.nan
    return ps / (ps + po)


def fmt_odds(a) -> str:
    if a is None or pd.isna(a):
        return "—"
    a = int(round(a))
    return f"{a:+d}"


# --- confidence --------------------------------------------------------------
def confidence(model_prob: float, edge: float, games_played: int = 0) -> float:
    """0–100 confidence: decisiveness × edge, damped by sample size.

    Not the odds — a heavy favorite and a live dog can both score high. Early in
    the season (few games) everything is damped; the offseason phantom baseline
    gets a modest fixed floor so picks still rank relative to each other.
    """
    if pd.isna(model_prob):
        return 0.0
    decisiveness = min(abs(model_prob - 0.5) * 2, 1.0)   # 0 (coin flip) → 1
    edge_score = min(abs(edge) / 0.10, 1.0) if pd.notna(edge) else 0.0
    core = 0.55 * decisiveness + 0.45 * edge_score
    if games_played <= 0:
        sample = 0.60           # phantom baseline — rank, don't trust
    else:
        sample = min(games_played / 6.0, 1.0)
    return round(100 * core * sample, 1)


def confidence_label(score: float) -> str:
    if score >= 70:
        return "Elite"
    if score >= 50:
        return "Strong"
    if score >= 32:
        return "Solid"
    if score >= 18:
        return "Lean"
    return "Thin"


def _bet(game_id, game, market, selection, model_prob, market_odds,
         other_odds=None, corr_group=None, games_played=0, rationale="") -> dict:
    """Assemble one bet with edge, fair odds, Kelly, and confidence."""
    if other_odds is not None and pd.notna(other_odds):
        implied = novig_prob(market_odds, other_odds)
    else:
        implied = implied_prob(market_odds)
    edge = (model_prob - implied) if pd.notna(model_prob) and pd.notna(implied) else np.nan
    kelly = betting.kelly_stake(model_prob, market_odds) if pd.notna(model_prob) else 0.0
    return {
        "game_id": game_id, "game": game, "market": market, "selection": selection,
        "model_prob": model_prob, "fair_odds": fair_odds(model_prob),
        "market_odds": market_odds, "novig_prob": implied, "edge": edge,
        "kelly": kelly, "confidence": confidence(model_prob, edge, games_played),
        "corr_group": corr_group or game_id, "rationale": rationale,
    }


# --- build the board from a game --------------------------------------------
def game_bets(row: pd.Series, off: pd.DataFrame, deff: pd.DataFrame, extras: dict,
              games_played: int = 0) -> list[dict]:
    """Every game-level bet (spread, total, moneyline) for one game."""
    home, away = row["home_team"], row["away_team"]
    gid = row.get("game_id", f"{away}@{home}")
    game = f"{away} @ {home}"
    sim = simulation.simulate(off, deff, home, away, extras, row)
    if not sim:
        return []
    bets = []

    # spread — probability of covering from the sim; -110 both sides (no-vig 0.5)
    if "home_cover" in sim:
        hc = sim["home_cover"]
        spread = sim["mkt_spread"]
        if hc >= 0.5:
            sel = f"{home} {spread:+.1f}" if spread < 0 else f"{home} -{spread:.1f}" if spread > 0 else f"{home} PK"
            p = hc
        else:
            asp = -spread
            sel = f"{away} {asp:+.1f}" if asp < 0 else f"{away} -{asp:.1f}" if asp > 0 else f"{away} PK"
            p = 1 - hc
        bets.append(_bet(gid, game, "Spread", sel, p, _STD_ODDS, _STD_ODDS, gid,
                         games_played, "Cover probability from the game simulation."))

    # total — over/under from the sim
    if "over" in sim:
        ov = sim["over"]
        line = sim["mkt_total"]
        if ov >= 0.5:
            bets.append(_bet(gid, game, "Total", f"Over {line:.1f}", ov, _STD_ODDS, _STD_ODDS,
                             gid, games_played, "Total-points distribution from the sim."))
        else:
            bets.append(_bet(gid, game, "Total", f"Under {line:.1f}", 1 - ov, _STD_ODDS, _STD_ODDS,
                             gid, games_played, "Total-points distribution from the sim."))

    # moneyline — model win prob vs the actual market prices (de-vigged)
    ph = sim["home_win"]
    mlh, mla = row.get("home_moneyline"), row.get("away_moneyline")
    if pd.notna(mlh) and pd.notna(mla):
        if ph >= 0.5:
            bets.append(_bet(gid, game, "Moneyline", f"{home} ML", ph, mlh, mla, gid,
                             games_played, "Straight-up win probability from the sim."))
        else:
            bets.append(_bet(gid, game, "Moneyline", f"{away} ML", 1 - ph, mla, mlh, gid,
                             games_played, "Straight-up win probability from the sim."))
    return bets


def week_board(games: pd.DataFrame, off: pd.DataFrame, deff: pd.DataFrame,
               extras: dict, games_played: int = 0, prop_bets: list | None = None) -> pd.DataFrame:
    """The full board of priced bets for a slate (games + any props passed in)."""
    rows = []
    for _, r in games.iterrows():
        rows.extend(game_bets(r, off, deff, extras, games_played))
    if prop_bets:
        rows.extend(prop_bets)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("edge", ascending=False, na_position="last").reset_index(drop=True)


# --- parlays -----------------------------------------------------------------
def parlay(legs: list[dict], corr_penalty: float = 0.85) -> dict:
    """Combine legs into a parlay with correlation-aware model probability.

    Naive parlay prob is the product of legs — but same-game legs are correlated,
    so multiplying overcounts independence. We damp the joint probability toward
    the product for each extra leg sharing a game (a conservative SGP proxy). EV
    is measured against the combined decimal odds.
    """
    if not legs:
        return {}
    dec = 1.0
    prob = 1.0
    for leg in legs:
        dec *= american_to_decimal(leg["market_odds"])
        prob *= leg["model_prob"]
    # correlation damp: count legs beyond the first that share a game
    groups = {}
    for leg in legs:
        groups[leg["corr_group"]] = groups.get(leg["corr_group"], 0) + 1
    dupes = sum(c - 1 for c in groups.values() if c > 1)
    prob *= corr_penalty ** dupes
    payout = dec - 1
    ev = prob * payout - (1 - prob)          # per 1 unit staked
    return {
        "legs": legs, "n": len(legs), "decimal": dec,
        "american": decimal_to_american(dec), "model_prob": prob,
        "fair_odds": fair_odds(prob), "payout": payout, "ev": ev,
        "kelly": betting.kelly_stake(prob, decimal_to_american(dec)),
        "same_game_legs": dupes,
    }
