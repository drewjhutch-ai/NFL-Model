#!/usr/bin/env python3
"""Scrape per-player slot rates and commit slot_rates_<season>.csv.

Run by ``.github/workflows/update-coverage.yml`` on a schedule (GitHub's runners
usually aren't blocked the way Streamlit Cloud's servers are). The committed CSV
feeds the WR–CB matchup panel (``data/slot_rates.py`` -> ``coverage_matchup``);
absent it, that panel falls back to depth-chart alignment, so a blocked run is a
no-op, never a breakage.

Exit codes:
    0  wrote the file (fresh data)
    2  every source was blocked / empty (nothing written)

Usage:
    python scripts/fetch_slot_rates.py [--season 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from data.providers.slot_scrape import scrape_slot_rates  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=config.CURRENT_SEASON)
    args = ap.parse_args()

    df = scrape_slot_rates(args.season)
    if df is None or df.empty:
        print("[fetch_slot_rates] every source was blocked or empty — nothing written.")
        return 2

    out = df[["player", "slot_pct"]].copy()
    out["slot_pct"] = out["slot_pct"].round(1)
    path = _ROOT / f"slot_rates_{args.season}.csv"
    out.to_csv(path, index=False)
    src = df["source"].iloc[0] if "source" in df.columns and len(df) else "?"
    print(f"[fetch_slot_rates] wrote {len(out)} players -> {path.name} (source: {src})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
