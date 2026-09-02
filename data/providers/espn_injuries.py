"""ESPN public injury feed — a faster, free layer on top of the official report.

ESPN publishes current injury status on a public JSON endpoint (no key, no
login):
    https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries

It updates faster than the once-weekly official game-status report and carries a
short comment ("expected to play", "week to week", etc.), so it's a good "in the
know" layer over the nflverse designations we already use. Free and public —
no credentials — but it may be blocked from some datacenter IPs, so every call
degrades gracefully to an empty frame.

Returns a tidy frame: team, name, pos, espn_status, detail, updated.
"""
from __future__ import annotations

import pandas as pd
import requests

from data.teams import normalize_team

_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
# A per-team fallback the core API exposes if the aggregate endpoint is blocked.
_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/nfl/injuries",
    "Origin": "https://www.espn.com",
}

# Last fetch diagnostic for the UI to surface ("" = ok / not yet tried).
LAST_ERROR: str = ""


def last_error() -> str:
    return LAST_ERROR

# ESPN status text -> our canonical game-status vocabulary where it maps cleanly.
_STATUS_NORM = {
    "out": "Out", "doubtful": "Doubtful", "questionable": "Questionable",
    "injured reserve": "IR", "ir": "IR", "physically unable to perform": "PUP",
    "day-to-day": "Day-To-Day", "probable": "Probable", "active": "Active",
    "suspension": "Suspended",
}


def _norm_status(raw: str) -> str:
    return _STATUS_NORM.get((raw or "").strip().lower(), (raw or "").strip())


def fetch(timeout: int = 15) -> pd.DataFrame:
    """Pull the current ESPN injury feed, normalized. Empty on any failure.

    Records LAST_ERROR so the UI can explain *why* it's empty (blocked, quota,
    parse) instead of a generic 'unreachable'.
    """
    global LAST_ERROR
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - network/parse issues degrade to empty
        LAST_ERROR = f"{type(exc).__name__}: {str(exc)[:160]}"
        return pd.DataFrame()

    rows: list[dict] = []
    for group in payload.get("injuries", []) or []:
        # team name can live at a few keys depending on ESPN's shape
        tname = (group.get("displayName") or group.get("name")
                 or (group.get("team") or {}).get("displayName")
                 or (group.get("team") or {}).get("abbreviation"))
        team = normalize_team(tname) if tname else None
        for item in group.get("injuries", []) or []:
            ath = item.get("athlete") or {}
            pos = ((ath.get("position") or {}).get("abbreviation")
                   or (ath.get("position") or {}).get("name") or "")
            status = _norm_status(item.get("status") or item.get("type", {}).get("description", ""))
            detail = (item.get("shortComment") or item.get("longComment")
                      or (item.get("details") or {}).get("type") or "")
            rows.append({
                "team": team,
                "name": ath.get("displayName") or ath.get("shortName") or "?",
                "pos": (pos or "").upper(),
                "espn_status": status,
                "detail": (detail or "").strip(),
                "updated": item.get("date") or "",
            })
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["team"]) if not df.empty else df
    LAST_ERROR = "" if not df.empty else "reachable, but the feed listed no injuries"
    return df


def by_team(timeout: int = 15) -> dict[str, pd.DataFrame]:
    """ESPN feed grouped by canonical team abbreviation (empty dict on failure)."""
    df = fetch(timeout=timeout)
    if df.empty:
        return {}
    return {team: g.reset_index(drop=True) for team, g in df.groupby("team")}


def is_available() -> bool:
    """Optimistic — it's a public endpoint; failures are handled at fetch time."""
    return True
