"""Positional matchup analysis: which offensive weapons face which soft spots.

This is what turns "Team A vs Team B" into something you can actually bet on:
does a team that *features* its pass-catching backs draw a defense that *can't
cover* backs? We build two things from free play-by-play + roster positions:

* **defense_vs_position** — how much each defense allows to RB / WR / TE targets
  (EPA and yards per target), ranked league-wide. A high rank = soft spot.
* **offense_usage** — how heavily each offense funnels targets to each position,
  ranked. High RB target share = a receiving-back offense, etc.

``matchup_table`` crosses one team's usage against the other's soft spots and
flags the edges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POSITIONS = ("RB", "WR", "TE")


def _wmean(g: pd.DataFrame, value: str) -> float:
    v, w = g[value], g["w"]
    mask = v.notna() & w.notna()
    denom = w[mask].sum()
    return float((v[mask] * w[mask]).sum() / denom) if denom else np.nan


def _targets(pbp_weighted: pd.DataFrame, posmap: dict[str, str]) -> pd.DataFrame:
    """Pass plays with a resolved receiver position (RB/WR/TE)."""
    if pbp_weighted.empty or "receiver_player_id" not in pbp_weighted.columns:
        return pd.DataFrame()
    pp = pbp_weighted[(pbp_weighted["pass"] == 1)
                      & pbp_weighted["receiver_player_id"].notna()].copy()
    if pp.empty:
        return pp
    pp["pos"] = pp["receiver_player_id"].map(posmap)
    return pp[pp["pos"].isin(POSITIONS)].copy()


def defense_vs_position(pbp_weighted: pd.DataFrame, posmap: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Per-position frames: how much each defense allows to that receiver type.

    Rank 1 = stingiest defense vs that position; a high rank = a soft spot.
    """
    pp = _targets(pbp_weighted, posmap)
    out: dict[str, pd.DataFrame] = {}
    if pp.empty:
        return out
    if "complete_pass" in pp.columns:
        pp["_c"] = pp["complete_pass"].fillna(0).astype(float)
    else:
        pp["_c"] = 0.0
    for pos in POSITIONS:
        sub = pp[pp["pos"] == pos]
        rows = []
        for team, g in sub.groupby("defteam"):
            rows.append({
                "team": team,
                "targets": float(g["w"].sum()),
                "epa_per_tgt": _wmean(g, "epa"),
                "yards_per_tgt": _wmean(g, "yards_gained"),
                "catch_rate": _wmean(g, "_c"),
            })
        df = pd.DataFrame(rows).set_index("team")
        if not df.empty:
            df["def_rank"] = df["epa_per_tgt"].rank(ascending=True, method="min").astype("Int64")
        out[pos] = df
    return out


def offense_usage(pbp_weighted: pd.DataFrame, posmap: dict[str, str]) -> pd.DataFrame:
    """Per-offense target share & receiving efficiency by position, with ranks."""
    pp = _targets(pbp_weighted, posmap)
    if pp.empty:
        return pd.DataFrame()
    rows = []
    for team, g in pp.groupby("posteam"):
        total = g["w"].sum()
        row = {"team": team, "total_targets": float(total)}
        for pos in POSITIONS:
            gp = g[g["pos"] == pos]
            row[f"{pos}_tgt_share"] = float(gp["w"].sum() / total) if total else np.nan
            row[f"{pos}_epa_tgt"] = _wmean(gp, "epa") if not gp.empty else np.nan
        rows.append(row)
    df = pd.DataFrame(rows).set_index("team")
    for pos in POSITIONS:
        # rank 1 = most target share funneled to that position
        df[f"{pos}_share_rank"] = df[f"{pos}_tgt_share"].rank(ascending=False, method="min").astype("Int64")
    return df


def _edge(share_rank, def_rank) -> tuple[str, int]:
    """Cross offense usage rank vs defense stinginess rank (both 1 = extreme)."""
    if pd.isna(share_rank) or pd.isna(def_rank):
        return "—", 0
    featured = int(share_rank) <= 12          # top-12 usage at this position
    soft = int(def_rank) >= 21                # bottom-12 defense vs this position
    stout = int(def_rank) <= 11               # top-11 defense vs this position
    # magnitude: how featured + how soft
    mag = (33 - int(share_rank)) + (int(def_rank) - 16)
    if featured and soft:
        return "🟢 Strong edge", mag
    if soft:
        return "🟢 Lean edge", mag
    if featured and stout:
        return "🔴 Tough spot", mag
    if stout:
        return "🔴 Lean tough", mag
    return "🟡 Neutral", mag


def _rec_role(share_rank) -> str:
    if pd.isna(share_rank):
        return ""
    r = int(share_rank)
    if r <= 5:
        return " (heavily featured)"
    if r <= 12:
        return " (featured)"
    return ""


def matchup_table(off_team: str, def_team: str, usage: pd.DataFrame,
                  dvp: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One direction: off_team's weapons vs def_team's coverage by position."""
    if usage.empty or not dvp or off_team not in usage.index:
        return pd.DataFrame()
    u = usage.loc[off_team]
    rows = []
    for pos in POSITIONS:
        share_rank = u.get(f"{pos}_share_rank")
        share = u.get(f"{pos}_tgt_share")
        dfp = dvp.get(pos)
        if dfp is None or def_team not in dfp.index:
            def_rank = pd.NA
            allowed = np.nan
        else:
            def_rank = dfp.loc[def_team, "def_rank"]
            allowed = dfp.loc[def_team, "epa_per_tgt"]
        label, mag = _edge(share_rank, def_rank)
        # "allows Kth-most" -> flip stinginess rank (1=stingiest) to allowed-rank
        allows_rank = (33 - int(def_rank)) if pd.notna(def_rank) else None
        rows.append({
            "Position": pos + _rec_role(share_rank),
            f"{off_team} target share": f"{share * 100:.0f}%" if pd.notna(share) else "—",
            f"{def_team} allows": (f"{allows_rank}{_ord_suffix(allows_rank)}-most EPA/tgt"
                                   if allows_rank else "—"),
            "Edge": label,
            "_mag": mag,
        })
    return pd.DataFrame(rows)


def _ord_suffix(n) -> str:
    if n is None:
        return ""
    n = int(n)
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
