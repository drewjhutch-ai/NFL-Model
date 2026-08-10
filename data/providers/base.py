"""The contract every scheme-data provider must satisfy.

A provider returns per-defense coverage tendencies keyed by team abbreviation.
The dashboard never cares *where* the data came from -- only that it matches
this shape. That's what lets a paid feed replace the placeholder cleanly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class SchemeUnavailable(Exception):
    """Raised when a provider has no data to serve (not configured / no feed)."""


# The columns the app expects back from ``coverage_tendencies``. Rates are
# fractions in [0, 1]. Extra columns are allowed and ignored.
COVERAGE_SCHEMA = [
    "team",         # team abbreviation, e.g. "KC"
    "zone_rate",    # share of coverage snaps in zone
    "man_rate",     # share of coverage snaps in man
    "snaps",        # coverage snaps behind the numbers (sample size)
]


class SchemeDataProvider(ABC):
    """Interface for a source of coverage / advanced scheme data."""

    #: Human-readable name shown in the UI ("PFF", "SIS", "Manual CSV"…).
    name: str = "Unnamed provider"

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap check: can this provider serve data right now?"""

    @abstractmethod
    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        """Per-defense zone/man coverage rates for ``season``.

        Must return a DataFrame indexed by ``team`` with at least the columns in
        ``COVERAGE_SCHEMA``. Raise ``SchemeUnavailable`` if there's nothing to
        serve.
        """

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Coerce/verify a provider frame against COVERAGE_SCHEMA."""
        missing = [c for c in COVERAGE_SCHEMA if c not in df.columns and c != "team"]
        if missing:
            raise SchemeUnavailable(
                f"{self.name} returned data missing columns: {missing}"
            )
        if df.index.name != "team" and "team" in df.columns:
            df = df.set_index("team")
        return df
