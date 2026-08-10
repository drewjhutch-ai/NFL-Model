"""StatRankings.com coverage-scheme provider (free source).

Pulls team man/zone coverage rate from the public advanced-stats tables:
    https://statrankings.com/nfl/advanced/teams/coverage/zone-coverage-rate/
    https://statrankings.com/nfl/advanced/teams/coverage/man-coverage-rate/

Uses the fast HTTP path first and auto-falls back to a headless browser if the
page renders its tables with JavaScript. Structure is matched by keyword, so
minor layout changes shouldn't break it; if the live parse fails, run
scripts/test_providers.py to see what came back.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_ZONE_URL = "https://statrankings.com/nfl/advanced/teams/coverage/zone-coverage-rate/"
_MAN_URL = "https://statrankings.com/nfl/advanced/teams/coverage/man-coverage-rate/"


def _make_matcher(kind: str):
    """Build a table-matcher that extracts (team, <kind>_rate)."""
    def matcher(tbl: pd.DataFrame) -> pd.DataFrame | None:
        team_col = _scrape.find_col(tbl, "team") or _scrape.find_col(tbl, "defense")
        rate_col = (
            _scrape.find_col(tbl, kind, "rate")
            or _scrape.find_col(tbl, kind, "%")
            or _scrape.find_col(tbl, kind, "coverage")
            or _scrape.find_col(tbl, kind)
        )
        if team_col is None or rate_col is None:
            return None
        out = pd.DataFrame(
            {
                "team": tbl[team_col].map(normalize_team),
                f"{kind}_rate": _scrape.to_rate(tbl[rate_col]),
            }
        ).dropna(subset=["team"])
        return out.set_index("team") if not out.empty else None

    return matcher


class StatRankingsProvider(SchemeDataProvider):
    key = "statrankings"
    name = "StatRankings"
    trust = 0.75

    def is_available(self) -> bool:
        return True  # network source; fails gracefully when pulling

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        try:
            zone = _scrape.extract_table(_ZONE_URL, _make_matcher("zone"))
        except Exception as exc:  # noqa: BLE001
            raise SchemeUnavailable(f"{self.name} zone pull failed: {exc}") from exc
        try:
            man = _scrape.extract_table(_MAN_URL, _make_matcher("man"))
        except Exception:  # noqa: BLE001 - man optional; base.validate infers it
            man = None

        df = zone if man is None else zone.join(man, how="outer")
        return self.validate(df)
