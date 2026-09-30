"""Per-player slot-rate scraper — auto-populates slot_rates_<season>.csv.

Slot rate (how often a receiver lines up inside) is the charting input the WR–CB
panel wants: the depth chart only says who the *nominal* slot man is, while a rate
says how each receiver is actually deployed. A handful of public pages publish it
for free, but they're brittle (StatRankings changed its layout and broke our
coverage feed once already), so this is written to *never* be load-bearing:

* it runs only in the weekly GitHub Action, never at app load;
* it tries an ordered list of candidate pages and takes the first that yields a
  (player, slot%) table, matched by keyword so small layout tweaks don't break it;
* if every source is blocked/empty it returns an empty frame, the fetch script
  exits 2, and the committed CSV (or depth-chart fallback) is left untouched.

Add or reorder sources in ``SLOT_SOURCES`` as pages come and go. The matcher
accepts any table exposing a name column plus a column whose header mentions
"slot"; percentages are normalised to a 0-100 scale to match the CSV contract.
"""
from __future__ import annotations

import pandas as pd

from . import _scrape

# Candidate pages, tried in order. Each is a free per-player slot-rate table.
# Kept as a list so a dead source is skipped, not fatal — order by reliability.
SLOT_SOURCES: list[str] = [
    "https://www.fantasypros.com/nfl/advanced-stats-wr.php",
    "https://statrankings.com/nfl/advanced/players/receiving/slot-rate/",
]


def _name_col(tbl: pd.DataFrame) -> str | None:
    col = (_scrape.find_col(tbl, "player") or _scrape.find_col(tbl, "name")
           or _scrape.find_col(tbl, "receiver"))
    if col is not None:
        return col
    # fall back to the first text-like column (many stat tables lead with the name)
    for c in tbl.columns:
        if tbl[c].dtype == object:
            return c
    return None


def _slot_col(tbl: pd.DataFrame) -> str | None:
    return (_scrape.find_col(tbl, "slot", "%")
            or _scrape.find_col(tbl, "slot", "rate")
            or _scrape.find_col(tbl, "slot", "pct")
            or _scrape.find_col(tbl, "slot", "snap")
            or _scrape.find_col(tbl, "slot"))


def _clean_name(x) -> str:
    """'A.J. Brown (PHI)' / 'A.J. Brown WR' -> 'a.j. brown' (matches roster names)."""
    s = str(x).strip()
    for cut in (" (",):                       # drop trailing '(TEAM)'
        if cut in s:
            s = s.split(cut, 1)[0]
    return s.strip()


def _matcher(tbl: pd.DataFrame) -> pd.DataFrame | None:
    # flatten a MultiIndex header (some advanced tables ship two header rows)
    if isinstance(tbl.columns, pd.MultiIndex):
        tbl = tbl.copy()
        tbl.columns = [" ".join(str(x) for x in c if str(x) != "nan").strip()
                       for c in tbl.columns]
    ncol, scol = _name_col(tbl), _slot_col(tbl)
    if ncol is None or scol is None:
        return None
    slot = _scrape.to_rate(tbl[scol]) * 100.0   # to_rate -> 0-1; CSV wants 0-100
    out = pd.DataFrame({"player": tbl[ncol].map(_clean_name), "slot_pct": slot})
    out = out.dropna(subset=["slot_pct"])
    out = out[out["player"].str.len() > 2]
    return out if len(out) >= 5 else None        # a real board has many players


def scrape_slot_rates(season: int | None = None) -> pd.DataFrame:
    """Return a (player, slot_pct) frame from the first source that answers.

    Empty frame if every source is blocked/empty — callers must treat that as
    "no data this run" and leave the committed file alone.
    """
    for url in SLOT_SOURCES:
        try:
            df = _scrape.extract_table(url, _matcher)
        except Exception:  # noqa: BLE001 - a dead source is skipped, never fatal
            continue
        if df is not None and not df.empty:
            df = df.drop_duplicates(subset=["player"]).reset_index(drop=True)
            df["source"] = url
            return df
    return pd.DataFrame(columns=["player", "slot_pct"])
