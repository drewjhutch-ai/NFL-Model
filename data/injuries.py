"""Major-injury tracking for the current week.

Cross-references the weekly injury report against snap share so only players who
actually matter get flagged — a starter or heavy-rotation piece (≥ the config
snap threshold on offense or defense), not a 4th-string special-teamer.

Everything is derived from free nflverse data (injury reports + snap counts),
linked via the roster's gsis_id ↔ pfr_id crosswalk. In the offseason there are
no reports, so this returns empty and the UI says so.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

import config
from data.teams import normalize_team

_STATUSES = ("Out", "Doubtful", "Questionable")
STATUS_ICON = {"Out": "OUT", "Doubtful": "DBT", "Questionable": "Q",
               "IR": "IR", "PUP": "PUP", "Suspended": "SUS"}
STATUS_ORDER = {"Out": 0, "IR": 0, "PUP": 0, "Suspended": 1, "Doubtful": 1, "Questionable": 2}

# Season-long / definite-absence statuses that come from the year-round feed
# (Sleeper/ESPN) rather than the weekly game report.
_FEED_ABSENT = ("IR", "PUP", "Suspended", "Out", "Doubtful")


def _role_pct(players_df, team: str, name: str) -> float:
    """Estimate a player's role (snap-share proxy) from the usage frame.

    A feed absence (e.g. a WR on IR) carries no snap count, so we approximate the
    player's importance from their share of the team's touches. Unknown names are
    treated as depth so they barely move the number.
    """
    if players_df is None or getattr(players_df, "empty", True):
        return 0.4
    t = players_df[players_df.get("team") == team]
    if t.empty:
        return 0.4
    touches = t["targets"].fillna(0) + t["carries"].fillna(0)
    mx = float(touches.max()) or 1.0
    row = t[t["name"].str.lower() == (name or "").lower()]
    if row.empty:
        return 0.35
    v = float((row["targets"].fillna(0) + row["carries"].fillna(0)).iloc[0])
    return max(0.3, min(0.95, v / mx * 0.9))


def merge_feed(inj_map: dict, feed_by_team: dict, players_df=None) -> dict:
    """Fold year-round feed absences (IR/PUP/susp./Out/Doubtful) into the weekly map.

    The weekly game report is in-season only and never lists IR/PUP, so a
    difference-maker on injured reserve would otherwise be invisible to the
    projection all year. This adds those absences — valued by role from usage —
    so they dock the team's strength across every betting tab. The weekly report
    wins on any name it already carries (it has real snap share + practice signal).
    """
    out = {t: list(v) for t, v in (inj_map or {}).items()}
    if not feed_by_team:
        return out
    for team, g in feed_by_team.items():
        if g is None or getattr(g, "empty", True):
            continue
        known = {p["name"].lower() for p in out.get(team, [])}
        for r in g.itertuples():
            status = getattr(r, "espn_status", "")
            if status not in _FEED_ABSENT:
                continue
            nm = getattr(r, "name", "")
            if not nm or nm.lower() in known:
                continue
            out.setdefault(team, []).append({
                "gsis": None, "name": nm, "pos": getattr(r, "pos", ""),
                "status": status, "injury": getattr(r, "detail", "") or "",
                "practice": "", "pct": _role_pct(players_df, team, nm),
                "source": "feed", "season_long": status in ("IR", "PUP", "Suspended"),
                "lingering": False,
            })
    for team in out:
        out[team].sort(key=lambda p: (STATUS_ORDER.get(p["status"], 9), -float(p.get("pct") or 0)))
    return out

# Practice participation is the tell behind a game-status designation — a
# Questionable who DNP'd all week trends toward out; one who practiced Full
# usually plays. Short labels + a read used by the Injuries tab.
_PRACTICE_SHORT = {
    "Did Not Participate In Practice": "DNP",
    "Limited Participation in Practice": "LP",
    "Full Participation in Practice": "FP",
}


def practice_short(practice: str) -> str:
    return _PRACTICE_SHORT.get((practice or "").strip(), "")


def practice_read(practice: str, status: str) -> tuple[str, str]:
    """(‘lean’, tone) from practice participation + game status.

    tone ∈ {"bad","warn","good","flat"} drives the tab's color coding.
    """
    p = practice_short(practice)
    s = (status or "").strip()
    if s == "Out":
        return ("Ruled out", "bad")
    if s == "Doubtful":
        return ("Unlikely to play", "bad")
    # Questionable (or unlisted game status) — practice is the signal
    if p == "DNP":
        return ("Trending out — DNP all week", "bad")
    if p == "LP":
        return ("Managing it — limited", "warn")
    if p == "FP":
        return ("Likely plays — full practice", "good")
    return ("Watch the report", "flat")


def is_watch(item: dict) -> bool:
    """A heavy-snap Questionable whose availability swings the projection."""
    return (item.get("status") == "Questionable"
            and float(item.get("pct") or 0) >= 0.55)


def _snap_share(snaps: pd.DataFrame) -> dict[str, dict]:
    """pfr_player_id -> {off, def} average snap share (latest season present)."""
    if snaps.empty or "pfr_player_id" not in snaps.columns:
        return {}
    g = (snaps.groupby(["pfr_player_id", "season"])
         .agg(off=("offense_pct", "mean"), dff=("defense_pct", "mean"))
         .reset_index()
         .sort_values("season")
         .groupby("pfr_player_id").tail(1))
    return {r.pfr_player_id: {"off": r.off, "def": r.dff} for r in g.itertuples()}


def build(inj: pd.DataFrame, snaps: pd.DataFrame, rosters: pd.DataFrame,
          season: int, threshold: float | None = None) -> tuple[dict, int | None]:
    """Return ({team -> [injury dicts]}, week) for the latest reported week."""
    threshold = config.INJURY_SNAP_THRESHOLD if threshold is None else threshold
    if inj.empty or "season" not in inj.columns:
        return {}, None
    inj = inj[inj["season"] == season]
    if inj.empty:
        return {}, None
    latest = int(inj["week"].max())
    cur = inj[(inj["week"] == latest) & inj["report_status"].isin(_STATUSES)]
    if cur.empty:
        return {}, latest

    x = {}
    if not rosters.empty and "player_id" in rosters.columns and "pfr_id" in rosters.columns:
        x = dict(zip(rosters["player_id"], rosters["pfr_id"]))
    share = _snap_share(snaps)

    out: dict[str, list] = defaultdict(list)
    for row in cur.itertuples():
        pfr = x.get(getattr(row, "gsis_id", None))
        sh = share.get(pfr) if pfr else None
        if not sh:
            continue
        off_pct = sh["off"] if pd.notna(sh["off"]) else 0.0
        def_pct = sh["def"] if pd.notna(sh["def"]) else 0.0
        pct = max(off_pct, def_pct)
        if pct < threshold:
            continue
        team = normalize_team(getattr(row, "team", None))
        if not team:
            continue
        out[team].append({
            "gsis": getattr(row, "gsis_id", None),
            "name": getattr(row, "full_name", "?"),
            "pos": getattr(row, "position", ""),
            "status": row.report_status,
            "injury": getattr(row, "report_primary_injury", "") or "",
            "practice": getattr(row, "practice_status", "") or "",
            "side": "offense" if off_pct >= def_pct else "defense",
            "pct": pct,
        })
    for team in out:
        out[team].sort(key=lambda p: (STATUS_ORDER.get(p["status"], 9), -p["pct"]))
    return dict(out), latest


def summary_line(items: list[dict], limit: int = 4) -> str:
    """Compact one-liner: 'Mahomes (QB) · Kelce (TE)'."""
    if not items:
        return "No major injuries"
    parts = [f"{STATUS_ICON.get(p['status'], '•')} {p['name']} ({p['pos']})"
             for p in items[:limit]]
    more = f" +{len(items) - limit} more" if len(items) > limit else ""
    return " · ".join(parts) + more
