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
    "ydstogo",
    "yardline_100",
    "wp",
    "half_seconds_remaining",
    "pass_oe",
    "touchdown",
    "first_down",
    "penalty",
    "complete_pass",
    "receiver_player_id",
    "rusher_player_id",
    "passer_player_id",
    "sack",
    "qb_hit",
    "qb_scramble",
    "fumble_lost",
    "interception",
    "fixed_drive",
    "fixed_drive_result",
    "series_result",
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


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading special teams…")
def load_special_teams(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Special-teams plays (for a team ST-points contribution)."""
    import nfl_data_py as nfl

    cols = ["game_id", "season", "week", "season_type", "posteam", "special", "epa", "play_type"]
    df = _safe_import(nfl.import_pbp_data, list(seasons), columns=cols,
                      downcast=True, cache=False)
    if df.empty:
        return df
    if "season_type" in df.columns:
        df = df[df["season_type"] == "REG"]
    if "special" in df.columns:
        df = df[df["special"] == 1]
    return df[df["posteam"].notna() & df["epa"].notna()].copy()


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


_TEAM_META_URL = ("https://raw.githubusercontent.com/nflverse/nflfastR-data/"
                  "master/teams_colors_logos.csv")


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading team branding…")
def load_team_desc() -> pd.DataFrame:
    """Team abbreviations, names, colors, and logos (from a reachable mirror)."""
    try:
        return pd.read_csv(_TEAM_META_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"[loaders] team meta unavailable: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=_CACHE_TTL)
def team_meta() -> dict[str, dict]:
    """abbr -> {name, color, color2, logo} for headers and accents."""
    df = load_team_desc()
    if df.empty:
        return {}
    out = {}
    for _, r in df.iterrows():
        abbr = r.get("team_abbr")
        if not isinstance(abbr, str):
            continue
        out[abbr] = {
            "name": r.get("team_name", abbr),
            "color": r.get("team_color", "#1f77b4"),
            "color2": r.get("team_color2", "#333333"),
            "logo": r.get("team_logo_espn") or r.get("team_logo_wikipedia", ""),
            "conf": r.get("team_conf", ""),
            "division": r.get("team_division", ""),
        }
    return out


# nflverse's schedule file, served from a host our environments can reach
# (nfl_data_py's default URL is blocked by some proxies).
_SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading schedule…")
def load_schedule(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Game schedule / results for the requested seasons (incl. future games)."""
    try:
        df = pd.read_csv(_SCHEDULE_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"[loaders] schedule unavailable: {exc}")
        return pd.DataFrame()
    df = df[df["season"].isin(list(seasons))].copy()
    keep = [c for c in ["game_id", "season", "week", "gameday", "weekday",
                        "away_team", "home_team", "result", "away_score",
                        "home_score", "spread_line", "total_line",
                        "away_moneyline", "home_moneyline", "away_spread_odds",
                        "home_spread_odds", "over_odds", "under_odds",
                        "away_rest", "home_rest", "div_game", "roof",
                        "surface", "temp", "wind"] if c in df.columns]
    return df[keep]


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading player stats…")
def load_weekly_player(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Per-player, per-week offensive stats (for player usage & prop projections)."""
    import nfl_data_py as nfl

    df = _safe_import(nfl.import_weekly_data, list(seasons))
    if df.empty:
        return df
    keep = [c for c in ["player_id", "player_display_name", "position", "recent_team",
                        "opponent_team", "season", "week", "attempts", "completions",
                        "passing_yards", "passing_tds", "interceptions", "carries",
                        "rushing_yards", "rushing_tds", "targets", "receptions",
                        "receiving_yards", "receiving_tds"] if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading rushing tracking…")
def load_ngs_rushing(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Next Gen Stats rushing (season totals, week==0) for RB playstyle."""
    import nfl_data_py as nfl

    frames = []
    for year in seasons:
        try:
            frames.append(nfl.import_ngs_data(stat_type="rushing", years=[year]))
        except Exception as exc:  # noqa: BLE001
            print(f"[loaders] NGS rushing unavailable for {year}: {exc}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df
    if "week" in df.columns:
        df = df[df["week"] == 0]  # season cumulative rows
    keep = [c for c in ["season", "team_abbr", "player_gsis_id", "player_position",
                        "rush_attempts", "efficiency", "rush_yards_over_expected",
                        "rush_yards_over_expected_per_att",
                        "percent_attempts_gte_eight_defenders", "avg_time_to_los"]
            if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading passing tracking…")
def load_ngs_passing(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Next Gen Stats passing (season totals, week==0) — time to throw, CPOE, aggressiveness."""
    import nfl_data_py as nfl

    frames = []
    for year in seasons:
        try:
            frames.append(nfl.import_ngs_data(stat_type="passing", years=[year]))
        except Exception as exc:  # noqa: BLE001
            print(f"[loaders] NGS passing unavailable for {year}: {exc}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df
    if "week" in df.columns:
        df = df[df["week"] == 0]
    keep = [c for c in ["season", "team_abbr", "player_gsis_id", "player_display_name",
                        "attempts", "avg_time_to_throw", "aggressiveness",
                        "completion_percentage_above_expectation",
                        "avg_air_yards_differential", "avg_intended_air_yards"]
            if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading receiving tracking…")
def load_ngs_receiving(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Next Gen Stats receiving (season totals, week==0) — separation, cushion, YAC over expected."""
    import nfl_data_py as nfl

    frames = []
    for year in seasons:
        try:
            frames.append(nfl.import_ngs_data(stat_type="receiving", years=[year]))
        except Exception as exc:  # noqa: BLE001
            print(f"[loaders] NGS receiving unavailable for {year}: {exc}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df
    if "week" in df.columns:
        df = df[df["week"] == 0]
    keep = [c for c in ["season", "team_abbr", "player_gsis_id", "player_display_name",
                        "targets", "receptions", "avg_cushion", "avg_separation",
                        "avg_yac_above_expectation", "avg_intended_air_yards",
                        "percent_share_of_intended_air_yards"]
            if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading rosters…")
def load_rosters(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Player rosters (for player_id -> position mapping)."""
    import nfl_data_py as nfl

    df = _safe_import(nfl.import_seasonal_rosters, list(seasons))
    if df.empty:
        return df
    keep = [c for c in ["season", "player_id", "pfr_id", "position", "player_name",
                        "team", "depth_chart_position"] if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading injury reports…")
def load_injuries(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Weekly injury reports (game status per player)."""
    import nfl_data_py as nfl

    df = _safe_import(nfl.import_injuries, list(seasons))
    if df.empty:
        return df
    keep = [c for c in ["season", "week", "team", "gsis_id", "full_name",
                        "position", "report_status", "report_primary_injury",
                        "report_secondary_injury", "practice_status",
                        "practice_primary_injury"]
            if c in df.columns]
    return df[keep].copy()


@st.cache_data(ttl=_CACHE_TTL, show_spinner="Loading snap counts…")
def load_snaps(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> pd.DataFrame:
    """Per-game snap counts / shares (for gauging who actually plays)."""
    import nfl_data_py as nfl

    df = _safe_import(nfl.import_snap_counts, list(seasons))
    if df.empty:
        return df
    keep = [c for c in ["season", "week", "player", "pfr_player_id", "position",
                        "team", "offense_pct", "defense_pct"] if c in df.columns]
    return df[keep].copy()


def position_map(seasons: tuple[int, ...] = tuple(config.SEASONS)) -> dict[str, str]:
    """player_id -> position, current season overriding the prior."""
    rosters = load_rosters(seasons)
    if rosters.empty or "player_id" not in rosters.columns:
        return {}
    rosters = rosters.sort_values("season")  # current last -> wins on dedupe
    return dict(zip(rosters["player_id"], rosters["position"]))


def current_week(schedule: pd.DataFrame, season: int) -> int | None:
    """The week to show by default: earliest with an unplayed game, else last."""
    if schedule.empty:
        return None
    s = schedule[schedule["season"] == season]
    if s.empty:
        return None
    if "result" in s.columns:
        unplayed = s[s["result"].isna()]
        if not unplayed.empty:
            return int(unplayed["week"].min())
    return int(s["week"].max())


def add_recency_weight(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a per-play ``w`` column implementing the phantom-baseline scheme.

    Current-season plays weigh 1.0; prior-season plays weigh
    ``config.PRIOR_SEASON_WEIGHT``. Anything else (older) is dropped.
    """
    if df.empty or "season" not in df.columns:
        return df.assign(w=1.0) if not df.empty else df
    out = df.copy()
    out["w"] = 0.0
    cur = out["season"] == config.CURRENT_SEASON
    out.loc[cur, "w"] = 1.0
    # intra-season recency: recent weeks weigh more than early ones
    if cur.any() and "week" in out.columns:
        maxw = out.loc[cur, "week"].max()
        weeks_back = (maxw - out.loc[cur, "week"]).clip(lower=0)
        out.loc[cur, "w"] = config.RECENCY_DECAY ** weeks_back
    out.loc[out["season"] == config.PRIOR_SEASON, "w"] = config.PRIOR_SEASON_WEIGHT
    return out[out["w"] > 0].copy()


def has_current_season_data(df: pd.DataFrame) -> bool:
    """True once real current-season plays exist (drives the 'live' banner)."""
    if df.empty or "season" not in df.columns:
        return False
    return bool((df["season"] == config.CURRENT_SEASON).any())
