"""Player-prop projections as distributions, not point numbers.

A 62-yard projection isn't a bet — P(over 54.5) is. This turns each player's
matchup-adjusted projected mean into an over/under probability by modeling the
stat's game-to-game spread: yards are wide (a normal around the mean with a
stat-specific spread), touchdowns are rare events (Poisson). Feed it a line and
it returns the probability and a fair price; with no line it just projects.

Means come from data.players.project (usage × matchup). Game script and pace from
the Matchups sim can scale volume before we compute the distribution.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from data import betengine, players

# Coefficient of variation (sd / mean) for a single game, by stat. Rough but
# grounded: yardage is high-variance, volume counts less so, passing yards tight.
_CV = {
    "Rec yds": 0.62, "Rush yds": 0.58, "Pass yds": 0.24,
    "Rec": 0.42, "Targets": 0.34, "Carries": 0.30,
}
_POISSON = {"Pass TD"}
# The props worth surfacing, in display order.
PROP_STATS = ["Pass yds", "Pass TD", "Rush yds", "Carries", "Rec yds", "Rec", "Targets"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def over_prob(mean: float, line: float, stat: str) -> float:
    """P(stat > line) for a projected ``mean``. Normal for yards/volume, Poisson for TDs."""
    if pd.isna(mean) or pd.isna(line) or mean <= 0:
        return np.nan
    if stat in _POISSON:
        # P(X > line) with X ~ Poisson(mean); line usually 0.5/1.5
        k = math.floor(line)
        cdf = sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(k + 1))
        return float(1 - cdf)
    cv = _CV.get(stat, 0.45)
    sd = max(mean * cv, 1e-6)
    return float(1 - _norm_cdf((line - mean) / sd))


def project_player(player: pd.Series, opp: str, deff: pd.DataFrame, dvp: dict,
                   script: float = 0.0) -> dict:
    """Matchup-adjusted projected means, optionally nudged by game script.

    ``script`` is the team's projected margin (+ = favored). A favored team runs
    more late (bump carries, trim pass volume); an underdog throws more.
    """
    proj = players.project(player, opp, deff, dvp)
    if script and proj:
        pass_bump = 1 - min(max(script, -14), 14) / 100.0   # dog throws more
        rush_bump = 1 + min(max(script, -14), 14) / 120.0   # favorite runs more
        for k in ("Pass yds", "Rec yds", "Rec", "Targets"):
            if k in proj:
                proj[k] *= pass_bump
        for k in ("Rush yds", "Carries"):
            if k in proj:
                proj[k] *= rush_bump
    return proj


# raw-stat column behind each display stat, and the minimum volume worth a pick
_RAW = {"Pass yds": "passing_yards", "Pass TD": "passing_tds", "Rush yds": "rushing_yards",
        "Carries": "carries", "Rec yds": "receiving_yards", "Rec": "receptions", "Targets": "targets"}
_MIN_VOL = {"Pass yds": 150, "Pass TD": 0.8, "Rush yds": 25, "Carries": 6,
            "Rec yds": 25, "Rec": 2.0, "Targets": 3.0}


def _matchup_note(pos: str, stat: str, opp: str, deff, dvp) -> tuple[str, int | None]:
    """A human matchup reason + the opponent's rank for that facet (1=tough,32=soft)."""
    from data.profiles import _ordinal
    rank = None
    if stat in ("Rec yds", "Rec", "Targets") and pos in dvp:
        d = dvp.get(pos)
        rank = int(d.loc[opp, "def_rank"]) if d is not None and opp in d.index and pd.notna(d.loc[opp, "def_rank"]) else None
        desc = f"vs {pos}s"
    elif stat in ("Rush yds", "Carries"):
        rank = int(deff.loc[opp, "rush_epa_rank"]) if opp in deff.index else None
        desc = "vs the run"
    else:
        rank = int(deff.loc[opp, "pass_epa_rank"]) if opp in deff.index else None
        desc = "vs the pass"
    if rank is None:
        return f"{opp} {desc}", None
    softness = "soft" if rank >= 22 else ("tough" if rank <= 11 else "average")
    return f"{opp} {_ordinal(rank)} {desc} ({softness})", rank


def _prop_confidence(p_side: float, delta: float, volume: float, vol_ref: float,
                     games_played: int) -> float:
    """0–100 for a prop lean: decisiveness × matchup swing × volume, damped by sample."""
    decisiveness = min(abs(p_side - 0.5) * 2, 1.0)
    swing = min(abs(delta) / 0.18, 1.0)
    vol = min(volume / vol_ref, 1.0) if vol_ref else 0.5
    core = 0.5 * decisiveness + 0.3 * swing + 0.2 * vol
    sample = 0.6 if games_played <= 0 else min(games_played / 6.0, 1.0)
    return round(100 * core * sample, 1)


def auto_prop_picks(stats: pd.DataFrame, off, deff, extras: dict, games: pd.DataFrame,
                    per_team: int = 5, games_played: int = 0) -> pd.DataFrame:
    """Auto-surface the strongest player-prop leans for a slate — no book line needed.

    For each game we project every featured skill player against the opponent and
    game script, then compare to their own season baseline. The biggest swings vs
    a line set at their norm are the mismatches worth betting. Returns a ranked
    frame of leans (side, projection, baseline, hit probability, matchup, confidence).
    """
    from data import betting, players as P
    if stats is None or stats.empty or games is None or games.empty:
        return pd.DataFrame()
    dvp = extras.get("dvp", {})
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    rows = []
    for _, g in games.iterrows():
        home, away = g["home_team"], g["away_team"]
        margin = betting.project_margin(off, deff, home, away, st_ppg, qb)
        for team, opp, is_home in ((away, home, False), (home, away, True)):
            script = 0.0 if pd.isna(margin) else float(margin if is_home else -margin)
            tp = P.team_players(stats, team).head(per_team)
            for _, pl in tp.iterrows():
                proj = project_player(pl, opp, deff, dvp, script=script)
                for stat, mean in proj.items():
                    # TD/count props need a real half-point line (0.5/1.5) to read
                    # sensibly — leave those to the finder, not the auto board.
                    if stat in _POISSON:
                        continue
                    raw = _RAW.get(stat)
                    base = pl.get(raw, 0) if raw else 0
                    if raw is None or base < _MIN_VOL.get(stat, 0):
                        continue
                    p_over = over_prob(mean, float(base), stat)
                    if pd.isna(p_over):
                        continue
                    side, p_side = ("Over", p_over) if p_over >= 0.5 else ("Under", 1 - p_over)
                    delta = (mean - base) / base if base else 0.0
                    note, rank = _matchup_note(pl.get("pos", ""), stat, opp, deff, dvp)
                    vol_ref = {"Rec yds": 90, "Rush yds": 90, "Pass yds": 280, "Rec": 7,
                               "Targets": 9, "Carries": 18, "Pass TD": 2}.get(stat, 10)
                    volume = base
                    conf = _prop_confidence(p_side, delta, volume, vol_ref, games_played)
                    rows.append({
                        "Player": pl.get("name"), "Pos": pl.get("pos"), "Team": team,
                        "Game": f"{away} @ {home}", "Stat": stat, "Side": side,
                        "Projection": round(mean, 1), "Baseline": round(float(base), 1),
                        "Hit%": round(p_side * 100),
                        "Matchup": note, "conf": conf,
                        "_delta": abs(delta),
                    })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("conf", ascending=False).reset_index(drop=True)
    return df


def leans_to_bets(leans: pd.DataFrame, games_played: int = 0) -> list[dict]:
    """Convert auto prop leans into Bet-Engine rows so props compete on the board.

    Each lean is priced at a baseline line (the player's season norm) at -110 both
    ways, with ``corr_group`` set to the game so same-game correlation is handled
    in parlays. Edge is the hit probability minus the no-vig 50%.
    """
    if leans is None or leans.empty:
        return []
    out = []
    for _, r in leans.iterrows():
        p = r["Hit%"] / 100.0
        sel = f"{r['Player']} {r['Stat']} {r['Side']} {r['Baseline']:g}"
        out.append(betengine._bet(
            r["Game"], r["Game"], "Player prop", sel, p, -110, -110,
            corr_group=r["Game"], games_played=games_played,
            rationale=f"Proj {r['Projection']:g} vs {r['Baseline']:g} · {r['Matchup']}"))
    return out


def prop_bets(player: pd.Series, proj: dict, game_id: str, game: str, opp: str,
              lines: dict | None = None, games_played: int = 0) -> list[dict]:
    """Turn a player's projections into Bet-Engine rows (edge needs a line).

    ``lines``: {stat: line}. For each stat with a line, the over/under side the
    model prefers becomes a bet at -110 both ways. Without a line, nothing is
    emitted (a projection isn't a bet).
    """
    if not proj or not lines:
        return []
    out = []
    name = player.get("name", "?")
    for stat, line in lines.items():
        mean = proj.get(stat)
        if mean is None or pd.isna(mean) or line is None or pd.isna(line):
            continue
        p_over = over_prob(mean, float(line), stat)
        if pd.isna(p_over):
            continue
        if p_over >= 0.5:
            sel, p = f"{name} {stat} Over {line:g}", p_over
        else:
            sel, p = f"{name} {stat} Under {line:g}", 1 - p_over
        out.append(betengine._bet(
            game_id, game, "Player prop", sel, p, -110, -110, game_id, games_played,
            f"Projected {mean:.1f} vs line {line:g} ({stat}) vs {opp}."))
    return out
