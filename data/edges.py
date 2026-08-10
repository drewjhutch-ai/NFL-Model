"""Collect every edge in a game into one ranked list.

Used by the Picks tab to auto-surface the week's biggest mismatches, and reusable
anywhere a single "how lopsided is this?" score is handy. Every edge carries a
magnitude (positive = offense edge) and a plain-language description, so nothing
is a black box.
"""
from __future__ import annotations

import pandas as pd

from data import positional


def _unit_mag(off_rank, def_rank) -> float | None:
    if pd.isna(off_rank) or pd.isna(def_rank):
        return None
    return (32 - int(def_rank)) - (int(off_rank) - 1)


def collect_game_edges(away: str, home: str, off: pd.DataFrame, deff: pd.DataFrame,
                       dvp: dict, usage: pd.DataFrame) -> list[dict]:
    """All unit + positional edges for both directions of a game."""
    edges: list[dict] = []
    game = f"{away} @ {home}"

    for o_team, d_team in ((away, home), (home, away)):
        if o_team in off.index and d_team in deff.index:
            o, d = off.loc[o_team], deff.loc[d_team]
            for cat, orank, drank in (
                ("Passing", o["pass_epa_rank"], d["pass_epa_rank"]),
                ("Rushing", o["rush_epa_rank"], d["rush_epa_rank"]),
                ("Overall", o["epa_play_rank"], d["epa_play_rank"]),
            ):
                mag = _unit_mag(orank, drank)
                if mag is None:
                    continue
                edges.append({
                    "Game": game,
                    "Edge": f"{o_team} {cat.lower()}",
                    "Detail": f"{o_team} {cat} vs {d_team} defense",
                    "mag": float(mag),
                })

        # positional (RB/WR/TE receiving)
        pt = positional.matchup_table(o_team, d_team, usage, dvp)
        for r in pt.itertuples():
            mag = getattr(r, "_mag", 0)
            pos = getattr(r, "Position", "")
            edges.append({
                "Game": game,
                "Edge": f"{o_team} {pos}",
                "Detail": f"{o_team} {pos} vs {d_team} — {getattr(r, 'Edge', '')}",
                "mag": float(mag),
            })
    return edges


def week_leans(games: pd.DataFrame, off: pd.DataFrame, deff: pd.DataFrame,
               dvp: dict, usage: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Rank the strongest offense-side edges across a week's games."""
    all_edges: list[dict] = []
    for r in games.itertuples():
        all_edges += collect_game_edges(r.away_team, r.home_team, off, deff, dvp, usage)
    if not all_edges:
        return pd.DataFrame()
    df = pd.DataFrame(all_edges).sort_values("mag", ascending=False)
    df = df[df["mag"] >= 10]  # only meaningful leans
    return df.head(top_n).reset_index(drop=True)
