"""SumerSports.com coverage-scheme provider (free source).

Pulls team man/zone coverage tendencies from the public defensive team stats:
    https://sumersports.com/teams/defensive/

Uses the fast HTTP path first and auto-falls back to a headless browser if the
page renders its tables with JavaScript (SumerSports is a React site, so the
fallback is the likely path). Columns are matched by keyword.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_URL = "https://sumersports.com/teams/defensive/"


def _matcher(tbl: pd.DataFrame) -> pd.DataFrame | None:
    team_col = _scrape.find_col(tbl, "team") or _scrape.find_col(tbl, "defense")
    zone_col = _scrape.find_col(tbl, "zone")
    man_col = _scrape.find_col(tbl, "man")
    if team_col is None or (zone_col is None and man_col is None):
        return None
    data = {"team": tbl[team_col].map(normalize_team)}
    if zone_col is not None:
        data["zone_rate"] = _scrape.to_rate(tbl[zone_col])
    if man_col is not None:
        data["man_rate"] = _scrape.to_rate(tbl[man_col])
    out = pd.DataFrame(data).dropna(subset=["team"])
    return out.set_index("team") if not out.empty else None


class SumerSportsProvider(SchemeDataProvider):
    key = "sumersports"
    name = "SumerSports"
    trust = 0.85

    def is_available(self) -> bool:
        return True

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        try:
            df = _scrape.extract_table(_URL, _matcher)
        except Exception as exc:  # noqa: BLE001
            raise SchemeUnavailable(f"{self.name} pull failed: {exc}") from exc
        return self.validate(df)
