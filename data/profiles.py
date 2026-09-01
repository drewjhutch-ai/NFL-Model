"""Team 'scouting report' logic: strengths, struggles, and play identity.

Turns the pile of per-facet ranks into a human read — a broad headline plus the
ultra-specific chink in the armor ("strong vs the run, but can't cover
pass-catching backs — 30th"). Everything here is derived from ranks already
computed elsewhere; this module only decides what's notable and how to say it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import labels


def _ordinal(n) -> str:
    if n is None or pd.isna(n):
        return "—"
    n = int(n)
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _f(unit: str, detail: str, rank) -> dict | None:
    if rank is None or pd.isna(rank):
        return None
    return {"unit": unit, "detail": detail, "rank": int(rank)}


def _get(df, team, col):
    if df is None or getattr(df, "empty", True) or team not in df.index or col not in df.columns:
        return None
    return df.loc[team, col]


def offense_facets(team: str, off: pd.DataFrame, extras: dict) -> list[dict]:
    """Every notable offensive facet for a team, each with a 1-32 rank."""
    o = off.loc[team]
    facets = [
        _f("Passing", "passing efficiency (EPA/play)", o.get("pass_epa_rank")),
        _f("Rushing", "rushing efficiency (EPA/play)", o.get("rush_epa_rank")),
        _f("Explosiveness", "explosive-play rate", o.get("explosive_rate_rank")),
        _f("Passing", "pass success rate", o.get("pass_sr_rank")),
        _f("Rushing", "rush success rate", o.get("rush_sr_rank")),
        _f("Rushing", "yards over expected per carry", _get(extras.get("rush"), team, "ryoe_rank")),
        _f("Pass protection", "sacks allowed rate", _get(extras.get("protection"), team, "protection_rank")),
        _f("vs Blitz", "efficiency when blitzed", _get(extras.get("ovb"), team, "vs_blitz_rank")),
    ]
    return [dict(f, side="offense") for f in facets if f]


def defense_facets(team: str, deff: pd.DataFrame, extras: dict) -> list[dict]:
    """Every notable defensive facet for a team, each with a 1-32 rank."""
    d = deff.loc[team]
    dvp = extras.get("dvp") or {}
    wr_def = extras.get("wr_def") or {}
    facets = [
        _f("Pass defense", "pass EPA allowed", d.get("pass_epa_rank")),
        _f("Run defense", "rush EPA allowed", d.get("rush_epa_rank")),
        _f("Explosive prevention", "explosive plays allowed", d.get("explosive_rate_rank")),
        _f("Pass rush", "pressure rate", _get(extras.get("pressure"), team, "pressure_rate_rank")),
        _f("Pass rush", "sack rate", _get(extras.get("pressure"), team, "sack_rate_rank")),
        _f("Coverage", "covering pass-catching RBs", _get(dvp.get("RB"), team, "def_rank")),
        _f("Coverage", "covering WRs", _get(dvp.get("WR"), team, "def_rank")),
        _f("Coverage", "covering TEs", _get(dvp.get("TE"), team, "def_rank")),
        _f("Coverage", "covering the slot / WR3", _get(wr_def.get(3), team, "def_rank")),
    ]
    return [dict(f, side="defense") for f in facets if f]


def strengths_and_struggles(facets: list[dict], n: int = 3
                            ) -> tuple[list[dict], list[dict]]:
    """Pick the n best facets (strengths) and n worst (struggles)."""
    valid = [f for f in facets if f["rank"] is not None]
    strengths = sorted([f for f in valid if f["rank"] <= 12], key=lambda f: f["rank"])[:n]
    struggles = sorted([f for f in valid if f["rank"] >= 21], key=lambda f: -f["rank"])[:n]
    return strengths, struggles


def facet_line(f: dict) -> str:
    """'**Coverage** — covering pass-catching RBs (30th)'."""
    return f"**{f['unit']}** — {f['detail']} ({_ordinal(f['rank'])})"


def team_grade(rank, total: int = 32) -> str:
    """A letter grade from a 1..total rank (A+ elite → F bottom)."""
    if rank is None or pd.isna(rank):
        return "—"
    pct = 1 - (int(rank) - 1) / max(total - 1, 1)  # 1.0 best → 0 worst
    bands = [(0.97, "A+"), (0.90, "A"), (0.83, "A-"), (0.75, "B+"), (0.66, "B"),
             (0.57, "B-"), (0.48, "C+"), (0.40, "C"), (0.31, "C-"), (0.22, "D+"),
             (0.12, "D"), (0.0, "F")]
    for cutoff, letter in bands:
        if pct >= cutoff:
            return letter
    return "F"


def team_thesis(team: str, off: pd.DataFrame, deff: pd.DataFrame, extras: dict) -> str:
    """One-line identity read: how they win, and where they break."""
    facets = offense_facets(team, off, extras) + defense_facets(team, deff, extras)
    s, w = strengths_and_struggles(facets, n=1)
    ident = pass_identity(team, off)["base"] if team in off.index else ""
    lead = f"{ident} offense" if ident and ident != "—" else "Balanced attack"
    if s:
        core = f"{lead} that leans on {s[0]['detail']} ({_ordinal(s[0]['rank'])})"
    else:
        core = f"{lead} with no standout unit"
    if w:
        # be specific + side-aware: a defensive hole is "exploitable"; an
        # offensive one is a "struggle" — and always name the exact metric.
        verb = "exploitable in" if w[0].get("side") == "defense" else "struggles with"
        weak = f"{verb} {w[0]['detail']} ({_ordinal(w[0]['rank'])})"
    else:
        weak = "few clear holes"
    return f"{core}; {weak}."


# --- analytical pass identity ------------------------------------------------
def pass_identity(team: str, off: pd.DataFrame) -> dict:
    """A nuanced read on how a team chooses to attack, not a 3-way bucket.

    Combines *neutral* pass rate (what they do when game script isn't forcing
    their hand) with PROE (pass rate over expectation) and where both rank.
    """
    o = off.loc[team]
    npr = o.get("neutral_pass_rate")
    proe = o.get("proe")
    pass_rate = o.get("pass_rate")

    # percentile of neutral pass rate across the league (100 = most pass-happy)
    series = off["neutral_pass_rate"].dropna()
    npr_pct = float((series < npr).mean() * 100) if pd.notna(npr) and len(series) else np.nan

    # Relative label: where this team sits in the league's pass-rate distribution,
    # so it recalibrates as the NFL trends run- or pass-heavier.
    base = labels.band_from_pct(npr_pct, labels.STYLE_BANDS) if pd.notna(npr_pct) else "—"
    return {
        "neutral_pass_rate": npr,
        "proe": proe,
        "pass_rate": pass_rate,
        "npr_pct": npr_pct,
        "base": base,
        "tendency": _proe_label(proe),
    }


def _proe_label(proe) -> str:
    if proe is None or pd.isna(proe):
        return ""
    if proe >= 3:
        return "throws more than game situations call for — pass-first by design"
    if proe >= 1:
        return "slightly more aggressive than expected"
    if proe <= -3:
        return "runs more than expected — run-committed even when passing is optimal"
    if proe <= -1:
        return "slightly more run-committed than expected"
    return "close to what game situations dictate"
