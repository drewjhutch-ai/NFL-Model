"""Sleeper injury feed — free, no key, year-round, and reachable from the cloud.

ESPN's public injury endpoint hard-blocks datacenter IPs (403), so it's dead on
Streamlit Cloud. Sleeper's API is built for third-party app developers, needs no
key, and returns every NFL player's current status — including the season-long
designations the weekly game report never carries: **IR, PUP, and suspensions**.

    https://api.sleeper.app/v1/players/nfl

That payload is the full player universe (~5 MB), so we pull it once, cache it,
and keep only players who actually carry an injury designation and a team.
Returns the same tidy shape as the ESPN provider so the UI is a drop-in swap:
team, name, pos, espn_status, detail, updated.
"""
from __future__ import annotations

import pandas as pd
import requests

from data.teams import normalize_team

_URL = "https://api.sleeper.app/v1/players/nfl"
_HEADERS = {"User-Agent": "nfl-model/1.0", "Accept": "application/json"}

# Sleeper's injury_status vocabulary -> our canonical statuses.
_STATUS_NORM = {
    "ir": "IR", "injured reserve": "IR",
    "pup": "PUP", "physically unable to perform": "PUP",
    "sus": "Suspended", "suspended": "Suspended", "suspension": "Suspended",
    "out": "Out", "doubtful": "Doubtful", "questionable": "Questionable",
    "dtd": "Day-To-Day", "day-to-day": "Day-To-Day",
}
# Designations worth showing / feeding the model. NA / None / "" are skipped.
_KEEP = set(_STATUS_NORM.values())

LAST_ERROR: str = ""


def last_error() -> str:
    return LAST_ERROR


def _norm_status(raw: str) -> str | None:
    return _STATUS_NORM.get((raw or "").strip().lower())


def fetch(timeout: int = 25) -> pd.DataFrame:
    """Pull the Sleeper player universe, keep the injured ones. Empty on failure."""
    global LAST_ERROR
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - network/parse issues degrade to empty
        LAST_ERROR = f"{type(exc).__name__}: {str(exc)[:160]}"
        return pd.DataFrame()

    rows: list[dict] = []
    for _pid, p in (payload or {}).items():
        if not isinstance(p, dict):
            continue
        status = _norm_status(p.get("injury_status"))
        if status is None:
            continue
        team = normalize_team(p.get("team")) if p.get("team") else None
        if not team:
            continue
        name = (p.get("full_name")
                or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
                or "?")
        rows.append({
            "team": team,
            "name": name,
            "pos": (p.get("position") or "").upper(),
            "espn_status": status,
            "detail": (p.get("injury_body_part") or "").strip(),
            "updated": p.get("injury_start_date") or "",
        })
    df = pd.DataFrame(rows)
    LAST_ERROR = "" if not df.empty else "reachable, but no injuries listed"
    return df


def by_team(timeout: int = 25) -> dict[str, pd.DataFrame]:
    """Sleeper feed grouped by canonical team abbreviation (empty dict on failure)."""
    df = fetch(timeout=timeout)
    if df.empty:
        return {}
    return {team: g.reset_index(drop=True) for team, g in df.groupby("team")}


def is_available() -> bool:
    return True
