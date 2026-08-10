"""Placeholder scheme provider: reads coverage data from a local CSV drop.

This exists so the app is fully wired for coverage data *before* you commit to a
paid feed. Two ways it becomes useful:

1. **Right now, manually.** Many paid tools (e.g. PFF ELITE) let you export a
   coverage-scheme table as CSV even without an API. Drop that file at
   ``scheme_data/coverage_<season>.csv`` with columns matching COVERAGE_SCHEMA
   (team, zone_rate, man_rate, snaps) and it lights up immediately.

2. **Later, as a template.** When you pick an API-based feed, copy this file to
   e.g. ``pff_api.py``, implement ``coverage_tendencies`` against the API, and
   point ``providers.get_provider`` at it. Nothing else changes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import COVERAGE_SCHEMA, SchemeDataProvider, SchemeUnavailable

_DATA_DIR = Path(__file__).resolve().parents[2] / "scheme_data"


class ManualCSVProvider(SchemeDataProvider):
    name = "Manual CSV (scheme_data/)"

    def _path(self, season: int) -> Path:
        return _DATA_DIR / f"coverage_{season}.csv"

    def is_available(self) -> bool:
        return _DATA_DIR.exists() and any(_DATA_DIR.glob("coverage_*.csv"))

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        path = self._path(season)
        if not path.exists():
            raise SchemeUnavailable(
                f"No coverage CSV found at {path}. Drop a paid-feed export there "
                f"with columns: {', '.join(COVERAGE_SCHEMA)}."
            )
        df = pd.read_csv(path)
        return self.validate(df)
