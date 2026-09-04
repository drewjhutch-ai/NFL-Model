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
# The prop-engine stat key each position's mismatch maps to (for a consistent lean).
_STAT_KEY = {"WR": "Rec yds", "TE": "Rec yds", "RB": "Rec"}


def _top_target_row(stats, team: str, pos: str):
    """The lead pass-catcher at a position: most-targeted, depth chart breaking ties.

    Ranking by volume then depth_rank means a proven target wins in-season, but a
    depth-chart WR1 with no snaps yet (new signing / week 1) still surfaces.
    """
    if stats is None or getattr(stats, "empty", True):
        return None
    t = stats[(stats["team"] == team) & (stats["pos"] == pos)]
    if t.empty or "targets" not in t.columns:
        return None
    t = t.copy()
    t["_tgt"] = t["targets"].fillna(0)
    t["_dr"] = pd.to_numeric(t["depth_rank"], errors="coerce").fillna(9) if "depth_rank" in t.columns else 9
    t = t.sort_values(["_tgt", "_dr"], ascending=[False, True])
    return t.iloc[0]


def _lean(row, opp, deff, extras, script, cov, pos):
    """Model side/line/projection for a player's receiving prop — the SAME math the
    prop board uses, so the mismatch card and the prop table never disagree.

    Returns (side, line, proj, hit%) or (None, None, None, None) if not projectable.
    """
    if row is None:
        return None, None, None, None
    from data import props
    stat_key = _STAT_KEY.get(pos)
    raw = props._RAW.get(stat_key)
    try:
        proj = props.project_player(row, opp, deff, extras.get("dvp", {}), script=script, cov=cov)
    except Exception:  # noqa: BLE001
        return None, None, None, None
    mean = proj.get(stat_key)
    base = row.get(raw) if raw else None
    if mean is None or base is None or pd.isna(mean) or pd.isna(base) or float(base) <= 0:
        return None, None, None, None
    p_over = props.over_prob(float(mean), float(base), stat_key)
    if pd.isna(p_over):
        return None, None, None, None
    side = "Over" if p_over >= 0.5 else "Under"
    hit = p_over if side == "Over" else 1 - p_over
    return side, round(float(base), 1), round(float(mean), 1), round(hit * 100)


def game_mismatches(away: str, home: str, off, deff, extras: dict) -> list[dict]:
    """Ranked receiving mismatches for a game (both offenses). Empty if no data."""
    usage = extras.get("usage")
    dvp = extras.get("dvp") or {}
    stats = extras.get("players")
    from data import sharp_value as sv
    from data import betting as _bet
    cbp = sv.coverage_by_position(extras.get("sharp") or {})
    if usage is None or getattr(usage, "empty", True):
        return []
    # game script (home margin) — same signature the prop board uses so the
    # projection (and therefore the Over/Under lean) is identical, not merely close
    margin = _bet.project_margin(off, deff, home, away, extras.get("st_ppg"),
                                 extras.get("qb_value"))

    out: list[dict] = []
    for o, d in ((away, home), (home, away)):
        if o not in usage.index:
            continue
        is_home = (o == home)
        script = 0.0 if pd.isna(margin) else float(margin if is_home else -margin)
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
            row = _top_target_row(stats, o, pos)
            side, line, proj, hit = _lean(row, d, deff, extras, script, cov=cbp, pos=pos)
            out.append({
                "off": o, "def": d, "pos": pos,
                "player": row.get("name") if row is not None else None,
                "role": (row.get("role") or "") if row is not None else "",
                "share": float(share), "share_rank": int(sr),
                "cov_rank": round(cov_rank, 1),
                "epa_tgt": float(epa) if pd.notna(epa) else None,
                "stat": _STAT[pos], "score": round(score, 4),
                # projection-based lean + the line it's against (matches the prop board)
                "side": side, "line": line, "proj": proj, "hit": hit,
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
