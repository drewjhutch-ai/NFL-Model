"""Derived offense-vs-coverage performance (activates the scheme-fit edge).

We already scrape the *defense* side — how much zone vs man each defense plays
(``data/providers`` → the committed coverage CSV). The scheme-fit edge also needs
the *offense* side: how well each offense throws against zone vs against man.
Sharp Football doesn't publish that split cleanly, so we **derive** it from
play-by-play we already load, cross-referenced with the defensive coverage rates.

Method — exposure weighting (no noisy tertile splits):
    For every dropback an offense runs, weight its EPA by the *opponent
    defense's* zone rate (and, separately, its man rate). An offense that piles
    up EPA against zone-heavy defenses scores well "vs zone"; weighting every
    play by how much of that scheme it actually faced uses the whole sample.
    Empirical-Bayes shrinkage pulls small samples toward the league mean.

Output (indexed by team), matching what ``edges._coverage_edge`` consumes:
    vs_zone_epa, vs_man_epa  — shrunk EPA/dropback experienced vs each scheme
    vs_zone_rank, vs_man_rank — 1 = best offense vs that scheme
    scheme_affinity          — vs_zone_epa − vs_man_epa (+ = better vs zone)
    n_db                     — dropbacks in the sample (confidence)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

# Pseudo-weight (in fractional-exposure units) for empirical-Bayes shrinkage.
_SHRINK = 15.0


def offense_vs_coverage(pbp: pd.DataFrame, coverage: pd.DataFrame | None) -> pd.DataFrame:
    """Per-offense EPA vs zone / vs man, derived from pbp + defense coverage rates.

    ``coverage`` is the blended defensive frame (index=team, has ``zone_rate``
    and optionally ``man_rate``). Returns an empty frame if either input is
    missing so callers degrade gracefully.
    """
    if pbp is None or getattr(pbp, "empty", True):
        return pd.DataFrame()
    if coverage is None or getattr(coverage, "empty", True) or "zone_rate" not in coverage.columns:
        return pd.DataFrame()

    need = {"posteam", "defteam", "epa"}
    if not need.issubset(pbp.columns):
        return pd.DataFrame()

    # Dropbacks with a valid EPA. Prefer the explicit dropback flag; fall back to
    # the pass flag so this still works if qb_dropback is absent.
    df = pbp
    if "qb_dropback" in df.columns:
        df = df[df["qb_dropback"] == 1]
    elif "pass" in df.columns:
        df = df[df["pass"] == 1]
    df = df[["posteam", "defteam", "epa"]].dropna(subset=["posteam", "defteam", "epa"])
    if df.empty:
        return pd.DataFrame()

    zone = coverage["zone_rate"].astype(float)
    man = (coverage["man_rate"].astype(float) if "man_rate" in coverage.columns
           else (1.0 - zone))
    df = df.copy()
    df["zw"] = df["defteam"].map(zone)
    df["mw"] = df["defteam"].map(man)
    df = df.dropna(subset=["zw", "mw"])
    if df.empty:
        return pd.DataFrame()

    # League-mean EPA under each scheme's exposure weights (the shrink target).
    lm_zone = np.average(df["epa"], weights=df["zw"]) if df["zw"].sum() else 0.0
    lm_man = np.average(df["epa"], weights=df["mw"]) if df["mw"].sum() else 0.0

    rows = []
    for team, g in df.groupby("posteam"):
        zsum, msum = g["zw"].sum(), g["mw"].sum()
        z_epa = (float((g["epa"] * g["zw"]).sum()) + _SHRINK * lm_zone) / (zsum + _SHRINK)
        m_epa = (float((g["epa"] * g["mw"]).sum()) + _SHRINK * lm_man) / (msum + _SHRINK)
        rows.append({"team": team, "vs_zone_epa": z_epa, "vs_man_epa": m_epa,
                     "n_db": int(len(g))})
    out = pd.DataFrame(rows).set_index("team")
    if out.empty:
        return out

    # 1 = best offense vs that scheme (higher EPA is better). Kept for display.
    out["vs_zone_rank"] = out["vs_zone_epa"].rank(ascending=False, method="min").astype(int)
    out["vs_man_rank"] = out["vs_man_epa"].rank(ascending=False, method="min").astype(int)

    # The scheme signal is the *differential*, not overall quality (offenses good
    # vs zone tend to be good vs man too — that's already the QB/passing facet).
    # scheme_affinity strips the baseline; its z-score makes it a clean,
    # orthogonal input for the scheme-fit edge (+ = better vs zone than vs man).
    out["scheme_affinity"] = out["vs_zone_epa"] - out["vs_man_epa"]
    std = float(out["scheme_affinity"].std(ddof=0)) or 1.0
    out["affinity_z"] = (out["scheme_affinity"] - out["scheme_affinity"].mean()) / std
    out["affinity_rank"] = out["scheme_affinity"].rank(ascending=False, method="min").astype(int)
    return out
