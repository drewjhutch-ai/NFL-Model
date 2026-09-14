"""Small, dependency-free probability toolkit.

The betting math needs a few distribution functions that scipy would normally
provide — but the app doesn't ship scipy, so we implement the handful we use in
pure Python (they're all scalar, called per bet):

  * ``norm_cdf`` / ``norm_ppf`` — standard normal CDF and its inverse (quantile).
  * ``gamma_sf``               — Gamma survival, for yardage props (right-skewed,
                                  non-negative — better than a normal for yards).
  * ``nbinom_sf``              — Negative-binomial survival, for count props
                                  (receptions/carries/targets are over-dispersed
                                  integer counts, not continuous).
  * ``poisson_sf``             — Poisson survival, for touchdown props.

Each ``*_sf(k, ...)`` returns P(X > k). Half-point lines (2.5) have no push, so
P(X > 2.5) = P(X >= 3) = ``nbinom_sf(2, ...)``.
"""
from __future__ import annotations

import math

_SQRT2 = math.sqrt(2.0)


# --- normal ------------------------------------------------------------------
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation, ~1e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# --- regularized lower incomplete gamma P(a, x) ------------------------------
def _gammp(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a,x) (Numerical Recipes gser/gcf)."""
    if x <= 0.0 or a <= 0.0:
        return 0.0
    if x < a + 1.0:                       # series expansion
        ap = a
        total = 1.0 / a
        term = total
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # continued fraction for the upper part, then complement
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


def gamma_sf(x: float, shape: float, scale: float) -> float:
    """P(X > x) for X ~ Gamma(shape, scale). mean = shape*scale, var = shape*scale^2."""
    if shape <= 0 or scale <= 0:
        return float("nan")
    if x <= 0:
        return 1.0
    return 1.0 - _gammp(shape, x / scale)


def gamma_params(mean: float, cv: float) -> tuple[float, float]:
    """(shape, scale) for a Gamma with the given mean and coefficient of variation."""
    cv = max(cv, 1e-6)
    shape = 1.0 / (cv * cv)
    scale = mean * cv * cv
    return shape, scale


_UNIT_MEDIAN: dict[float, float] = {}


def _gamma_unit_median(shape: float) -> float:
    """Median of Gamma(shape, 1), cached (bisection on the CDF)."""
    key = round(shape, 4)
    if key in _UNIT_MEDIAN:
        return _UNIT_MEDIAN[key]
    lo, hi = 1e-9, shape * 3.0 + 12.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if _gammp(shape, mid) < 0.5:
            lo = mid
        else:
            hi = mid
    med = 0.5 * (lo + hi)
    _UNIT_MEDIAN[key] = med
    return med


def gamma_sf_median(x: float, median: float, cv: float) -> float:
    """P(X > x) for a right-skewed Gamma whose *median* equals ``median``.

    Centering on the median (not the mean) keeps the 50/50 point exactly at the
    projection, so a projection above the line always reads as an over and vice
    versa — no skew-induced sign flips — while the tails stay realistically
    right-skewed and non-negative.
    """
    if median <= 0 or x <= 0:
        return 1.0 if x <= 0 else float("nan")
    cv = max(cv, 1e-6)
    shape = 1.0 / (cv * cv)
    scale = median / _gamma_unit_median(shape)
    return gamma_sf(x, shape, scale)


# --- negative binomial (over-dispersed counts) -------------------------------
def _nbinom_pmf(k: int, r: float, p: float) -> float:
    # P(X=k) = C(k+r-1, k) p^r (1-p)^k, via lgamma for non-integer r.
    return math.exp(
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(p) + k * math.log1p(-p))


def nbinom_sf_from_rp(k: int, r: float, p: float) -> float:
    if k < 0:
        return 1.0
    cdf = sum(_nbinom_pmf(i, r, p) for i in range(0, int(k) + 1))
    return max(0.0, 1.0 - cdf)


def nbinom_sf(k: int, mean: float, var: float) -> float:
    """P(X > k) for a count with the given mean and variance (var must exceed mean).

    Parameterized so E[X]=mean, Var[X]=var. Falls back to Poisson if var<=mean
    (a negative binomial can only add dispersion, never remove it).
    """
    if mean <= 0:
        return 0.0
    if var <= mean:                       # not over-dispersed -> Poisson
        return poisson_sf(k, mean)
    p = mean / var                        # in (0,1)
    r = mean * p / (1.0 - p)
    return nbinom_sf_from_rp(k, r, p)


# --- Poisson -----------------------------------------------------------------
def poisson_sf(k: int, mean: float) -> float:
    """P(X > k) for X ~ Poisson(mean)."""
    if mean <= 0:
        return 0.0
    if k < 0:
        return 1.0
    cdf = 0.0
    term = math.exp(-mean)                # i=0
    cdf += term
    for i in range(1, int(k) + 1):
        term *= mean / i
        cdf += term
    return max(0.0, 1.0 - cdf)
