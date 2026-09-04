"""Pro Football Reference advanced stats — a second charted opinion.

The Sharp feed is our primary pressure/coverage source; PFR advanced is an
independent charted layer that confirms (or disputes) it. Columns vary by
release, so everything here is defensive: it finds the team and metric columns
by keyword and returns empty when they're absent, so a schema change degrades
gracefully instead of breaking.
"""
from __future__ import annotations

import pandas as pd


def _col(df: pd.DataFrame, *keys: str):
    for c in df.columns:
        name = str(c).lower()
        if all(k in name for k in keys):
            return c
    return None


def _team_col(df: pd.DataFrame):
    for c in ("tm", "team", "recent_team", "team_abbr"):
        if c in df.columns:
            return c
    return None


def team_pass_rush(pfr_def: pd.DataFrame) -> pd.DataFrame:
    """team -> pressures, sacks, QB knockdowns, hurries (summed), with a rank."""
    if pfr_def is None or pfr_def.empty:
        return pd.DataFrame()
    tc = _team_col(pfr_def)
    if tc is None:
        return pd.DataFrame()
    prss = _col(pfr_def, "prss") or _col(pfr_def, "pressure")
    sk = _col(pfr_def, "sk") or _col(pfr_def, "sack")
    hu = _col(pfr_def, "hurry") or _col(pfr_def, "hrry")
    cols = {name: c for name, c in (("pressures", prss), ("sacks", sk), ("hurries", hu)) if c}
    if not cols:
        return pd.DataFrame()
    g = pfr_def.groupby(tc).agg({c: "sum" for c in cols.values()})
    g = g.rename(columns={v: k for k, v in cols.items()})
    if "pressures" in g.columns:
        g["pressure_rank"] = g["pressures"].rank(ascending=False, method="min").astype("Int64")
    return g.rename_axis("team")


def team_coverage(pfr_def: pd.DataFrame) -> pd.DataFrame:
    """team -> passer rating allowed & yards/target allowed (target-weighted)."""
    if pfr_def is None or pfr_def.empty:
        return pd.DataFrame()
    tc = _team_col(pfr_def)
    tgt = _col(pfr_def, "tgt") or _col(pfr_def, "target")
    rat = _col(pfr_def, "rat")  # passer rating allowed
    ypt = _col(pfr_def, "yards", "tgt") or _col(pfr_def, "yds", "tgt")
    if tc is None or tgt is None or (rat is None and ypt is None):
        return pd.DataFrame()
    rows = []
    for team, grp in pfr_def.groupby(tc):
        w = pd.to_numeric(grp[tgt], errors="coerce").fillna(0)
        wsum = w.sum() or 1

        def wavg(col):
            if col is None:
                return None
            return float((pd.to_numeric(grp[col], errors="coerce").fillna(0) * w).sum() / wsum)
        rows.append({"team": team, "rating_allowed": wavg(rat), "ypt_allowed": wavg(ypt)})
    out = pd.DataFrame(rows).set_index("team")
    if "rating_allowed" in out.columns and out["rating_allowed"].notna().any():
        out["cover_rank"] = out["rating_allowed"].rank(ascending=True, method="min").astype("Int64")
    return out
