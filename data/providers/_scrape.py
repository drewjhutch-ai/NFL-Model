"""Shared helpers for the HTML-scraping providers.

Two-stage fetch so a scraper works whether a site renders its tables on the
server or in the browser:

1. **Fast path** — plain HTTP GET + parse (works for server-rendered pages).
2. **Rendered fallback** — drive a real headless Chromium (Playwright) to let
   the page's JavaScript build its tables, then parse (works for React/Vue/etc.).

Parsing finds the right columns by *keyword*, not fixed positions, so a site
tweaking its layout is less likely to break us.

The rendered fallback needs Playwright:
    pip install playwright && playwright install chromium
If it isn't installed, only the fast path is attempted and a clear message is
raised so you know the one command to run.
"""
from __future__ import annotations

import glob
import io
import os
import shutil
from typing import Callable

import pandas as pd
import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# pandas is pinned to the lxml parser: newer beautifulsoup4 releases are
# incompatible with some pandas versions, and lxml is faster anyway.
_FLAVOR = "lxml"


# --- fast path ---------------------------------------------------------------
def fetch_tables(url: str, timeout: int = 20) -> list[pd.DataFrame]:
    """GET a page and return every static HTML <table> as a DataFrame."""
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), flavor=_FLAVOR)


# --- rendered fallback -------------------------------------------------------
def _system_chromium() -> str | None:
    """Locate a system-installed Chromium/Chrome (e.g. apt's on Streamlit Cloud)."""
    env = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or os.environ.get("CHROMIUM_PATH")
    if env and os.path.exists(env):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
        if os.path.exists(path):
            return path
    return None


def _launch_chromium(pw):
    """Launch headless Chromium across local, cloud, and managed environments.

    Order: (1) Playwright's own browser (local, after ``playwright install``);
    (2) a system Chromium from apt (Streamlit Cloud via packages.txt);
    (3) a pre-provisioned browser under PLAYWRIGHT_BROWSERS_PATH (sandboxes).
    """
    # Sandbox headless-shell can be flaky; prefer full chromium there via the glob.
    try:
        return pw.chromium.launch(headless=True)
    except Exception:
        pass

    system = _system_chromium()
    if system:
        try:
            return pw.chromium.launch(headless=True, executable_path=system)
        except Exception:
            pass

    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    patterns = [
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        "chromium-*/chrome-win/chrome.exe",
        "chromium_headless_shell-*/chrome-linux/headless_shell",
    ]
    for pat in patterns:
        for exe in glob.glob(os.path.join(base, pat)):
            try:
                return pw.chromium.launch(headless=True, executable_path=exe)
            except Exception:
                continue
    raise RuntimeError("No usable Chromium found for the rendered-page fallback.")


def fetch_tables_rendered(url: str, timeout_ms: int = 30000) -> list[pd.DataFrame]:
    """Render a page in a real browser, then return its HTML tables."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright isn't installed, so JavaScript-rendered pages can't be "
            "read. Install it once with:\n"
            "    pip install playwright && playwright install chromium"
        ) from exc

    with sync_playwright() as pw:
        browser = _launch_chromium(pw)
        try:
            page = browser.new_page(user_agent=_HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(500)  # let late JS settle
            html = page.content()
        finally:
            browser.close()
    return pd.read_html(io.StringIO(html), flavor=_FLAVOR)


# --- orchestration -----------------------------------------------------------
def extract_table(
    url: str,
    matcher: Callable[[pd.DataFrame], pd.DataFrame | None],
) -> pd.DataFrame:
    """Return the first table on ``url`` that ``matcher`` accepts.

    Tries the fast HTTP path first; if that yields no matching table (or fails),
    falls back to rendering the page in a browser. ``matcher`` takes a raw table
    and returns a cleaned frame, or ``None`` if that table isn't the one we want.
    Raises ``ValueError`` if nothing matches via either method.
    """
    attempts: list[str] = []
    for method in (fetch_tables, fetch_tables_rendered):
        try:
            tables = method(url)
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{method.__name__}: {exc}")
            continue
        for tbl in tables:
            try:
                res = matcher(tbl)
            except Exception:  # noqa: BLE001 - a bad table shouldn't abort
                res = None
            if res is not None and not res.empty:
                return res
        attempts.append(f"{method.__name__}: no match among {len(tables)} table(s)")
    raise ValueError(f"No matching table at {url}. Tried -> " + " | ".join(attempts))


# --- column helpers ----------------------------------------------------------
def find_col(df: pd.DataFrame, *keywords: str) -> str | None:
    """Return the first column whose lowercased name contains all keywords."""
    for col in df.columns:
        name = str(col).lower()
        if all(k in name for k in keywords):
            return col
    return None


def to_rate(series: pd.Series) -> pd.Series:
    """Coerce a percentage-ish column to a 0-1 fraction ('73.2%'/'73.2'/0.732)."""
    s = series.astype(str).str.replace("%", "", regex=False).str.strip()
    vals = pd.to_numeric(s, errors="coerce")
    if vals.dropna().gt(1.5).any():
        vals = vals / 100.0
    return vals
