"""SumerSports.com coverage-scheme provider (free source).

Pulls team man/zone coverage tendencies from the public defensive team stats:
    https://sumersports.com/teams/defensive/

⚠️  Structure inferred, not verified from the build sandbox. SumerSports may
    render its tables client-side (React); if ``fetch_tables`` finds nothing,
    the page needs the headless-browser fallback noted in scripts/test_providers.py.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_URL = "https://sumersports.com/teams/defensive/"


class SumerSportsProvider(SchemeDataProvider):
    key = "sumersports"
    name = "SumerSports"
    trust = 0.85

    def is_available(self) -> bool:
        return True

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        try:
            tables = _scrape.fetch_tables(_URL)
        except Exception as exc:  # noqa: BLE001
            raise SchemeUnavailable(f"{self.name} fetch failed: {exc}") from exc

        for tbl in tables:
            team_col = _scrape.find_col(tbl, "team") or _scrape.find_col(tbl, "defense")
            zone_col = _scrape.find_col(tbl, "zone")
            man_col = _scrape.find_col(tbl, "man")
            if team_col is not None and (zone_col is not None or man_col is not None):
                data = {"team": tbl[team_col].map(normalize_team)}
                if zone_col is not None:
                    data["zone_rate"] = _scrape.to_rate(tbl[zone_col])
                if man_col is not None:
                    data["man_rate"] = _scrape.to_rate(tbl[man_col])
                df = pd.DataFrame(data).dropna(subset=["team"]).set_index("team")
                return self.validate(df)

        raise SchemeUnavailable(
            f"{self.name}: no coverage table found at {_URL} "
            "(likely JavaScript-rendered — see scripts/test_providers.py)."
        )
