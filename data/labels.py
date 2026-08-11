"""League-relative labels — so descriptions move with the NFL, not fixed cutoffs.

Instead of hardcoding "pass-heavy = 62%+", a team is labeled by where it sits in
*this* league, right now. If the whole NFL gets more pass-happy (or blitzes less,
or zones more), the labels recalibrate automatically because they're computed
from the current distribution every time the data refreshes.

Bands are expressed as cumulative percentile cutoffs; tune them in one place.
"""
from __future__ import annotations

import pandas as pd

# (upper_percentile, label) ascending. A value in the bottom 12% of neutral pass
# rate is "Very run-heavy"; the top 12% is "Very pass-heavy"; etc.
STYLE_BANDS = [(0.12, "Very run-heavy"), (0.35, "Run-leaning"),
               (0.65, "Balanced"), (0.88, "Pass-leaning"), (1.01, "Very pass-heavy")]

BLITZ_BANDS = [(0.20, "Low blitz / coverage-heavy"), (0.55, "Average"),
               (0.80, "Above-average blitz"), (1.01, "Heavy blitz")]

QB_BANDS = [(0.55, "Pocket passer"), (0.82, "Some mobility"),
            (1.01, "Mobile / dual-threat")]

# blitz_delta: higher = holds up better against the blitz
RESILIENCE_BANDS = [(0.15, "Struggles vs blitz"), (0.40, "Dips vs blitz"),
                    (0.70, "Handles blitz fine"), (1.01, "Thrives vs blitz")]


def band_series(series: pd.Series, bands: list[tuple[float, str]],
                higher_is_more: bool = True) -> pd.Series:
    """Label every value by its percentile within the (current-league) series."""
    if series is None or series.dropna().empty:
        return pd.Series("—", index=getattr(series, "index", None))
    pct = series.rank(pct=True, ascending=higher_is_more)

    def to_name(p):
        if pd.isna(p):
            return "—"
        for upper, name in bands:
            if p <= upper:
                return name
        return bands[-1][1]

    return pct.map(to_name)


def band_from_pct(pct: float, bands: list[tuple[float, str]]) -> str:
    """Label a single already-computed percentile (0-100 or 0-1)."""
    if pct is None or pd.isna(pct):
        return "—"
    p = pct / 100 if pct > 1 else pct
    for upper, name in bands:
        if p <= upper:
            return name
    return bands[-1][1]
