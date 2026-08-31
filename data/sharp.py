"""Read the committed Sharp Football tables — the model's data lifeblood.

The GitHub Action (``scripts/fetch_sharp.py``) scrapes Sharp Football Analysis's
stat pages from GitHub's network and commits each under::

    sharp_data/<key>_<season>.csv

This layer reads them back into team-indexed frames. It degrades gracefully to
*empty* whenever a file isn't there yet (offseason, or before the Action's first
run), so every downstream consumer can call it unconditionally and the app never
breaks on missing data.

Keys are the stable ids from ``data.providers.sharp_tables.SHARP_PAGES``:
    pace, off_personnel, def_line, def_tendencies, coverage_schemes,
    def_metrics, off_tendencies, off_line, coverage_by_pos, off_metrics
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.providers.sharp_tables import SHARP_LABELS, SHARP_PAGES

_DATA_DIR = Path(__file__).resolve().parents[1] / "sharp_data"

# Public re-exports so callers don't reach into the providers package.
KEYS: tuple[str, ...] = tuple(SHARP_PAGES.keys())
LABELS: dict[str, str] = dict(SHARP_LABELS)


def _resolve(key: str, season: int) -> Path | None:
    """Path to this key's CSV for ``season``, else the newest season on disk."""
    exact = _DATA_DIR / f"{key}_{season}.csv"
    if exact.exists():
        return exact
    if not _DATA_DIR.exists():
        return None
    candidates = sorted(_DATA_DIR.glob(f"{key}_*.csv"))
    return candidates[-1] if candidates else None


def load_table(key: str, season: int) -> pd.DataFrame:
    """Team-indexed frame for one Sharp table, or an empty frame if absent.

    The returned frame is indexed by canonical team abbreviation; columns are
    whatever that page exposes (see the committed CSV / the fetch-script log).
    """
    path = _resolve(key, season)
    if path is None:
        return pd.DataFrame()
    try:
        raw = pd.read_csv(path)
    except Exception:  # noqa: BLE001 - a corrupt file must never break the app
        return pd.DataFrame()
    if raw.empty or "team" not in raw.columns:
        # Tolerate a stray index column name.
        if not raw.empty and raw.columns[0].lower() in ("team", "unnamed: 0"):
            raw = raw.rename(columns={raw.columns[0]: "team"})
        else:
            return pd.DataFrame()
    raw["team"] = raw["team"].astype(str).str.upper().str.strip()
    return raw.dropna(subset=["team"]).drop_duplicates("team").set_index("team")


def load_all(season: int) -> dict[str, pd.DataFrame]:
    """Every available Sharp table for ``season``, keyed by id (empties skipped)."""
    out: dict[str, pd.DataFrame] = {}
    for key in KEYS:
        df = load_table(key, season)
        if not df.empty:
            out[key] = df
    return out


def available(season: int) -> list[str]:
    """The keys that actually have data committed for ``season``."""
    return [k for k in KEYS if not load_table(k, season).empty]


def is_available(season: int) -> bool:
    """True if at least one Sharp table has been committed."""
    return bool(available(season))


def merged(season: int) -> pd.DataFrame:
    """All available tables joined into one wide, team-indexed frame.

    Columns are namespaced ``<key>__<column>`` so same-named stats from
    different tables never collide. Empty if nothing is committed yet.
    """
    frames = load_all(season)
    if not frames:
        return pd.DataFrame()
    wide = []
    for key, df in frames.items():
        renamed = df.add_prefix(f"{key}__")
        wide.append(renamed)
    return pd.concat(wide, axis=1)


def column_map(season: int) -> dict[str, list[str]]:
    """Diagnostic: {key: [column names]} for whatever is committed.

    Handy while wiring the valuation layer — it shows the real column names the
    scraper produced, straight from the committed CSVs.
    """
    return {key: list(df.columns) for key, df in load_all(season).items()}
