"""Per-player slot rate — sharpens the WR–CB alignment when charting data exists.

The depth chart says who the *nominal* slot man is (the SWR designation); a slot
RATE says how often each receiver actually lines up inside, which is what you want
for a WR–CB matchup. Sources like StatRankings and RotoWire publish it free, but
they're brittle to scrape (StatRankings just changed its layout and broke our
coverage feed), so this reads it from a committed CSV instead:

    slot_rates_<season>.csv   columns: player (name), slot_pct (0-100)

Populate it by hand or from a verified scrape; absent, the WR–CB panel falls back
to depth-chart alignment. Returns {name_lower: slot_pct}.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load(season: int) -> dict[str, float]:
    p = Path(__file__).resolve().parents[1] / f"slot_rates_{season}.csv"
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p)
        cols = {c.lower(): c for c in df.columns}
        pc = cols.get("player") or cols.get("name")
        sc = cols.get("slot_pct") or cols.get("slot_rate") or cols.get("slot")
        if not pc or not sc:
            return {}
        out: dict[str, float] = {}
        for _, r in df.iterrows():
            nm = str(r[pc]).strip().lower()
            try:
                v = float(r[sc])
            except (TypeError, ValueError):
                continue
            if nm and pd.notna(v):
                out[nm] = v
        return out
    except Exception:  # noqa: BLE001 - a bad file must never break the build
        return {}
