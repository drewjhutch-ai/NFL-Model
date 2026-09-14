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
    """De-vig a two-way market (Shin's method): this side's fair probability."""
    ps, po = implied_prob(odds_side), implied_prob(odds_other)
    if pd.isna(ps) or pd.isna(po) or (ps + po) == 0:
        return np.nan
    fair = betting.shin_devig([ps, po])
    return fair[0] if fair else ps / (ps + po)


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
         other_odds=None, corr_group=None, games_played=0, rationale="",
         team=None, ou=None, pos=None, stat=None, player=None) -> dict:
    """Assemble one bet with edge, fair odds, Kelly, and confidence.

    ``team``/``ou``/``pos``/``stat``/``player`` are optional structured tags that
    let the parlay engine model same-game correlation (who the bet is on, and
    whether it wants more or less scoring). They default to None and are ignored
    by every other consumer.
    """
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
        "team": team, "ou": ou, "pos": pos, "stat": stat, "player": player,
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

    # spread — cover probability from the sim, push-adjusted (a push returns the
    # stake, so the money-relevant win prob is cover / (1 - push)). Push mass is
    # material on whole-number lines now that margins land on key numbers.
    if "home_cover" in sim:
        hc = sim["home_cover"]
        push = sim.get("home_push", 0.0)
        spread = sim["mkt_spread"]
        away_cover = max(0.0, 1.0 - hc - push)
        decisive = hc + away_cover
        if hc >= away_cover:
            sel = f"{home} {spread:+.1f}" if spread < 0 else f"{home} -{spread:.1f}" if spread > 0 else f"{home} PK"
            p, side_team = (hc / decisive if decisive > 0 else hc), home
        else:
            asp = -spread
            sel = f"{away} {asp:+.1f}" if asp < 0 else f"{away} -{asp:.1f}" if asp > 0 else f"{away} PK"
            p, side_team = (away_cover / decisive if decisive > 0 else (1 - hc)), away
        note = "Cover probability from the game simulation."
        if push > 0.02:
            note += f" Push {push*100:.0f}% at this key number."
        bets.append(_bet(gid, game, "Spread", sel, p, _STD_ODDS, _STD_ODDS, gid,
                         games_played, note, team=side_team, ou=1))

    # total — over/under from the sim
    if "over" in sim:
        ov = sim["over"]
        line = sim["mkt_total"]
        if ov >= 0.5:
            bets.append(_bet(gid, game, "Total", f"Over {line:.1f}", ov, _STD_ODDS, _STD_ODDS,
                             gid, games_played, "Total-points distribution from the sim.", ou=1))
        else:
            bets.append(_bet(gid, game, "Total", f"Under {line:.1f}", 1 - ov, _STD_ODDS, _STD_ODDS,
                             gid, games_played, "Total-points distribution from the sim.", ou=-1))

    # moneyline — model win prob vs the actual market prices (de-vigged)
    ph = sim["home_win"]
    mlh, mla = row.get("home_moneyline"), row.get("away_moneyline")
    if pd.notna(mlh) and pd.notna(mla):
        if ph >= 0.5:
            bets.append(_bet(gid, game, "Moneyline", f"{home} ML", ph, mlh, mla, gid,
                             games_played, "Straight-up win probability from the sim.",
                             team=home, ou=1))
        else:
            bets.append(_bet(gid, game, "Moneyline", f"{away} ML", 1 - ph, mla, mlh, gid,
                             games_played, "Straight-up win probability from the sim.",
                             team=away, ou=1))
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


# --- parlays: same-game correlation via a Gaussian copula --------------------
def _kind(leg: dict) -> str:
    m = leg.get("market")
    if m in ("Spread", "Moneyline"):
        return "side"
    if m == "Total":
        return "total"
    return "prop"


def _is_qbpass(leg: dict) -> bool:
    return (leg.get("pos") == "QB") or str(leg.get("stat") or "").startswith("Pass")


def _is_reception(leg: dict) -> bool:
    return (leg.get("stat") in ("Rec", "Rec yds", "Targets")) or leg.get("pos") in ("WR", "TE")


def _is_rush(leg: dict) -> bool:
    return (leg.get("stat") in ("Rush yds", "Carries")) or leg.get("pos") == "RB"


def _sign(da, db) -> float:
    a, b = da or 0, db or 0
    if a * b > 0:
        return 1.0
    if a * b < 0:
        return -1.0
    return 1.0


def _pair_corr(a: dict, b: dict) -> float:
    """Correlation between two legs' latent outcomes (0 if in different games).

    Encodes the football logic books shade same-game parlays on: a QB's passing
    stacks with his receivers, everything offensive stacks with the Over, the two
    sides of one game are mirror images, opposing offenses share a shootout.
    """
    if a.get("corr_group") != b.get("corr_group"):
        return 0.0                                   # different games → independent
    ka, kb = _kind(a), _kind(b)
    ta, tb = a.get("team"), b.get("team")
    da, db = a.get("ou"), b.get("ou")
    s = _sign(da, db)
    # same player, two stats (pass yds + pass TD, rec + rec yds)
    if ka == kb == "prop" and a.get("player") and a.get("player") == b.get("player"):
        return 0.60 * s
    if ka == "total" and kb == "total":
        return 0.90 * s
    if {ka, kb} == {"total", "prop"}:
        return 0.30 * s                              # more scoring ↔ more production
    if {ka, kb} == {"total", "side"}:
        return 0.08 * s
    if ka == kb == "side":
        if ta and tb:
            return (0.85 if ta == tb else -0.85) * s
        return 0.50 * s
    if {ka, kb} == {"side", "prop"}:
        side, prop = (a, b) if ka == "side" else (b, a)
        if side.get("team") and prop.get("team"):
            base = 0.35 if side["team"] == prop["team"] else -0.25
            return base * _sign(side.get("ou"), prop.get("ou"))
        return 0.10 * s
    # prop vs prop
    if ta and tb and ta == tb:
        if _is_qbpass(a) != _is_qbpass(b) and (_is_reception(a) or _is_reception(b)):
            return 0.55 * s                          # QB passing ↔ same-team receiver
        if _is_reception(a) and _is_reception(b):
            return 0.15 * s                          # two receivers share pass volume
        if _is_rush(a) != _is_rush(b):
            return -0.05 * s                         # run vs pass game-script tension
        return 0.15 * s
    if ta and tb and ta != tb:
        return 0.20 * s                              # opposing offenses → shootout
    return 0.10 * s


def _corr_matrix(legs: list[dict]) -> list[list[float]]:
    n = len(legs)
    R = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            c = max(-0.95, min(0.95, _pair_corr(legs[i], legs[j])))
            R[i][j] = R[j][i] = c
    return R


def _joint_prob(legs: list[dict], R: list[list[float]]) -> float:
    """P(all legs hit) under a Gaussian copula with correlation matrix ``R``."""
    import numpy as np
    from data.distributions import norm_ppf
    n = len(legs)
    probs = [max(min(float(l["model_prob"]), 0.999), 0.001) for l in legs]
    thr = np.array([norm_ppf(1.0 - p) for p in probs])   # leg hits if Z_i > thr_i
    A = np.array(R, dtype=float)
    A = (A + A.T) / 2.0
    # nearest positive-definite: clip eigenvalues, renormalize to unit diagonal
    w, V = np.linalg.eigh(A)
    w = np.clip(w, 1e-6, None)
    A = (V * w) @ V.T
    d = np.sqrt(np.diag(A))
    A = A / np.outer(d, d)
    L = np.linalg.cholesky(A + 1e-9 * np.eye(n))
    rng = np.random.default_rng(7)
    Z = L @ rng.standard_normal((n, 60000))
    hit = np.ones(Z.shape[1], dtype=bool)
    for i in range(n):
        hit &= Z[i] > thr[i]
    return float(hit.mean())


def parlay(legs: list[dict]) -> dict:
    """Combine legs into a parlay priced with same-game correlation.

    Multiplying leg probabilities assumes independence, which is wrong for
    same-game legs — a QB's passing yards and his receiver's yards rise and fall
    together, so the true joint probability is *higher* than the product (and
    opposing legs lower). We model each leg's outcome as a latent normal, build a
    correlation matrix from the football relationships between legs, and estimate
    P(all hit) with a Gaussian copula. EV is measured against the combined odds.
    Falls back to the independence product if the copula can't be evaluated.
    """
    if not legs:
        return {}
    dec = 1.0
    indep = 1.0
    for leg in legs:
        dec *= american_to_decimal(leg["market_odds"])
        indep *= max(min(float(leg["model_prob"]), 0.999), 0.001)
    try:
        prob = _joint_prob(legs, _corr_matrix(legs))
    except Exception:  # noqa: BLE001 - never fail a card on the enhancement
        prob = indep
    groups: dict = {}
    for leg in legs:
        groups[leg["corr_group"]] = groups.get(leg["corr_group"], 0) + 1
    dupes = sum(c - 1 for c in groups.values() if c > 1)
    payout = dec - 1
    ev = prob * payout - (1 - prob)          # per 1 unit staked
    return {
        "legs": legs, "n": len(legs), "decimal": dec,
        "american": decimal_to_american(dec), "model_prob": prob,
        "indep_prob": indep, "correlation_lift": prob - indep,
        "fair_odds": fair_odds(prob), "payout": payout, "ev": ev,
        "kelly": betting.kelly_stake(prob, decimal_to_american(dec)),
        "same_game_legs": dupes,
    }
