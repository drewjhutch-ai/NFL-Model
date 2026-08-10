#!/usr/bin/env python3
"""Local smoke test for the coverage-scheme providers.

Run this on your own machine (the build sandbox can't reach the stats sites):

    python scripts/test_providers.py

It pings each source, prints what came back, and shows the blended consensus.

The scrapers try a fast HTTP fetch first and automatically fall back to a real
headless browser for JavaScript-rendered pages. That fallback needs Playwright:

    pip install -r requirements.txt      # includes playwright
    playwright install chromium          # one-time browser download (~150 MB)

If you see a "Playwright isn't installed" message, run those two commands.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data.providers import (  # noqa: E402
    SchemeUnavailable,
    get_provider,
)
from data.providers.pff_csv import PFFCoverageProvider  # noqa: E402
from data.providers.statrankings import StatRankingsProvider  # noqa: E402
from data.providers.sumersports import SumerSportsProvider  # noqa: E402

SEASON = config.CURRENT_SEASON


def _try(provider):
    print(f"\n=== {provider.name} (key={provider.key}, trust={provider.trust}) ===")
    print("available:", provider.is_available())
    try:
        df = provider.coverage_tendencies(SEASON)
        print(f"rows: {len(df)}")
        print(df.head(10).to_string())
    except SchemeUnavailable as exc:
        print("UNAVAILABLE:", exc)
    except Exception as exc:  # noqa: BLE001
        print("ERROR:", type(exc).__name__, exc)


def main():
    for p in (PFFCoverageProvider(), SumerSportsProvider(), StatRankingsProvider()):
        _try(p)

    print("\n\n########## BLENDED CONSENSUS ##########")
    try:
        blended = get_provider().coverage_tendencies(SEASON)
        cols = [c for c in ["zone_rate", "man_rate", "confidence", "n_sources", "sources"]
                if c in blended.columns]
        print(blended[cols].sort_values("zone_rate", ascending=False).to_string())
    except SchemeUnavailable as exc:
        print("No sources available:", exc)


if __name__ == "__main__":
    main()

# The requests -> headless-browser fallback is built into data/providers/_scrape.py
# (extract_table). You don't need to wire anything up; just make sure Playwright
# is installed (see the module docstring above) if a site is JavaScript-rendered.
