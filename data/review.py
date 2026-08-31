"""The automated game-review layer — cross-references facets against results.

The self-tuner (``data/tuning.py``) re-fits weights from a correlation backtest.
This module adds the *interpretable* half the war plan promised: for every facet
edge the model flagged, did the flagged side actually win the game? That yields a
per-facet **hit rate** ("coverage-fit hit 71%") and a weekly **review log**, so
the learning loop is auditable — you can see which mismatches are paying off and
which are noise, not just a black-box weight change.

Runs hands-off inside the weekly Action (``scripts/review.py``), reading the same
committed coverage the app uses so the scheme-fit facet is graded too.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd

import config
from data import backtest, edges, off_coverage, positional, pressure, situational

_ROOT = Path(__file__).resolve().parents[1]
_REVIEW_LOG = _ROOT / "review_log.csv"

# A facet "flags" a side once its net (home-relative) edge clears this magnitude.
_FLAG_MIN = 6.0


def _committed_coverage(season: int) -> pd.DataFrame | None:
    try:
        from data.providers.base import SchemeUnavailable
        from data.providers.committed import CommittedCoverageProvider
        return CommittedCoverageProvider().coverage_tendencies(season)
    except Exception:  # noqa: BLE001
        return None


def _grade_extras(sp: pd.DataFrame, season: int, coverage: pd.DataFrame | None) -> dict:
    """The full facet-grading context, mirroring what the app feeds edges."""
    posmap = {}
    try:
        from data import loaders
        posmap = loaders.position_map((season,))
    except Exception:  # noqa: BLE001
        pass
    extras = {
        "dvp": positional.defense_vs_position(sp, posmap),
        "usage": positional.offense_usage(sp, posmap),
        "off_sit": situational.offense_situational(sp),
        "def_sit": situational.defense_situational(sp),
        "pressure": pressure.defense_pressure(sp),
        "protection": pressure.offense_protection(sp),
    }
    if coverage is not None and not coverage.empty:
        extras["coverage"] = coverage
        extras["off_vs_cov"] = off_coverage.offense_vs_coverage(sp, coverage)
    return extras


def facet_hit_rates(pbp_all: pd.DataFrame, schedule: pd.DataFrame, season: int,
                    coverage: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-facet hit rate: when a facet flagged a side, did that side win?

    Returns columns: n_flagged, hits, hit_rate (%), correlation with margin.
    """
    sp = backtest._season_pbp(pbp_all, season)  # noqa: SLF001 - internal reuse
    if sp.empty:
        return pd.DataFrame()
    off, deff, _pace = backtest._ratings(sp)    # noqa: SLF001
    extras = _grade_extras(sp, season, coverage)
    extras["pace"] = _pace
    games = schedule[(schedule["season"] == season) & schedule["result"].notna()]

    tallies: dict[str, dict] = {}
    for _, r in games.iterrows():
        home, away, margin = r["home_team"], r["away_team"], r["result"]
        he = {e["label"]: e["mag"] for e in edges.facet_edges(home, away, off, deff, extras)}
        ae = {e["label"]: e["mag"] for e in edges.facet_edges(away, home, off, deff, extras)}
        for label in set(he) | set(ae):
            net = he.get(label, 0.0) - ae.get(label, 0.0)   # + = favors home
            if abs(net) < _FLAG_MIN:
                continue
            t = tallies.setdefault(label, {"n": 0, "hits": 0, "nets": [], "margins": []})
            t["n"] += 1
            hit = (net > 0 and margin > 0) or (net < 0 and margin < 0)
            t["hits"] += int(hit)
            t["nets"].append(net)
            t["margins"].append(margin)
    rows = []
    for label, t in tallies.items():
        if t["n"] == 0:
            continue
        corr = (np.corrcoef(t["nets"], t["margins"])[0, 1]
                if len(t["nets"]) > 2 and np.std(t["nets"]) > 0 else np.nan)
        rows.append({
            "facet": label, "n_flagged": t["n"], "hits": t["hits"],
            "hit_rate": round(100 * t["hits"] / t["n"], 1),
            "correlation": round(float(corr), 3) if pd.notna(corr) else None,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("hit_rate", ascending=False).reset_index(drop=True)


def weekly_review(pbp_all: pd.DataFrame, schedule: pd.DataFrame, season: int) -> dict:
    """Grade the season to date: accuracy headline + per-facet hit rates."""
    coverage = _committed_coverage(season)
    res = backtest.walk_forward(pbp_all, schedule, season, start_week=4)
    acc = backtest.summary(res)
    facets = facet_hit_rates(pbp_all, schedule, season, coverage)
    headline = _headline(acc, facets)
    return {
        "as_of": _dt.date.today().isoformat(), "season": season,
        "graded_games": int(acc.get("games", 0)),
        "model_mae": acc.get("model_mae"), "market_mae": acc.get("market_mae"),
        "ats_pct": acc.get("ats_pct"), "su_pct": acc.get("su_pct"),
        "facets": facets.to_dict("records") if not facets.empty else [],
        "headline": headline,
    }


def _headline(acc: dict, facets: pd.DataFrame) -> str:
    if not acc.get("games"):
        return "No graded games yet."
    parts = [f"graded {acc['games']} games"]
    if acc.get("model_mae") is not None:
        parts.append(f"MAE {acc['model_mae']:.1f}")
    if acc.get("ats_pct") is not None:
        parts.append(f"ATS {acc['ats_pct']:.0f}%")
    if not facets.empty:
        top = facets.iloc[0]
        parts.append(f"best facet: {top['facet']} hit {top['hit_rate']:.0f}%")
    return " · ".join(parts)


def append_review_log(summary: dict) -> None:
    """Append a flat per-facet row set for this review to review_log.csv."""
    facets = summary.get("facets") or []
    base = {"as_of": summary.get("as_of"), "season": summary.get("season"),
            "graded_games": summary.get("graded_games"),
            "model_mae": summary.get("model_mae"), "ats_pct": summary.get("ats_pct")}
    if facets:
        rows = [{**base, "facet": f["facet"], "n_flagged": f["n_flagged"],
                 "hit_rate": f["hit_rate"], "correlation": f.get("correlation")}
                for f in facets]
    else:
        rows = [{**base, "facet": None, "n_flagged": 0, "hit_rate": None, "correlation": None}]
    df = pd.DataFrame(rows)
    if _REVIEW_LOG.exists():
        df = pd.concat([pd.read_csv(_REVIEW_LOG), df], ignore_index=True)
    df.to_csv(_REVIEW_LOG, index=False)


def load_review_log() -> pd.DataFrame:
    if not _REVIEW_LOG.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(_REVIEW_LOG)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
