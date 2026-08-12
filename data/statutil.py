"""Small statistical helpers shared across the data engines."""
from __future__ import annotations

import numpy as np
import pandas as pd


def shrink(rate, count, league_mean: float, k: float):
    """Empirical-Bayes shrink a rate toward the league mean by sample size.

    shrunk = (count * rate + k * league_mean) / (count + k)

    With a full-season sample the rate is trusted; with a tiny sample it's pulled
    to the mean — so early-season noise and regression-prone stats behave.
    Works on scalars or aligned pandas Series.
    """
    if isinstance(rate, pd.Series):
        c = count.fillna(0)
        out = (c * rate.fillna(league_mean) + k * league_mean) / (c + k)
        return out.where(rate.notna(), np.nan)
    if rate is None or pd.isna(rate):
        return np.nan
    c = 0 if (count is None or pd.isna(count)) else count
    return (c * rate + k * league_mean) / (c + k)
