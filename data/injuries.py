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
STATUS_ICON = {"Out": "🔴", "Doubtful": "🟠", "Questionable": "🟡"}
STATUS_ORDER = {"Out": 0, "Doubtful": 1, "Questionable": 2}


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
            "side": "offense" if off_pct >= def_pct else "defense",
            "pct": pct,
        })
    for team in out:
        out[team].sort(key=lambda p: (STATUS_ORDER.get(p["status"], 9), -p["pct"]))
    return dict(out), latest


def summary_line(items: list[dict], limit: int = 4) -> str:
    """Compact one-liner: '🔴 Mahomes (QB) · 🟠 Kelce (TE)'."""
    if not items:
        return "✅ No major injuries"
    parts = [f"{STATUS_ICON.get(p['status'], '•')} {p['name']} ({p['pos']})"
             for p in items[:limit]]
    more = f" +{len(items) - limit} more" if len(items) > limit else ""
    return " · ".join(parts) + more
