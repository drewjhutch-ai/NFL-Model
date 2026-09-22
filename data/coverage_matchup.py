"""WR–CB matchups by name — who's the WR1 / slot, and the corner across from him.

Depth charts carry alignment — LWR/RWR (outside) vs SWR (slot) for receivers,
LCB/RCB (outside) vs NCB (nickel/slot) for corners — plus a depth order, and
rosters carry every player's name. So we can name a team's top outside receivers
and its slot man, the opponent's outside corners and nickel, and pair them by
alignment.

This is an ALIGNMENT projection, not a true shadow assignment: most defenses play
sides (the left corner stays left), so outside-vs-outside is the honest default;
knowing that a specific corner *travels* with a specific receiver needs charting
data we don't have for free. Coverage QUALITY comes from the defense's existing
vs-Outside / vs-Slot ranks (Sharp), so the pairing carries a real edge read, not
just names.
"""
from __future__ import annotations

import pandas as pd

# depth-chart alignment codes → slot vs outside
_WR_SLOT = {"SWR", "SLWR", "NWR", "SL"}
_WR_OUT = {"LWR", "RWR", "SPLIT", "X", "Z", "FL", "SE", "WR"}
_CB_SLOT = {"NCB", "NB", "SCB", "NICKEL", "NICK", "SLCB"}


def _name(names: dict, pid) -> str:
    return (names.get(str(pid)) if names else None) or "?"


def _wr_align(pos: str, rank: int) -> str:
    p = str(pos).upper()
    if p in _WR_SLOT:
        return "slot"
    if p in _WR_OUT and p != "WR":
        return "outside"
    return "slot" if (rank and rank >= 3) else "outside"   # plain WR: WR3+ ≈ slot


def _cb_align(pos: str, rank: int) -> str:
    p = str(pos).upper()
    if p in _CB_SLOT:
        return "slot"
    return "slot" if (rank and rank >= 3) else "outside"   # CB3/nickel ≈ slot


def _rank_of(r) -> int:
    v = getattr(r, "depth_rank", None)
    return int(v) if pd.notna(v) else 9


def _receivers(depth: pd.DataFrame, team: str, names: dict) -> list[dict]:
    if depth is None or getattr(depth, "empty", True):
        return []
    up = depth["pos"].astype(str).str.upper()
    d = depth[(depth["team"] == team) & up.str.contains("WR")]
    rows = [{"name": _name(names, r.player_id), "rank": _rank_of(r),
             "align": _wr_align(r.pos, _rank_of(r))} for r in d.itertuples()]
    rows.sort(key=lambda x: x["rank"])
    return rows


def _corners(depth: pd.DataFrame, team: str, names: dict) -> list[dict]:
    if depth is None or getattr(depth, "empty", True):
        return []
    up = depth["pos"].astype(str).str.upper()
    mask = (depth["team"] == team) & (up.str.contains("CB") | up.isin(_CB_SLOT))
    d = depth[mask]
    rows = [{"name": _name(names, r.player_id), "rank": _rank_of(r),
             "align": _cb_align(r.pos, _rank_of(r))} for r in d.itertuples()]
    rows.sort(key=lambda x: x["rank"])
    return rows


def _cov_rank(extras: dict, def_team: str, kind: str):
    """Defense's coverage rank vs Outside / Slot (1 = stingiest, 32 = softest)."""
    from data import sharp_value as sv
    cbp = sv.coverage_by_position(extras.get("sharp") or {})
    col = f"ypt_{kind}_rank"
    if not cbp.empty and def_team in cbp.index and col in cbp.columns and pd.notna(cbp.loc[def_team, col]):
        return int(cbp.loc[def_team, col])
    return None


def matchups(off_team: str, def_team: str, extras: dict) -> list[dict]:
    """Projected WR–CB pairings for one offense vs one defense (by alignment).

    Rows: {wr, wr_role, align, cb, cov_rank}. cov_rank is the defense's rank vs
    that alignment (high = soft = good for the receiver). Empty if depth data is
    missing for either side.
    """
    depth = extras.get("depth")
    names = extras.get("player_names") or {}
    wrs = _receivers(depth, off_team, names)
    cbs = _corners(depth, def_team, names)
    if not wrs or not cbs:
        return []
    out_wr = [w for w in wrs if w["align"] == "outside"]
    slot_wr = [w for w in wrs if w["align"] == "slot"]
    out_cb = [c for c in cbs if c["align"] == "outside"] or cbs
    slot_cb = [c for c in cbs if c["align"] == "slot"]

    rows: list[dict] = []
    for i, w in enumerate(out_wr[:2]):
        c = out_cb[i] if i < len(out_cb) else (out_cb[-1] if out_cb else None)
        rows.append({"wr": w["name"], "wr_role": f"WR{i + 1} (outside)", "align": "Outside",
                     "cb": c["name"] if c else "—", "cov_rank": _cov_rank(extras, def_team, "Outside")})
    if slot_wr:
        c = slot_cb[0] if slot_cb else None
        rows.append({"wr": slot_wr[0]["name"], "wr_role": "Slot WR", "align": "Slot",
                     "cb": c["name"] if c else "(nickel n/a)", "cov_rank": _cov_rank(extras, def_team, "Slot")})
    return rows
