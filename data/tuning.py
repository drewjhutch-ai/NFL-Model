"""The self-tuning loop — the model re-fits itself from results each week.

After games settle, this grades how our stored projections did, then searches for
the settings that would have predicted the season best and nudges toward them
(gently, so one noisy week can't whipsaw the model). What it learns is written to
``model_tuning.json``, which ``config.py`` overlays on the safe defaults, so the
deployed model actually uses what it has learned.

Dials tuned on the walk-forward backtest (all cleanly measurable there):
  * ``POINTS_WEIGHT`` — the EPA-vs-scoreboard blend in the margin projection.
  * ``MARKET_WEIGHT`` — how much the market power rating (team strength backed out
    of the closing lines) pulls the margin ensemble.
  * ``EDGE_WEIGHTS`` — each matchup facet, toward how well it tracked real margins.

Prop-side dials (``PROP_MODEL_TRUST`` and the reconciliation flags) can't be graded
on the margin backtest — they need historical *book prop lines*, which the free odds
feed doesn't retain. ``scripts/snapshot_prop_lines.py`` now banks them each week; the
loop reports them as "accruing" until there's enough history to grade, then tunes
``PROP_MODEL_TRUST`` the same way (see ``prop_tuning_status``).

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
_MARKET_GRID = [0.0, 0.10, 0.18, 0.22, 0.28, 0.35, 0.45]
# Weeks of banked prop-line snapshots before PROP_MODEL_TRUST can be graded.
MIN_PROP_WEEKS = 4


def _score(pbp, schedule, season) -> tuple[pd.DataFrame, dict]:
    res = backtest.walk_forward(pbp, schedule, season, start_week=3)
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


def best_market_weight(pbp, schedule, season) -> tuple[float, dict]:
    """Grid-search MARKET_WEIGHT on the backtest; best ATS%, tie-break lower MAE.

    Only meaningful now that walk_forward feeds market power ratings in — the grid
    measures how far to lean the margin on the market's own team strength.
    """
    original = config.MARKET_WEIGHT
    best_w, best_key, best_metrics = original, None, {}
    try:
        for w in _MARKET_GRID:
            config.MARKET_WEIGHT = w
            _, s = _score(pbp, schedule, season)
            if not s:
                continue
            key = (round(s.get("ats_pct") or 0, 2), -round(s.get("model_mae") or 99, 3))
            if best_key is None or key > best_key:
                best_key, best_w, best_metrics = key, w, s
    finally:
        config.MARKET_WEIGHT = original
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


def prop_tuning_status() -> dict:
    """Whether PROP_MODEL_TRUST can be graded yet — gated on banked prop-line weeks.

    We can only grade the prop market-blend once we have historical book lines to
    de-vig; the free feed doesn't retain them, so snapshot_prop_lines banks them
    weekly. Until MIN_PROP_WEEKS have accrued this returns a 'held' status so the
    loop keeps the safe default and reports honestly why.
    """
    try:
        from data import prop_history
        weeks = prop_history.weeks_available(config.CURRENT_SEASON)
    except Exception:  # noqa: BLE001
        weeks = 0
    if weeks < MIN_PROP_WEEKS:
        return {"status": "accruing", "weeks": weeks, "need": MIN_PROP_WEEKS,
                "prop_model_trust": config.PROP_MODEL_TRUST}
    # Enough history exists; grading is added when the prop backtest lands. For now
    # hold at the current value but mark it ready so the status is transparent.
    return {"status": "ready", "weeks": weeks, "prop_model_trust": config.PROP_MODEL_TRUST}


def recommend_reconcile(schedule, weekly, season) -> dict:
    """Anchor constants (yards/point, pass share, receiver capture) blended toward
    what actually happened. Empty when there aren't enough team-games to fit."""
    cal = backtest.reconcile_calibration(schedule, weekly, season)
    if not cal or cal.get("status") != "ok":
        return {"status": (cal or {}).get("status", "none"), "n": (cal or {}).get("n", 0)}
    return {
        "status": "ok", "n": cal["n"],
        "yards_per_point": _blend(config.RECON_YARDS_PER_POINT, cal["yards_per_point"]),
        "pass_share": _blend(config.RECON_PASS_SHARE, cal["pass_share"]),
        "receiver_capture": _blend(config.RECON_RECEIVER_CAPTURE, cal["receiver_capture"]),
        "fit": {k: cal[k] for k in ("yards_per_point", "pass_share", "receiver_capture")},
    }


def tune(pbp, schedule, season, weekly=None) -> dict:
    """Run one learning step. Returns the result (or a 'held' status if too early)."""
    res, base = _score(pbp, schedule, season)
    n = len(res)
    if n < MIN_GAMES:
        return {"status": "held", "reason": f"only {n} graded games (< {MIN_GAMES})", "games": n}

    rec_w, metrics = best_points_weight(pbp, schedule, season)
    new_points = _blend(config.POINTS_WEIGHT, rec_w)

    rec_mkt, mkt_metrics = best_market_weight(pbp, schedule, season)
    new_market = _blend(config.MARKET_WEIGHT, rec_mkt)

    rec_weights = recommend_edge_weights(pbp, schedule, season)
    new_weights = dict(config.EDGE_WEIGHTS)
    for k, target in rec_weights.items():
        new_weights[k] = _blend(config.EDGE_WEIGHTS[k], target)

    recon = recommend_reconcile(schedule, weekly, season)

    payload = {
        "points_weight": new_points,
        "market_weight": new_market,
        "edge_weights": {k: round(v, 3) for k, v in new_weights.items()},
        "as_of": _dt.date.today().isoformat(),
        "season": season, "graded_games": n,
        "metrics": {k: (round(v, 3) if isinstance(v, (int, float)) else None)
                    for k, v in metrics.items() if k in ("model_mae", "market_mae", "ats_pct", "su_pct")},
        "recommended_points_weight": rec_w,
        "recommended_market_weight": rec_mkt,
        "prop_tuning": prop_tuning_status(),
    }
    if recon.get("status") == "ok":
        payload["reconcile"] = {
            "yards_per_point": recon["yards_per_point"],
            "pass_share": recon["pass_share"],
            "receiver_capture": recon["receiver_capture"],
            "n": recon["n"], "fit": recon["fit"],
        }
    else:
        payload["reconcile_status"] = recon
    return {"status": "tuned", "payload": payload,
            "prev_points": config.POINTS_WEIGHT, "prev_market": config.MARKET_WEIGHT}


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
           "market_weight": payload.get("market_weight"),
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
