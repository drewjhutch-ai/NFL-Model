"""Scheme-data providers (zone/man coverage, advanced blitz, etc.).

The free nflverse data can't tell you how much a defense plays zone vs. man --
that's charting data. We pull it from several sources and blend them:

  * PFF (manual CSV export)  -- gold-standard charting, highest trust
  * SumerSports (free scrape)
  * StatRankings (free scrape)

The dashboard talks to a single blended provider, so sources can be added,
removed, or swapped without touching the rest of the app.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .base import COVERAGE_SCHEMA, SchemeDataProvider, SchemeUnavailable
from .composite import CompositeSchemeProvider
from .pff_csv import PFFCoverageProvider
from .statrankings import StatRankingsProvider
from .sumersports import SumerSportsProvider

__all__ = [
    "SchemeDataProvider",
    "SchemeUnavailable",
    "COVERAGE_SCHEMA",
    "get_provider",
    "load_coverage",
]


def get_provider() -> SchemeDataProvider:
    """The active (blended) scheme provider.

    Order matters only for display; trust weights (config.SCHEME_SOURCE_TRUST)
    decide influence in the blend. Add/remove sources here.
    """
    return CompositeSchemeProvider(
        providers=[
            PFFCoverageProvider(),
            SumerSportsProvider(),
            StatRankingsProvider(),
        ]
    )


@st.cache_data(ttl=60 * 60, show_spinner="Blending coverage sources…")
def load_coverage(season: int) -> pd.DataFrame | None:
    """Cached blended coverage frame, or ``None`` if no source has data."""
    provider = get_provider()
    if not provider.is_available():
        return None
    try:
        return provider.coverage_tendencies(season)
    except SchemeUnavailable:
        return None
