"""Current-roster layer — put every player on the team he's on *today*.

The stats/pbp frames assign a player to the team he last played for, so an
offseason signing or an in-season trade is wrong until he logs a snap. This
module takes the authoritative current roster (Sleeper) and overrides the team
on the model's player frames, keyed by nflverse player_id (gsis). Because every
tab reads the same corrected ``extras['players']`` (and red-zone usage), the fix
propagates to Players, Props, Touchdowns, mismatches, and the projection.

Usage stats stay with the player — a receiver who changed teams brings his prior
production as a baseline until new games accrue, which is exactly how a sharp
would treat him week 1 on a new team.
"""
from __future__ import annotations

import pandas as pd

from data.teams import normalize_team


def team_map(roster: pd.DataFrame) -> dict:
    """player_id (gsis) -> current team, from the Sleeper roster frame."""
    if roster is None or roster.empty or "player_id" not in roster.columns:
        return {}
    r = roster.dropna(subset=["player_id"])
    r = r[r["team"].notna() & (r["team"] != "")]
    return dict(zip(r["player_id"].astype(str), r["team"]))


def name_team_map(roster: pd.DataFrame) -> dict:
    """lowercased name -> current team, a fallback when a gsis id is missing."""
    if roster is None or roster.empty or "name" not in roster.columns:
        return {}
    r = roster[roster["team"].notna() & (roster["team"] != "")]
    # keep the first team per name (Sleeper lists one current team per player)
    out = {}
    for nm, tm in zip(r["name"].astype(str), r["team"]):
        key = nm.strip().lower()
        if key and key not in out:
            out[key] = tm
    return out


# Injury statuses that make a player unavailable — no prop/pick should list them.
_OUT_STATUSES = {"Out", "IR", "PUP", "Suspended", "Doubtful"}


def mark_active(frame: pd.DataFrame, roster: pd.DataFrame, inj_map: dict) -> pd.DataFrame:
    """Add an `active` flag: on the current roster AND not ruled out.

    Two failure modes this closes: a player who has left a team but still carries
    that team's stats (roster confirms he's gone), and a player who is Out/IR/PUP/
    suspended (the injury feed says he can't play). Pick generators filter on this
    so neither can ever surface as a bet. When the roster feed is unavailable we
    don't treat everyone as departed — only the injury filter applies.
    """
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    names = out["name"].astype(str) if "name" in out.columns else pd.Series("", index=out.index)

    if roster is not None and not getattr(roster, "empty", True) and "player_id" in roster.columns:
        ids = set(roster["player_id"].dropna().astype(str))
        rnames = set(roster["name"].astype(str).str.lower()) if "name" in roster.columns else set()
        rostered = [(str(pid) in ids) or (str(nm).strip().lower() in rnames)
                    for pid, nm in zip(out.index, names)]
    else:
        rostered = [True] * len(out)   # no roster feed → don't drop anyone on that basis

    out_names = {(p.get("name") or "").strip().lower()
                 for items in (inj_map or {}).values() for p in items
                 if p.get("status") in _OUT_STATUSES}
    injured_out = [str(nm).strip().lower() in out_names for nm in names]

    out["rostered"] = rostered
    out["injured_out"] = injured_out
    out["active"] = [r and not i for r, i in zip(rostered, injured_out)]
    return out


def unavailable_names(inj_map: dict) -> set:
    """Lowercased names of players ruled out (Out/IR/PUP/suspended/doubtful)."""
    return {(p.get("name") or "").strip().lower()
            for items in (inj_map or {}).values() for p in items
            if p.get("status") in _OUT_STATUSES}


def apply_current_teams(frame: pd.DataFrame, roster: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Override each player's team with the current roster; report who moved.

    ``frame`` is indexed by player_id (gsis) and carries team/name columns (the
    players stats frame or red-zone usage). Match by id first, then by name.
    Returns (corrected_frame, moves) where moves is a list of dicts describing
    players whose team changed vs the stats-derived team.
    """
    if frame is None or frame.empty or "team" not in frame.columns:
        return frame, []
    tmap = team_map(roster)
    nmap = name_team_map(roster)
    if not tmap and not nmap:
        return frame, []
    out = frame.copy()
    moves = []
    new_teams = []
    names = out["name"] if "name" in out.columns else pd.Series("", index=out.index)
    for pid, old_team, nm in zip(out.index, out["team"], names):
        cur = tmap.get(str(pid))
        if cur is None and nm:
            cur = nmap.get(str(nm).strip().lower())
        # normalize the stats-derived team so a spelling difference (nflverse "LA"
        # vs the canonical "LAR") isn't mistaken for a trade.
        old_norm = normalize_team(old_team) if isinstance(old_team, str) and old_team else None
        if cur and old_norm and cur != old_norm:
            moves.append({"player_id": pid, "name": nm, "from": old_norm, "to": cur,
                          "pos": out.at[pid, "pos"] if "pos" in out.columns else ""})
            new_teams.append(cur)
        else:
            new_teams.append(cur or old_norm or old_team)
    out["team"] = new_teams
    return out, moves
