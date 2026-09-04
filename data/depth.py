"""Depth-chart roles — WR1 / RB1 / TE1, the authoritative starter picture.

Target volume tells you who's been used; the depth chart tells you who the team
*intends* to use — which matters most exactly when volume is missing (a new
signing, a rookie, week 1). Pairs with the current-roster layer: the roster says
what team a player is on, the depth chart says his role on it. Feeds prop
targeting, the Players/Touchdowns role labels, and the mismatch top-target pick.
"""
from __future__ import annotations

import pandas as pd

# Granular depth-chart positions folded into the skill groups we reason about.
_GROUP = {
    "QB": "QB",
    "RB": "RB", "HB": "RB", "FB": "RB",
    "WR": "WR", "LWR": "WR", "RWR": "WR", "SWR": "WR", "SLWR": "WR",
    "TE": "TE",
}


def role_frame(depth: pd.DataFrame) -> pd.DataFrame:
    """player_id -> team, group, depth_rank, role (e.g. 'WR2'). Empty if no data."""
    if depth is None or depth.empty or "player_id" not in depth.columns:
        return pd.DataFrame()
    d = depth.copy()
    d["group"] = d["pos"].map(lambda p: _GROUP.get(str(p).upper()))
    d = d[d["group"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d["depth_rank"] = pd.to_numeric(d.get("depth_rank"), errors="coerce").fillna(9)
    rows = []
    for (team, group), g in d.groupby(["team", "group"]):
        g = g.sort_values("depth_rank", kind="stable")
        for i, (_, r) in enumerate(g.iterrows(), start=1):
            rows.append({"player_id": str(r["player_id"]), "team": team,
                         "group": group, "depth_rank": int(r["depth_rank"]),
                         "role": f"{group}{i}"})
    return pd.DataFrame(rows)


def apply_roles(players: pd.DataFrame, depth: pd.DataFrame) -> pd.DataFrame:
    """Attach `role` (WR1…) and `depth_rank` to the players frame by player_id.

    Only applies a role when the depth-chart team matches the player's current
    team, so a stale role from a prior team never leaks in.
    """
    if players is None or players.empty:
        return players
    roles = role_frame(depth)
    out = players.copy()
    if roles.empty:
        out["role"] = ""
        out["depth_rank"] = pd.NA
        return out
    rmap = {r.player_id: (r.role, r.team, r.depth_rank) for r in roles.itertuples()}
    role_col, rank_col = [], []
    teams = out["team"] if "team" in out.columns else pd.Series("", index=out.index)
    for pid, team in zip(out.index, teams):
        info = rmap.get(str(pid))
        if info and (not team or info[1] == team):
            role_col.append(info[0]); rank_col.append(info[2])
        else:
            role_col.append(""); rank_col.append(pd.NA)
    out["role"] = role_col
    out["depth_rank"] = rank_col
    return out
