"""Unified matchup edge engine.

One function computes every facet edge for a direction (one team's offense vs the
other's defense) on a single consistent scale: positive = offense edge, negative
= defense edge, roughly -31..+31. Everything else — the matchup chart, the
headline verdict, the Picks leans — is built on top of it, so the numbers always
agree.
"""
from __future__ import annotations

import pandas as pd


def _ord(n) -> str:
    if n is None or pd.isna(n):
        return "—"
    n = int(n)
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _mag(off_rank, def_rank):
    """Offense strong (low rank) vs defense weak (high rank) => positive edge.

    Both ranks are 1 (best) .. 32 (worst). A weak defense (high def_rank) facing
    a strong offense (low off_rank) yields a large positive edge; range -31..+31.
    """
    if pd.isna(off_rank) or pd.isna(def_rank):
        return None
    return int(def_rank) - int(off_rank)


def _get(df, team, col):
    if df is None or getattr(df, "empty", True) or team not in df.index or col not in df.columns:
        return None
    return df.loc[team, col]


def facet_edges(o_team: str, d_team: str, off: pd.DataFrame, deff: pd.DataFrame,
                extras: dict) -> list[dict]:
    """All facet edges for o_team's offense attacking d_team's defense."""
    if o_team not in off.index or d_team not in deff.index:
        return []
    o, d = off.loc[o_team], deff.loc[d_team]
    dvp = extras.get("dvp") or {}
    usage = extras.get("usage")
    off_sit = extras.get("off_sit")
    def_sit = extras.get("def_sit")

    specs = [
        ("Passing", o.get("pass_epa_rank"), d.get("pass_epa_rank"), "EPA/play"),
        ("Rushing", o.get("rush_epa_rank"), d.get("rush_epa_rank"), "EPA/play"),
        ("Explosive", o.get("explosive_rate_rank"), d.get("explosive_rate_rank"), "big plays"),
        ("3rd down", _get(off_sit, o_team, "third_rank"), _get(def_sit, d_team, "third_rank"), "conversions"),
        ("Red zone", _get(off_sit, o_team, "rz_rank"), _get(def_sit, d_team, "rz_rank"), "TD finishing"),
    ]
    edges = []
    for label, orank, drank, kind in specs:
        m = _mag(orank, drank)
        if m is None:
            continue
        edges.append({
            "label": label, "mag": float(m),
            "detail": f"{o_team} {_ord(orank)} {kind} vs {d_team} D {_ord(drank)}",
        })

    # positional receiving (featured usage vs coverage soft spot)
    if usage is not None and not usage.empty and o_team in usage.index:
        for pos in ("RB", "WR", "TE"):
            share_rank = usage.loc[o_team].get(f"{pos}_share_rank")
            dfp = dvp.get(pos)
            def_rank = _get(dfp, d_team, "def_rank")
            m = _mag(share_rank, def_rank)
            if m is None:
                continue
            share = usage.loc[o_team].get(f"{pos}_tgt_share")
            share_txt = f"{share * 100:.0f}% targets" if pd.notna(share) else ""
            edges.append({
                "label": f"{pos} receiving", "mag": float(m),
                "detail": f"{o_team} {pos} {share_txt} vs {d_team} allows {_ord(33 - int(def_rank))}-most",
            })
    return edges


def direction_net(edges: list[dict]) -> float:
    """A single 'how big is this offense's edge' score (mean facet edge)."""
    if not edges:
        return 0.0
    return sum(e["mag"] for e in edges) / len(edges)


def collect_game_edges(away: str, home: str, off: pd.DataFrame, deff: pd.DataFrame,
                       extras: dict) -> list[dict]:
    out = []
    for o_team, d_team in ((away, home), (home, away)):
        for e in facet_edges(o_team, d_team, off, deff, extras):
            out.append({"Game": f"{away} @ {home}", "Edge": f"{o_team} {e['label']}",
                        "Detail": e["detail"], "mag": e["mag"]})
    return out


def week_leans(games: pd.DataFrame, off: pd.DataFrame, deff: pd.DataFrame,
               extras: dict, top_n: int = 20) -> pd.DataFrame:
    rows = []
    for r in games.itertuples():
        rows += collect_game_edges(r.away_team, r.home_team, off, deff, extras)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("mag", ascending=False)
    df = df[df["mag"] >= 10]
    return df.head(top_n).reset_index(drop=True)
