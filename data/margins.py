"""Key-number-aware NFL victory-margin distribution.

A single normal treats a game landing on 3 the same as landing on 5 — but NFL
margins cluster hard on the key numbers (the scoring increments 3 and 7 stack up).
Measured on 7,291 games (nflverse), the final margin lands on **3** about 2.8x as
often as a normal predicts, on **7** ~1.9x, with smaller spikes at 6/10/14/17 and
troughs at 1/2/5/8/9. Pricing spreads, moneylines and covers off a smooth normal
therefore misprices exactly the numbers books live on.

This module models the margin as a discrete distribution over integer point
differentials: a normal centered on our projected margin, reshaped by the
empirical key-number weights, then renormalized. Everything the spread/ML math
needs — win probability, cover probability, and a sampler for the simulation —
reads from that one distribution.

Weights are ``empirical_frequency / normal_frequency`` per |margin| from the
historical study; 1.0 (no adjustment) beyond the range we measured.
"""
from __future__ import annotations

import math

import config

# empirical freq / normal freq at each absolute margin (nflverse, 7291 games).
_KEY_W = {
    0: 0.20, 1: 0.80, 2: 0.78, 3: 2.85, 4: 0.95, 5: 0.72, 6: 1.21, 7: 1.87,
    8: 0.82, 9: 0.42, 10: 1.28, 11: 0.60, 12: 0.45, 13: 0.78, 14: 1.42,
    15: 0.48, 16: 0.72, 17: 1.28, 18: 0.90, 19: 0.55, 20: 1.00,
}
_LO, _HI = -70, 70


def _weight(k: int) -> float:
    return _KEY_W.get(abs(int(k)), 1.0)


def margin_pmf(mu: float, sigma: float | None = None) -> tuple[list[int], list[float]]:
    """Discrete PMF over integer margins: normal(mu, sigma) reshaped by key numbers.

    Returns (margins, probabilities) with margins from -70..70 (home-relative,
    + = home wins by that many). Probabilities sum to 1.
    """
    sigma = sigma or config.MARGIN_STD
    two_var = 2.0 * sigma * sigma
    ks = list(range(_LO, _HI + 1))
    dens = [math.exp(-((k - mu) ** 2) / two_var) * _weight(k) for k in ks]
    s = sum(dens)
    if s <= 0:
        return ks, [0.0] * len(ks)
    return ks, [d / s for d in dens]


def win_prob(mu: float, sigma: float | None = None) -> float:
    """Home win probability from the projected margin (a tie splits 50/50)."""
    if mu is None or (isinstance(mu, float) and math.isnan(mu)):
        return float("nan")
    ks, p = margin_pmf(mu, sigma)
    win = sum(pi for k, pi in zip(ks, p) if k > 0)
    tie = sum(pi for k, pi in zip(ks, p) if k == 0)
    return win + 0.5 * tie


def cover_prob(mu: float, spread: float, sigma: float | None = None) -> tuple[float, float]:
    """(P(home covers), P(push)) for a home line ``spread`` (+ = home favored).

    Home covers when margin - spread > 0. A push (margin == spread) is only
    possible when the line is a whole number.
    """
    ks, p = margin_pmf(mu, sigma)
    home = sum(pi for k, pi in zip(ks, p) if (k - spread) > 1e-9)
    push = sum(pi for k, pi in zip(ks, p) if abs(k - spread) < 1e-9)
    return home, push


def sample_margins(mu: float, sigma: float, n: int, rng) -> "object":
    """Draw ``n`` integer margins from the key-number PMF (for the simulation)."""
    import numpy as np
    ks, p = margin_pmf(mu, sigma)
    return rng.choice(np.asarray(ks, dtype=float), size=n, p=np.asarray(p, dtype=float))
