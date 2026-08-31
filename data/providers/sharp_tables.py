"""Config-driven scrapers for Sharp Football Analysis's public stat tables.

Warren Sharp publishes a family of charted team tables openly (no login, no
paywall): pace, personnel, O-line, D-line, tendencies, coverage, and overall
metrics. They all share one consistent page layout, so a single generic scraper
plus a page registry covers every one of them.

**Discovery-first.** Rather than guess each page's exact column names from a
sandbox that can't reach the site, we capture *every* column (normalized to a
canonical team) into ``sharp_data/<key>_<season>.csv``. The committed CSVs then
tell us the real column names, and the valuation layer is written against
reality. Keyword matching keeps minor layout tweaks from breaking us.

This module is intentionally dependency-light and reuses the shared two-stage
fetch (fast HTTP → headless-Chromium fallback) in ``_scrape``.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team

from . import _scrape


class SharpUnavailable(Exception):
    """Raised when a Sharp page can't be scraped into a team table."""


# --- the registry ------------------------------------------------------------
# key -> public URL. Keys are stable (used as the CSV filename stem and the
# data-layer accessor), so downstream code never hard-codes a URL.
SHARP_PAGES: dict[str, str] = {
    "pace": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-team-pace-stats/",
    "off_personnel": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-personnel/",
    "def_line": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-defensive-line-stats/",
    "def_tendencies": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-defensive-tendencies/",
    "coverage_schemes": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-schemes/",
    "def_metrics": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-defensive-stats/",
    "off_tendencies": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-tendencies-stats/",
    "off_line": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-line-stats/",
    "coverage_by_pos": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-stats-by-position/",
    "off_metrics": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-stats/",
}

# A human label per key, for logs and UI.
SHARP_LABELS: dict[str, str] = {
    "pace": "Team Pace",
    "off_personnel": "Offensive Personnel",
    "def_line": "Defensive Line",
    "def_tendencies": "Defensive Tendencies",
    "coverage_schemes": "Coverage Schemes",
    "def_metrics": "Defensive Metrics",
    "off_tendencies": "Offensive Tendencies",
    "off_line": "Offensive Line",
    "coverage_by_pos": "Coverage by Position",
    "off_metrics": "Offensive Metrics",
}

# The minimum resolved-team rows for a parsed table to count as "the" team
# table on a page (guards against matching a stray 2-row promo table).
_MIN_TEAMS = 8


# --- column + value cleaning -------------------------------------------------
def _flatten_columns(cols) -> list[str]:
    """Collapse a (possibly MultiIndex) header into unique, readable names."""
    flat: list[str] = []
    for col in cols:
        if isinstance(col, tuple):
            parts = [
                str(p).strip()
                for p in col
                if str(p).strip() and not str(p).lower().startswith("unnamed")
            ]
            # dedupe while preserving order ("Pass Pass Rate" -> "Pass Rate")
            name = " ".join(dict.fromkeys(parts))
        else:
            name = str(col).strip()
        flat.append(name if name else "col")
    # make duplicates unique so a DataFrame/CSV round-trips cleanly
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in flat:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def _numify(series: pd.Series) -> pd.Series:
    """Parse a column to numbers when most of it is numeric; else leave as text.

    Strips ``%`` and thousands separators. Percentages are kept on their native
    scale here (73.2, not 0.732) — the valuation layer decides per-column
    whether a value is a rate. This keeps the discovery CSVs faithful.
    """
    cleaned = (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    num = pd.to_numeric(cleaned, errors="coerce")
    if num.notna().mean() >= 0.5:
        return num
    return series


def _normalize_team_table(tbl: pd.DataFrame) -> pd.DataFrame | None:
    """Turn a raw scraped table into a team-indexed frame, or None if it isn't one."""
    if tbl is None or tbl.empty:
        return None
    tbl = tbl.copy()
    tbl.columns = _flatten_columns(tbl.columns)

    team_col = (
        _scrape.find_col(tbl, "team")
        or _scrape.find_col(tbl, "defense")
        or _scrape.find_col(tbl, "offense")
    )
    if team_col is None:
        return None

    teams = tbl[team_col].map(normalize_team)
    keep = teams.notna()
    if keep.sum() < _MIN_TEAMS:
        return None

    out = pd.DataFrame({"team": teams[keep].values})
    for col in tbl.columns:
        if col == team_col:
            continue
        out[col] = _numify(tbl.loc[keep, col].reset_index(drop=True))

    out = out.drop_duplicates(subset="team", keep="first")
    return out.set_index("team") if not out.empty else None


def _best_team_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    """Pick the parsed team table with the most teams (closest to a full 32)."""
    best: pd.DataFrame | None = None
    for raw in tables:
        try:
            parsed = _normalize_team_table(raw)
        except Exception:  # noqa: BLE001 - a bad table must not abort the page
            parsed = None
        if parsed is not None and (best is None or len(parsed) > len(best)):
            best = parsed
    return best


# --- public scraping ---------------------------------------------------------
def scrape_sharp_page(url: str) -> pd.DataFrame:
    """Scrape ``url`` and return its main team table (all columns), team-indexed.

    Tries the fast HTTP path, then a rendered-browser fallback. Raises
    ``SharpUnavailable`` if no team table is found either way.
    """
    attempts: list[str] = []
    for method in (_scrape.fetch_tables, _scrape.fetch_tables_rendered):
        try:
            tables = method(url)
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{method.__name__}: {exc}")
            continue
        best = _best_team_table(tables)
        if best is not None:
            return best
        attempts.append(f"{method.__name__}: no team table among {len(tables)}")
    raise SharpUnavailable(f"No team table at {url}. Tried -> " + " | ".join(attempts))


def scrape_all() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Scrape every registered page.

    Returns ``(frames, errors)`` where ``frames[key]`` is a team-indexed table
    and ``errors[key]`` is the failure message for any page that couldn't be
    scraped. One page failing never aborts the rest.
    """
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for key, url in SHARP_PAGES.items():
        try:
            frames[key] = scrape_sharp_page(url)
        except Exception as exc:  # noqa: BLE001
            errors[key] = str(exc)
    return frames, errors
