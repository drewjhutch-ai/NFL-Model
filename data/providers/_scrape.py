"""Shared helpers for the HTML-scraping providers.

Kept deliberately defensive: parsing finds the right columns by *keyword* rather
than fixed positions, so a site tweaking its layout is less likely to break us.

NOTE: these helpers couldn't be exercised end-to-end from the build sandbox
(outbound access to the stats sites is blocked there). Run
``python scripts/test_providers.py`` locally to confirm the live pages parse,
and adjust the keyword hints below if a site's column labels differ.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def fetch_tables(url: str, timeout: int = 20) -> list[pd.DataFrame]:
    """GET a page and return every HTML <table> on it as a DataFrame.

    Raises ``requests.RequestException`` on network failure and ``ValueError``
    if the page has no parseable tables (e.g. it renders tables via JavaScript,
    in which case a headless-browser fallback would be needed).
    """
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def find_col(df: pd.DataFrame, *keywords: str) -> str | None:
    """Return the first column whose lowercased name contains all keywords."""
    for col in df.columns:
        name = str(col).lower()
        if all(k in name for k in keywords):
            return col
    return None


def to_rate(series: pd.Series) -> pd.Series:
    """Coerce a percentage-ish column to a 0-1 fraction.

    Handles '73.2%', '73.2', and 0.732 forms.
    """
    s = (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    vals = pd.to_numeric(s, errors="coerce")
    # If it looks like whole-number percentages, scale down.
    if vals.dropna().gt(1.5).any():
        vals = vals / 100.0
    return vals
