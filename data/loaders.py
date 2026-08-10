"""Data loading from the free nflverse data set via ``nfl_data_py``.

Every loader is season-tolerant: asking for a season that hasn't been played yet
(e.g. 2026 during the offseason) returns an empty frame instead of raising, so
the rest of the app can fall back to the phantom baseline.

All loaders are wrapped in Streamlit's cache so the (slow) network pull only
happens once per session / TTL.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config

# Only pull the play-by-play columns we actually use. Keeps the download and the
# in-memory frame an order of magnitude smaller than the full ~380-column table.
_PBP_COLUMNS = [
    "game_id",
    "play_id",
    "season",
    "week",
    "season_type",
    "posteam",
    "defteam",
    "play_type",
    "pass",
    "rush",
    "qb_dropback",
    "epa",
    "success",
    "yards_gained",
    "air_yards",
    "cpoe",
    "down",
    "wp",
    "half_seconds_remaining",
    "pass_oe",
    "touchdown",
    "first_down",
    "penalty",
]

_FTN_COLUMNS = [
    "nflverse_game_id",
    "nflverse_play_id",
    "season",
    "week",
    "n_blitzers",
    "n_defense_box",
    "is_play_action",
    "is_no_huddle",
    "is_motion",
]

# One hour: long enough to be cheap during a session, short enough that a live
# in-season refresh picks up the latest week within the hour.
_CACHE_TTL = 60 * 60


def _safe_import(fn, years, **kwargs) -> pd.DataFrame:
    """Call an nfl_data_py importer, tolerating seasons that don't exist yet."""
    frames = []
    for year in years:
        try:
            frames.append(fn([year], **kwargs))
        except Exception as exc:  # noqa: BLE001 - nfl_data_py raises many types
            # A missing season file (offseason / not released) is expected and
            # non-fatal; anything else we still swallow so one bad year can't
            # take down the whole dashboard, but we surface it to the console.
            print(f"[loaders] {fn.__name__} unavailable for {year}: {exc}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading play-by-play from nflverse…")
def load_pbp(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Regular-season play-by-play for the requested seasons."""
    import nfl_data_py as nfl

    df = _safe_import(nfl.import_pbp_data, list(seasons), columns=_PBP_COLUMNS,
                      downcast=True, cache=False)
    if df.empty:
        return df
    if "season_type" in df.columns:
        df = df[df["season_type"] == "REG"]
    # Real scrimmage plays only.
    df = df[df["play_type"].isin(["pass", "run"])].copy()
    return df


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading FTN charting…")
def load_ftn(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """FTN charting data (2022+). Powers blitz rate and a few scheme signals."""
    import nfl_data_py as nfl

    if not hasattr(nfl, "import_ftn_data"):
        return pd.DataFrame()
    df = _safe_import(nfl.import_ftn_data, list(seasons))
    if df.empty:
        return df
    keep = [c for c in _FTN_COLUMNS if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading team metadata…")
def load_team_desc() -> pd.DataFrame:
    """Team abbreviations, names, colors, logos."""
    import nfl_data_py as nfl

    try:
        return nfl.import_team_desc()
    except Exception as exc:  # noqa: BLE001
        print(f"[loaders] team desc unavailable: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading schedule…")
def load_schedule(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Game schedule / results for the requested seasons."""
    import nfl_data_py as nfl

    return _safe_import(nfl.import_schedules, list(seasons))


def add_recency_weight(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a per-play ``w`` column implementing the phantom-baseline scheme.

    Current-season plays weigh 1.0; prior-season plays weigh
    ``config.PRIOR_SEASON_WEIGHT``. Anything else (older) is dropped.
    """
    if df.empty or "season" not in df.columns:
        return df.assign(w=1.0) if not df.empty else df
    out = df.copy()
    out["w"] = 0.0
    out.loc[out["season"] == config.CURRENT_SEASON, "w"] = 1.0
    out.loc[out["season"] == config.PRIOR_SEASON, "w"] = config.PRIOR_SEASON_WEIGHT
    return out[out["w"] > 0].copy()


def has_current_season_data(df: pd.DataFrame) -> bool:
    """True once real current-season plays exist (drives the 'live' banner)."""
    if df.empty or "season" not in df.columns:
        return False
    return bool((df["season"] == config.CURRENT_SEASON).any())
