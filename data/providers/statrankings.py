"""StatRankings.com coverage-scheme provider (free source).

Pulls team man/zone coverage rate from the public advanced-stats tables:
    https://statrankings.com/nfl/advanced/teams/coverage/zone-coverage-rate/
    https://statrankings.com/nfl/advanced/teams/coverage/man-coverage-rate/

⚠️  Structure inferred, not verified from the build sandbox. If the live parse
    fails, run scripts/test_providers.py and tweak the keyword hints / URLs.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_ZONE_URL = "https://statrankings.com/nfl/advanced/teams/coverage/zone-coverage-rate/"
_MAN_URL = "https://statrankings.com/nfl/advanced/teams/coverage/man-coverage-rate/"


class StatRankingsProvider(SchemeDataProvider):
    key = "statrankings"
    name = "StatRankings"
    trust = 0.75

    def is_available(self) -> bool:
        # Network source: assume reachable, fail gracefully when pulling.
        return True

    def _pull_one(self, url: str, kind: str) -> pd.DataFrame:
        tables = _scrape.fetch_tables(url)
        for tbl in tables:
            team_col = (_scrape.find_col(tbl, "team") or _scrape.find_col(tbl, "defense"))
            rate_col = (
                _scrape.find_col(tbl, kind, "rate")
                or _scrape.find_col(tbl, kind, "%")
                or _scrape.find_col(tbl, kind, "coverage")
                or _scrape.find_col(tbl, kind)
            )
            if team_col is not None and rate_col is not None:
                out = pd.DataFrame(
                    {
                        "team": tbl[team_col].map(normalize_team),
                        f"{kind}_rate": _scrape.to_rate(tbl[rate_col]),
                    }
                ).dropna(subset=["team"])
                return out.set_index("team")
        raise SchemeUnavailable(f"{self.name}: couldn't find a {kind}-coverage table at {url}")

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        try:
            zone = self._pull_one(_ZONE_URL, "zone")
        except Exception as exc:  # noqa: BLE001
            raise SchemeUnavailable(f"{self.name} zone pull failed: {exc}") from exc
        try:
            man = self._pull_one(_MAN_URL, "man")
        except Exception:  # noqa: BLE001 - man is optional; infer from zone
            man = None

        df = zone if man is None else zone.join(man, how="outer")
        return self.validate(df)
