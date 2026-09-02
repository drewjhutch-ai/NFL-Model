"""Points-of-interest finder — sift a game for exploitable receiving mismatches.

The bet engine prices markets; this layer answers the scout's question the engine
leaves implicit: *where does a heavily-used weapon meet a soft coverage?* It
pairs each offense's target share by position with the opponent defense's
coverage weakness (Sharp YPT-allowed rank blended with nflverse defense-vs-
position), names the top target, and scores the edge — so a read like "NE leans
on TEs, Seattle is soft vs TEs → target the TE receiving prop" surfaces as a
candidate bet instead of hiding in the projection.
"""
from __future__ import annotations

import pandas as pd

# Position value weight (volume/《price》 of the receiving market).
_POS_VAL = {"WR": 1.0, "TE": 0.9, "RB": 0.6}
_STAT = {"WR": "receiving yards", "TE": "receiving yards", "RB": "receptions"}


def _top_target(stats, team: str, pos: str) -> str | None:
    if stats is None or getattr(stats, "empty", True):
        return None
    t = stats[(stats["team"] == team) & (stats["pos"] == pos)]
    if t.empty or "targets" not in t.columns:
        return None
    t = t.sort_values("targets", ascending=False)
    return t.iloc[0].get("name")


def game_mismatches(away: str, home: str, off, deff, extras: dict) -> list[dict]:
    """Ranked receiving mismatches for a game (both offenses). Empty if no data."""
    usage = extras.get("usage")
    dvp = extras.get("dvp") or {}
    stats = extras.get("players")
    from data import sharp_value as sv
    cbp = sv.coverage_by_position(extras.get("sharp") or {})
    if usage is None or getattr(usage, "empty", True):
        return []

    out: list[dict] = []
    for o, d in ((away, home), (home, away)):
        if o not in usage.index:
            continue
        u = usage.loc[o]
        for pos in ("WR", "TE", "RB"):
            share = u.get(f"{pos}_tgt_share")
            sr = u.get(f"{pos}_share_rank")
            epa = u.get(f"{pos}_epa_tgt")
            if pd.isna(share) or pd.isna(sr):
                continue
            usage_strength = (33 - float(sr)) / 32.0        # 1 = most-targeted at pos
            # opponent softness: blend Sharp YPT-allowed rank + nflverse dvp rank
            ranks = []
            col = f"ypt_{pos}_rank"
            if not cbp.empty and d in cbp.index and col in cbp.columns and pd.notna(cbp.loc[d, col]):
                ranks.append(float(cbp.loc[d, col]))
            dfp = dvp.get(pos)
            if dfp is not None and d in dfp.index and "def_rank" in dfp.columns and pd.notna(dfp.loc[d, "def_rank"]):
                ranks.append(float(dfp.loc[d, "def_rank"]))
            if not ranks:
                continue
            cov_rank = sum(ranks) / len(ranks)
            softness = cov_rank / 32.0                        # 1 = softest coverage
            score = usage_strength * softness * _POS_VAL[pos]
            out.append({
                "off": o, "def": d, "pos": pos,
                "player": _top_target(stats, o, pos),
                "share": float(share), "share_rank": int(sr),
                "cov_rank": round(cov_rank, 1),
                "epa_tgt": float(epa) if pd.notna(epa) else None,
                "stat": _STAT[pos], "score": round(score, 4),
            })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def strength_label(score: float) -> str:
    if score >= 0.42:
        return "Prime"
    if score >= 0.30:
        return "Strong"
    if score >= 0.20:
        return "Live"
    return "Slight"
