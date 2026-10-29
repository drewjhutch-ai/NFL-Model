"""Win-probability calibration — make the stated probability match reality.

A prediction tool is "accurate" in the formal sense when its probabilities are
calibrated: of the games it calls 60%, ~60% should hit. The walk-forward showed we
drift — a touch overconfident in the middle, underconfident on heavy favorites. This
fits a one-parameter-plus-intercept logistic recalibration from graded history,

    p_calibrated = sigmoid(a + b * logit(p_raw))

(identity at a=0, b=1), and applies it to the win probability the app reports and
bets moneylines off of. The learning loop refits (a, b) weekly from results and
stores them; config overlays them. Fit on the RAW probability so applying the
correction never feeds back into the next fit.
"""
from __future__ import annotations

import math


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def apply(p: float, a: float = 0.0, b: float = 1.0) -> float:
    """Recalibrate a probability. Identity when a=0, b=1."""
    try:
        return _sigmoid(a + b * _logit(p))
    except (ValueError, OverflowError):
        return p


def fit(preds, outcomes, iters: int = 300, lr: float = 0.3) -> dict:
    """Fit (a, b) for outcome ~ sigmoid(a + b*logit(pred)) by gradient descent.

    Returns {"a", "b"} clamped to a sane range, or identity on too little data or a
    degenerate fit (so a bad week can never invert or blow up the probabilities).
    """
    xs, ys = [], []
    for p, y in zip(preds, outcomes):
        try:
            if p is None or y is None or (isinstance(p, float) and math.isnan(p)):
                continue
            xs.append(_logit(float(p)))
            ys.append(float(y))
        except (TypeError, ValueError):
            continue
    n = len(xs)
    if n < 40:
        return {"a": 0.0, "b": 1.0}
    a, b = 0.0, 1.0
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            pr = _sigmoid(a + b * x)
            err = pr - y
            ga += err
            gb += err * x
        a -= lr * ga / n
        b -= lr * gb / n
    if not (0.3 <= b <= 2.5) or abs(a) > 1.5 or math.isnan(a) or math.isnan(b):
        return {"a": 0.0, "b": 1.0}           # degenerate → identity, stay safe
    return {"a": round(a, 4), "b": round(b, 4)}
