"""PFF coverage provider via manual CSV export.

PFF ELITE/+ has the best coverage-scheme charting but no individual API, so the
workflow is: export the team coverage table from PFF's web tool to CSV, drop it
at ``scheme_data/pff_coverage_<season>.csv``, and this provider ingests it.

It's forgiving about column names -- it looks for a team column and any columns
mentioning "zone"/"man", so most PFF exports work without renaming. Rates may be
percentages (73.2) or fractions (0.732); both are handled.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_DATA_DIR = Path(__file__).resolve().parents[2] / "scheme_data"


class PFFCoverageProvider(SchemeDataProvider):
    key = "pff"
    name = "PFF (CSV export)"
    trust = 1.0

    def _path(self, season: int) -> Path:
        return _DATA_DIR / f"pff_coverage_{season}.csv"

    def is_available(self) -> bool:
        return _DATA_DIR.exists() and any(_DATA_DIR.glob("pff_coverage_*.csv"))

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        path = self._path(season)
        if not path.exists():
            # Fall back to the newest available PFF export so an off-by-one
            # season doesn't hide data you've already dropped in.
            candidates = sorted(_DATA_DIR.glob("pff_coverage_*.csv")) if _DATA_DIR.exists() else []
            if not candidates:
                raise SchemeUnavailable(
                    f"No PFF export at {path}. Export the team coverage table from "
                    "PFF and save it there (columns like team, zone%, man%)."
                )
            path = candidates[-1]

        raw = pd.read_csv(path)
        team_col = _scrape.find_col(raw, "team") or raw.columns[0]
        zone_col = _scrape.find_col(raw, "zone")
        man_col = _scrape.find_col(raw, "man")
        if zone_col is None and man_col is None:
            raise SchemeUnavailable(
                f"{self.name}: {path.name} has no zone/man column. "
                f"Columns found: {list(raw.columns)}"
            )
        data = {"team": raw[team_col].map(normalize_team)}
        if zone_col is not None:
            data["zone_rate"] = _scrape.to_rate(raw[zone_col])
        if man_col is not None:
            data["man_rate"] = _scrape.to_rate(raw[man_col])
        snaps_col = _scrape.find_col(raw, "snap") or _scrape.find_col(raw, "cover", "snap")
        if snaps_col is not None:
            data["snaps"] = pd.to_numeric(raw[snaps_col], errors="coerce")
        df = pd.DataFrame(data).dropna(subset=["team"]).set_index("team")
        return self.validate(df)
