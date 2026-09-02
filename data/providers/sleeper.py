"""Sleeper player universe — one fetch, two derived feeds (rosters + injuries).

Sleeper's public player endpoint (no key, reachable from datacenters) is the
authoritative *current* state for every NFL player: what team they're on right
now and their status. Play-by-play and season stats lag reality — a player shows
on the team he last took a snap for, so trades, signings, and cuts are invisible
until he plays again. This module makes the current roster a first-class input.

    https://api.sleeper.app/v1/players/nfl   (~5 MB, all players)

The payload is large, so we fetch it once and memoize it briefly at module level
so a single pipeline build (rosters + injuries) costs one HTTP round-trip, not
two. Both derived views key on ``gsis_id`` so they join cleanly onto nflverse
player ids used everywhere else in the model.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from data.teams import normalize_team

_URL = "https://api.sleeper.app/v1/players/nfl"
_HEADERS = {"User-Agent": "nfl-model/1.0", "Accept": "application/json"}
_MEMO: dict = {"ts": 0.0, "data": None}
_MEMO_TTL = 1800   # seconds — dedupe the 5 MB pull within one build / short window

LAST_ERROR: str = ""

_INJURY_NORM = {
    "ir": "IR", "injured reserve": "IR",
    "pup": "PUP", "physically unable to perform": "PUP",
    "sus": "Suspended", "suspended": "Suspended", "suspension": "Suspended",
    "out": "Out", "doubtful": "Doubtful", "questionable": "Questionable",
    "dtd": "Day-To-Day", "day-to-day": "Day-To-Day",
}


def last_error() -> str:
    return LAST_ERROR


def player_universe(timeout: int = 25, force: bool = False) -> dict:
    """The raw Sleeper player dict, memoized briefly. Empty dict on failure."""
    global LAST_ERROR
    now = time.time()
    if not force and _MEMO["data"] is not None and (now - _MEMO["ts"]) < _MEMO_TTL:
        return _MEMO["data"]
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as exc:  # noqa: BLE001
        LAST_ERROR = f"{type(exc).__name__}: {str(exc)[:160]}"
        return {}
    LAST_ERROR = "" if data else "reachable, but the player list was empty"
    _MEMO.update({"ts": now, "data": data})
    return data


def current_rosters(timeout: int = 25) -> pd.DataFrame:
    """Current team + position for every active player, keyed by gsis_id.

    Columns: player_id (gsis), name, team, pos, number, status. Only players
    currently on a team are kept (free agents dropped). Empty on failure.
    """
    data = player_universe(timeout=timeout)
    if not data:
        return pd.DataFrame()
    rows = []
    for _pid, p in data.items():
        if not isinstance(p, dict):
            continue
        team = normalize_team(p.get("team")) if p.get("team") else None
        if not team:
            continue   # free agent / not currently rostered
        gsis = p.get("gsis_id")
        name = (p.get("full_name")
                or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
                or "?")
        rows.append({
            "player_id": gsis,
            "name": name,
            "team": team,
            "pos": (p.get("position") or "").upper(),
            "number": p.get("number"),
            "status": p.get("status") or "",
        })
    df = pd.DataFrame(rows)
    return df


def injuries_by_team(timeout: int = 25) -> dict[str, pd.DataFrame]:
    """Current injury designations grouped by team (IR/PUP/susp./Out/etc.).

    Same tidy shape the ESPN provider returns (team, name, pos, espn_status,
    detail, updated) so the injuries UI is source-agnostic.
    """
    data = player_universe(timeout=timeout)
    if not data:
        return {}
    rows = []
    for _pid, p in data.items():
        if not isinstance(p, dict):
            continue
        status = _INJURY_NORM.get((p.get("injury_status") or "").strip().lower())
        if status is None:
            continue
        team = normalize_team(p.get("team")) if p.get("team") else None
        if not team:
            continue
        name = (p.get("full_name")
                or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
                or "?")
        rows.append({
            "team": team, "name": name, "pos": (p.get("position") or "").upper(),
            "espn_status": status, "detail": (p.get("injury_body_part") or "").strip(),
            "updated": p.get("injury_start_date") or "",
        })
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    return {team: g.reset_index(drop=True) for team, g in df.groupby("team")}
