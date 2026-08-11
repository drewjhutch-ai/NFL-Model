"""Pluggable live-odds providers (for line movement & sharp-money signals).

Today the betting model runs off the free schedule lines (one consensus number).
Line *movement* (open → current) and true sharp signals (money% vs bet%, reverse
line movement) need a live feed. This module defines the seam so one drops in
without touching the betting logic.

Options when you're ready:
  * **The Odds API** (the-odds-api.com) — free tier ~500 req/mo; multi-book
    spreads/totals/moneylines. Snapshot periodically to build movement + detect
    reverse line movement. Put the key in Streamlit secrets as ODDS_API_KEY.
  * **Action Network / Unabated / Sports Insights** — actual bet% / handle% and
    sharp splits, but paid.

Implement ``LiveOddsProvider`` and point ``get_odds_provider`` at it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class LiveOddsProvider(ABC):
    name: str = "unnamed"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def movement(self, season: int, week: int) -> pd.DataFrame:
        """Per-game open/current lines (and, if available, bet%/handle%).

        Expected columns when implemented: game_id, open_spread, current_spread,
        open_total, current_total, bet_pct_home, handle_pct_home.
        """


class NoLiveOdds(LiveOddsProvider):
    """Default: no live feed connected."""
    name = "none"

    def is_available(self) -> bool:
        return False

    def movement(self, season: int, week: int) -> pd.DataFrame:
        return pd.DataFrame()


def get_odds_provider() -> LiveOddsProvider:
    # Swap for an Odds-API-backed provider once a key is configured.
    return NoLiveOdds()
