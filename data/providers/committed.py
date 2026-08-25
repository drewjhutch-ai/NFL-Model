"""Committed-coverage provider — reads the CSV the GitHub Action writes.

The free scrapers (SumerSports, StatRankings) are blocked from Streamlit
Cloud's servers, so instead of scraping at page-load, a scheduled GitHub Action
scrapes from GitHub's network and commits the blended result to
``scheme_data/coverage_<season>.csv``. This provider just reads that file, so the
deployed app gets fresh zone/man coverage every week with no upload and no
credentials.

If the file isn't there yet (Action hasn't run, or every source was blocked),
this provider simply reports unavailable and the app falls back to whatever
else is connected (a PFF upload, or nothing).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import _scrape
from .base import SchemeDataProvider, SchemeUnavailable

_DATA_DIR = Path(__file__).resolve().parents[2] / "scheme_data"


class CommittedCoverageProvider(SchemeDataProvider):
    """Reads scheme_data/coverage_<season>.csv committed by the update Action."""

    key = "committed"
    name = "Auto-fetched (weekly)"
    # It's a blend of the free sources captured from a working network, so trust
    # it like the free sources it came from (not above a manual PFF export).
    trust = 0.85

    def _path(self, season: int) -> Path:
        return _DATA_DIR / f"coverage_{season}.csv"

    def _resolve(self, season: int) -> Path | None:
        path = self._path(season)
        if path.exists():
            return path
        candidates = sorted(_DATA_DIR.glob("coverage_*.csv")) if _DATA_DIR.exists() else []
        return candidates[-1] if candidates else None

    def is_available(self) -> bool:
        return self._resolve(self._latest_season()) is not None

    @staticmethod
    def _latest_season() -> int:
        # Season is only used to pick a filename; is_available scans a glob too,
        # so a rough value is fine here.
        import config
        return config.CURRENT_SEASON

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        path = self._resolve(season)
        if path is None:
            raise SchemeUnavailable(
                f"{self.name}: no committed coverage file in {_DATA_DIR}. "
                "The update workflow may not have run yet."
            )
        raw = pd.read_csv(path)
        team_col = _scrape.find_col(raw, "team") or raw.columns[0]
        zone_col = _scrape.find_col(raw, "zone", "rate") or _scrape.find_col(raw, "zone")
        man_col = _scrape.find_col(raw, "man", "rate") or _scrape.find_col(raw, "man")
        if zone_col is None and man_col is None:
            raise SchemeUnavailable(
                f"{self.name}: {path.name} has no zone/man column "
                f"(found {list(raw.columns)})."
            )
        data = {"team": raw[team_col].astype(str).str.upper().str.strip()}
        if zone_col is not None:
            data["zone_rate"] = _scrape.to_rate(raw[zone_col])
        if man_col is not None:
            data["man_rate"] = _scrape.to_rate(raw[man_col])
        snaps_col = _scrape.find_col(raw, "snap")
        if snaps_col is not None:
            data["snaps"] = pd.to_numeric(raw[snaps_col], errors="coerce")
        df = pd.DataFrame(data).dropna(subset=["team"]).set_index("team")
        return self.validate(df)
