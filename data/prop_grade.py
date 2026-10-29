"""Grade player-prop projections and learn the prop market-blend (PROP_MODEL_TRUST).

Sides get tuned because we store the closing spread and the result. Props need the
same: our model's probability at pick time, the book's de-vigged probability, and
what actually happened. The free odds feed keeps no history, so we capture our own:

    history/prop_projections_<season>.csv
        season, week, player, stat, side, line, model_p, market_p, proj

``capture`` writes that each week (from the prop board, lines-anchored). ``grade``
joins it to actual weekly player stats and, over a grid of blend weights, finds the
PROP_MODEL_TRUST that would have predicted outcomes best (lowest log-loss) — exactly
how MODEL_TRUST is tuned for sides. Holds until enough graded props accrue.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from data import prop_market

_ROOT = Path(__file__).resolve().parents[1]
_HIST = _ROOT / "history"

# our prop stat -> the actual weekly-stats column to grade against
_STAT_COL = {
    "Pass yds": "passing_yards", "Rush yds": "rushing_yards",
    "Rec yds": "receiving_yards", "Rec": "receptions", "Pass TD": "passing_tds",
}
MIN_GRADED = 60                      # props needed before the blend can be tuned
_TRUST_GRID = [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0]


def _path(season: int) -> Path:
    return _HIST / f"prop_projections_{season}.csv"


def capture(leans: pd.DataFrame, season: int, week: int) -> Path | None:
    """Append this week's line-anchored prop projections (dedup by player+stat+week)."""
    if leans is None or getattr(leans, "empty", True):
        return None
    df = leans[leans.get("_has_line", False) == True].copy()  # noqa: E712
    if df.empty:
        return None
    rows = []
    for _, r in df.iterrows():
        mp, kp = r.get("_model_side_p"), r.get("_market_side_p")
        if mp is None or kp is None or pd.isna(mp) or pd.isna(kp):
            continue
        rows.append({"season": season, "week": int(week), "player": r.get("Player"),
                     "stat": r.get("Stat"), "side": r.get("Side"), "line": r.get("Line"),
                     "model_p": round(float(mp), 4), "market_p": round(float(kp), 4),
                     "proj": r.get("Projection")})
    if not rows:
        return None
    new = pd.DataFrame(rows)
    path = _path(season)
    if path.exists():
        try:
            old = pd.read_csv(path)
            old = old[~((old["week"] == int(week)))]        # replace this week's rows
            new = pd.concat([old, new], ignore_index=True)
        except Exception:  # noqa: BLE001
            pass
    _HIST.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False)
    return path


def load_projections(season: int) -> pd.DataFrame:
    p = _path(season)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def _actual_index(weekly: pd.DataFrame, season: int) -> dict:
    """{(norm_name, week, stat_col): actual_value} from weekly player stats."""
    if weekly is None or getattr(weekly, "empty", True):
        return {}
    w = weekly[weekly["season"] == season] if "season" in weekly.columns else weekly
    name_col = "player_display_name" if "player_display_name" in w.columns else None
    if name_col is None or "week" not in w.columns:
        return {}
    idx = {}
    for _, r in w.iterrows():
        nm = prop_market.norm_name(r[name_col])
        wk = r["week"]
        for col in set(_STAT_COL.values()):
            if col in w.columns and pd.notna(r.get(col)):
                idx[(nm, int(wk), col)] = float(r[col])
    return idx


def grade(season: int, weekly: pd.DataFrame) -> dict:
    """Join stored prop projections to actuals and tune PROP_MODEL_TRUST by log-loss.

    Returns {status: accruing|ok, n, recommended, losses:{t:loss}}. 'accruing' until
    MIN_GRADED props have a result.
    """
    proj = load_projections(season)
    if proj.empty:
        return {"status": "accruing", "n": 0, "need": MIN_GRADED}
    actual = _actual_index(weekly, season)
    if not actual:
        return {"status": "accruing", "n": 0, "need": MIN_GRADED}

    graded = []     # (model_p, market_p, win) for the chosen side
    for _, r in proj.iterrows():
        col = _STAT_COL.get(r["stat"])
        if not col:
            continue
        key = (prop_market.norm_name(r["player"]), int(r["week"]), col)
        if key not in actual:
            continue
        act, line = actual[key], float(r["line"])
        if act == line:
            continue                                   # push
        over_hit = act > line
        win = 1 if ((r["side"] == "Over") == over_hit) else 0
        mp, kp = float(r["model_p"]), float(r["market_p"])
        if pd.isna(mp) or pd.isna(kp):
            continue
        graded.append((mp, kp, win))

    n = len(graded)
    if n < MIN_GRADED:
        return {"status": "accruing", "n": n, "need": MIN_GRADED}

    def logloss(t: float) -> float:
        s = 0.0
        for mp, kp, win in graded:
            bp = min(max(t * mp + (1 - t) * kp, 1e-6), 1 - 1e-6)
            s += -(win * math.log(bp) + (1 - win) * math.log(1 - bp))
        return s / n

    losses = {t: round(logloss(t), 5) for t in _TRUST_GRID}
    best_t = min(losses, key=losses.get)
    # hit rate of the model side (diagnostic)
    hit = sum(w for _, _, w in graded) / n
    return {"status": "ok", "n": n, "recommended": best_t, "losses": losses,
            "model_side_hit": round(hit, 3)}
