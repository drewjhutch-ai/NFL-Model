"""The self-tuning loop — the model re-fits itself from results each week.

After games settle, this grades how our stored projections did, then searches for
the settings that would have predicted the season best and nudges toward them
(gently, so one noisy week can't whipsaw the model). What it learns is written to
``model_tuning.json``, which ``config.py`` overlays on the safe defaults, so the
deployed model actually uses what it has learned.

Two dials are tuned, both cleanly measurable on the walk-forward backtest:
  * ``POINTS_WEIGHT`` — the EPA-vs-scoreboard blend in the margin projection.
  * ``EDGE_WEIGHTS`` — each matchup facet, toward how well it tracked real margins.

Learning is gradual (a learning rate) and gated on a minimum sample, so early in
a season it holds the defaults until there's real signal.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pandas as pd

import config
from data import backtest

_ROOT = Path(__file__).resolve().parents[1]
_TUNING_FILE = _ROOT / "model_tuning.json"
_LOG_FILE = _ROOT / "tuning_log.csv"

# How far to move toward the recommendation each week (0 = never, 1 = jump).
LEARNING_RATE = 0.25
# Minimum graded games before we trust the fit enough to move off defaults.
MIN_GAMES = 24
_POINTS_GRID = [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def _score(pbp, schedule, season) -> tuple[pd.DataFrame, dict]:
    res = backtest.walk_forward(pbp, schedule, season, start_week=4)
    return res, backtest.summary(res)


def best_points_weight(pbp, schedule, season) -> tuple[float, dict]:
    """Grid-search POINTS_WEIGHT on the backtest; best ATS%, tie-break lower MAE."""
    original = config.POINTS_WEIGHT
    best_w, best_key, best_metrics = original, None, {}
    try:
        for w in _POINTS_GRID:
            config.POINTS_WEIGHT = w
            _, s = _score(pbp, schedule, season)
            if not s:
                continue
            key = (round(s.get("ats_pct") or 0, 2), -round(s.get("model_mae") or 99, 3))
            if best_key is None or key > best_key:
                best_key, best_w, best_metrics = key, w, s
    finally:
        config.POINTS_WEIGHT = original
    return best_w, best_metrics


def recommend_edge_weights(pbp, schedule, season) -> dict:
    """Suggested facet weights from how well each tracked real margins."""
    fp = backtest.facet_predictiveness(pbp, schedule, season)
    if fp is None or fp.empty or "suggested_weight" not in fp.columns:
        return {}
    return {k: float(v) for k, v in fp["suggested_weight"].items()
            if k in config.EDGE_WEIGHTS and pd.notna(v)}


def _blend(current: float, target: float, lr: float = LEARNING_RATE) -> float:
    return round(current + lr * (target - current), 4)


def tune(pbp, schedule, season) -> dict:
    """Run one learning step. Returns the result (or a 'held' status if too early)."""
    res, base = _score(pbp, schedule, season)
    n = len(res)
    if n < MIN_GAMES:
        return {"status": "held", "reason": f"only {n} graded games (< {MIN_GAMES})", "games": n}

    rec_w, metrics = best_points_weight(pbp, schedule, season)
    new_points = _blend(config.POINTS_WEIGHT, rec_w)

    rec_weights = recommend_edge_weights(pbp, schedule, season)
    new_weights = dict(config.EDGE_WEIGHTS)
    for k, target in rec_weights.items():
        new_weights[k] = _blend(config.EDGE_WEIGHTS[k], target)

    payload = {
        "points_weight": new_points,
        "edge_weights": {k: round(v, 3) for k, v in new_weights.items()},
        "as_of": _dt.date.today().isoformat(),
        "season": season, "graded_games": n,
        "metrics": {k: (round(v, 3) if isinstance(v, (int, float)) else None)
                    for k, v in metrics.items() if k in ("model_mae", "market_mae", "ats_pct", "su_pct")},
        "recommended_points_weight": rec_w,
    }
    return {"status": "tuned", "payload": payload, "prev_points": config.POINTS_WEIGHT}


def write(payload: dict) -> Path:
    _TUNING_FILE.write_text(json.dumps(payload, indent=2))
    return _TUNING_FILE


def load() -> dict:
    if not _TUNING_FILE.exists():
        return {}
    try:
        return json.loads(_TUNING_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def append_log(payload: dict) -> None:
    m = payload.get("metrics", {})
    row = {"as_of": payload.get("as_of"), "season": payload.get("season"),
           "graded_games": payload.get("graded_games"),
           "points_weight": payload.get("points_weight"),
           "model_mae": m.get("model_mae"), "market_mae": m.get("market_mae"),
           "ats_pct": m.get("ats_pct"), "su_pct": m.get("su_pct")}
    df = pd.DataFrame([row])
    if _LOG_FILE.exists():
        df = pd.concat([pd.read_csv(_LOG_FILE), df], ignore_index=True)
    df.to_csv(_LOG_FILE, index=False)


def load_log() -> pd.DataFrame:
    if not _LOG_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(_LOG_FILE)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
