"""Sharp Football Analysis coverage-scheme provider (free, public source).

Warren Sharp publishes team man/zone coverage rates openly (no login/paywall):
    https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-schemes/

Because it's free and public there's no TOS/credential issue — the only question
is whether the host serves our (datacenter) request. Uses the fast HTTP path
first and auto-falls back to a headless browser for JS-rendered tables. Columns
are matched by keyword, so minor layout changes shouldn't break it.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_URL = "https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-schemes/"


def _matcher(tbl: pd.DataFrame) -> pd.DataFrame | None:
    team_col = _scrape.find_col(tbl, "team") or _scrape.find_col(tbl, "defense")
    zone_col = _scrape.find_col(tbl, "zone", "rate") or _scrape.find_col(tbl, "zone", "%") \
        or _scrape.find_col(tbl, "zone")
    man_col = _scrape.find_col(tbl, "man", "rate") or _scrape.find_col(tbl, "man", "%") \
        or _scrape.find_col(tbl, "man")
    if team_col is None or (zone_col is None and man_col is None):
        return None
    data = {"team": tbl[team_col].map(normalize_team)}
    if zone_col is not None:
        data["zone_rate"] = _scrape.to_rate(tbl[zone_col])
    if man_col is not None:
        data["man_rate"] = _scrape.to_rate(tbl[man_col])
    out = pd.DataFrame(data).dropna(subset=["team"])
    return out.set_index("team") if not out.empty else None


class SharpFootballProvider(SchemeDataProvider):
    key = "sharpfootball"
    name = "Sharp Football Analysis"
    trust = 0.85

    def is_available(self) -> bool:
        return True  # network source; fails gracefully when pulling

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        try:
            df = _scrape.extract_table(_URL, _matcher)
        except Exception as exc:  # noqa: BLE001
            raise SchemeUnavailable(f"{self.name} pull failed: {exc}") from exc
        return self.validate(df)
