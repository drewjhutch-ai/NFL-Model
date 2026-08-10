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

    #: Short, stable id used as a column suffix and trust-config key ("pff").
    key: str = "unnamed"
    #: Human-readable name shown in the UI ("PFF", "SumerSports"…).
    name: str = "Unnamed provider"
    #: Default trust weight when blending. Higher = counts more in the consensus.
    #: Overridable per-source in ``config.SCHEME_SOURCE_TRUST``.
    trust: float = 1.0

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap check: can this provider serve data right now?

        Should be fast and side-effect-free. Network-backed providers may
        optimistically return ``True`` and fail gracefully in
        ``coverage_tendencies``.
        """

    @abstractmethod
    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        """Per-defense zone/man coverage rates for ``season``.

        Must return a DataFrame indexed by canonical team abbreviation with at
        least the columns in ``COVERAGE_SCHEMA``. Raise ``SchemeUnavailable`` if
        there's nothing to serve.
        """

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Coerce/verify a provider frame against COVERAGE_SCHEMA."""
        missing = [c for c in COVERAGE_SCHEMA
                   if c not in df.columns and c != "team" and df.index.name != "team"]
        if missing:
            raise SchemeUnavailable(
                f"{self.name} returned data missing columns: {missing}"
            )
        if df.index.name != "team" and "team" in df.columns:
            df = df.set_index("team")
        # If a source reports only one of man/zone, infer the other.
        if "zone_rate" in df.columns and "man_rate" not in df.columns:
            df["man_rate"] = 1.0 - df["zone_rate"]
        if "man_rate" in df.columns and "zone_rate" not in df.columns:
            df["zone_rate"] = 1.0 - df["man_rate"]
        if "snaps" not in df.columns:
            df["snaps"] = pd.NA
        return df
