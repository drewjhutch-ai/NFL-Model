#!/usr/bin/env python3
"""Scrape every Sharp Football Analysis stat table and commit them.

Run by ``.github/workflows/update-coverage.yml`` on a schedule. GitHub's runners
sit on a different network than Streamlit Cloud, so scrapes blocked at app-load
usually succeed here. Each page is written to::

    sharp_data/<key>_<season>.csv

which the deployed app reads (``data/sharp.py``). This is the "lifeblood" feed:
pace, personnel, O-line, D-line, tendencies, coverage, and overall metrics.

Discovery-first: we capture *every* column each page exposes, so the real column
names are visible in the committed CSVs (and in this script's log output) before
the valuation layer is written against them.

Exit codes:
    0  wrote at least one table (fresh data)
    2  every page was blocked / empty (nothing written)

Usage:
    python scripts/fetch_sharp.py [--season 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data.providers.sharp_tables import SHARP_LABELS, scrape_all  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parents[1] / "sharp_data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    frames, errors = scrape_all()

    if not frames:
        print("[fetch_sharp] every page was blocked or empty — nothing written.")
        for key, msg in errors.items():
            print(f"  - {SHARP_LABELS.get(key, key)}: {msg}")
        return 2

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, df in frames.items():
        out = df.reset_index()  # 'team' back to a column
        path = _OUT_DIR / f"{key}_{args.season}.csv"
        out.to_csv(path, index=False)
        label = SHARP_LABELS.get(key, key)
        print(f"[fetch_sharp] {label}: wrote {len(out)} teams x {out.shape[1]} cols -> {path.name}")
        # Surface the real column names so the valuation layer can be written to them.
        print(f"    columns: {list(out.columns)}")

    if errors:
        print("[fetch_sharp] pages that failed this run:")
        for key, msg in errors.items():
            print(f"  - {SHARP_LABELS.get(key, key)}: {msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
