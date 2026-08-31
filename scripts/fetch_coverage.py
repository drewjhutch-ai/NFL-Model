#!/usr/bin/env python3
"""Fetch team zone/man coverage from the free sources and commit it.

Run by ``.github/workflows/update-coverage.yml`` on a schedule. GitHub's
runners sit on a different network than Streamlit Cloud, so the scrapes that
are blocked at app-load often succeed here. The blended result is written to::

    scheme_data/coverage_<season>.csv

which the deployed app reads automatically (CommittedCoverageProvider), giving
you fresh coverage every week with no upload and no credentials.

Exit codes:
    0  wrote a file (fresh data)
    2  no source returned data (nothing written) -- the sites blocked us too

Usage:
    python scripts/fetch_coverage.py [--season 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data.providers.base import SchemeUnavailable  # noqa: E402
from data.providers.composite import CompositeSchemeProvider  # noqa: E402
from data.providers.sharpfootball import SharpFootballProvider  # noqa: E402
from data.providers.statrankings import StatRankingsProvider  # noqa: E402
from data.providers.sumersports import SumerSportsProvider  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parents[1] / "scheme_data"

# Columns worth committing: the consensus, plus per-source provenance so the
# file is auditable and the app can show which sources agreed.
_KEEP = [
    "zone_rate", "man_rate", "snaps",
    "n_sources", "zone_spread", "confidence", "sources",
    "zone_sharpfootball", "man_sharpfootball",
    "zone_sumersports", "man_sumersports",
    "zone_statrankings", "man_statrankings",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    # Only the free network sources — no PFF (no upload in CI) and no committed
    # provider (that would read the file we're about to write).
    provider = CompositeSchemeProvider(
        providers=[SharpFootballProvider(), SumerSportsProvider(), StatRankingsProvider()]
    )

    try:
        df = provider.coverage_tendencies(args.season)
    except SchemeUnavailable as exc:
        print(f"[fetch_coverage] no data: {exc}")
        return 2

    if df is None or df.empty:
        print("[fetch_coverage] every source was blocked or empty — nothing written.")
        return 2

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = df.reset_index()  # 'team' becomes a column
    keep = ["team"] + [c for c in _KEEP if c in out.columns]
    out = out[keep].sort_values("team")

    path = _OUT_DIR / f"coverage_{args.season}.csv"
    out.to_csv(path, index=False)
    print(f"[fetch_coverage] wrote {len(out)} teams -> {path}")
    print(out[[c for c in ("team", "zone_rate", "man_rate", "n_sources", "sources")
               if c in out.columns]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
