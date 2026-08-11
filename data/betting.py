"""Betting model: turn our compiled data into a projected line, compare it to
the market, and surface where the value (and the disagreement) is.

Flow:
  1. Power-rate every team from net efficiency (offense EPA minus defense EPA
     allowed) — the same data the other tabs use.
  2. Project each game to a point spread + win probability, matchup-aware.
  3. Pull the market line (spread / total / moneyline) from the schedule feed.
  4. Compare: where we differ from the market = potential value; when we and the
     book disagree on the favorite, flag it and explain *why* — both our drivers
     and what the market may be pricing that we don't (injuries, rest, weather).

Line movement and true sharp-money signals need a live odds feed (see
data/odds_providers.py); this module works off the free schedule lines today.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config
from data import edges


# --- team power ratings ------------------------------------------------------
def power_ratings(off: pd.DataFrame, deff: pd.DataFrame) -> pd.DataFrame:
    """Net efficiency per team: offense EPA/play minus defense EPA/play allowed."""
    idx = sorted(set(off.index) | set(deff.index))
    rows = []
    for t in idx:
        o = off.loc[t, "epa_play"] if t in off.index else np.nan
        d = deff.loc[t, "epa_play"] if t in deff.index else np.nan
        # good defense has negative EPA allowed, so subtracting it adds strength
        net = (0 if pd.isna(o) else o) - (0 if pd.isna(d) else d)
        rows.append({"team": t, "off_epa": o, "def_epa": d, "net": net})
    m = pd.DataFrame(rows).set_index("team")
    m["power_rank"] = m["net"].rank(ascending=False, method="min").astype("Int64")
    return m


# --- projection --------------------------------------------------------------
def project_margin(off: pd.DataFrame, deff: pd.DataFrame, home: str, away: str) -> float:
    """Projected home margin (points, + = home favored), matchup-aware."""
    if home not in off.index or away not in off.index:
        return np.nan

    def exp_off(o_team, d_team):
        # a team's expected EPA/play = blend of its offense and the D it faces
        o = off.loc[o_team, "epa_play"]
        d = deff.loc[d_team, "epa_play"]  # EPA allowed by that defense
        if pd.isna(o) and pd.isna(d):
            return np.nan
        return np.nanmean([o, d])

    home_off = exp_off(home, away)
    away_off = exp_off(away, home)
    if pd.isna(home_off) or pd.isna(away_off):
        return np.nan
    margin_per_play = home_off - away_off
    return margin_per_play * config.PLAYS_PER_TEAM + config.HOME_FIELD_ADVANTAGE


def win_prob(margin: float) -> float:
    """Home win probability from projected margin (logistic)."""
    if pd.isna(margin):
        return np.nan
    return 1.0 / (1.0 + math.exp(-margin * config.WINPROB_SLOPE))


# --- market ------------------------------------------------------------------
def implied_prob(moneyline) -> float:
    if moneyline is None or pd.isna(moneyline):
        return np.nan
    ml = float(moneyline)
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def devig_home_prob(home_ml, away_ml) -> float:
    ph, pa = implied_prob(home_ml), implied_prob(away_ml)
    if pd.isna(ph) or pd.isna(pa) or (ph + pa) == 0:
        return np.nan
    return ph / (ph + pa)


# --- context the market prices (that our efficiency model may not) -----------
def context_flags(row: pd.Series, home: str, away: str, extras: dict) -> list[str]:
    flags = []
    inj = extras.get("injuries", {}) if extras else {}
    for team in (away, home):
        outs = [p for p in inj.get(team, []) if p["status"] == "Out"]
        qb_out = [p for p in outs if p["pos"] == "QB"]
        if qb_out:
            flags.append(f"🔴 {team} QB {qb_out[0]['name']} is OUT — big market factor our model doesn't price")
        elif len(outs) >= 2:
            flags.append(f"🟠 {team} missing {len(outs)} starters (Out)")
    hr, ar = row.get("home_rest"), row.get("away_rest")
    if pd.notna(hr) and pd.notna(ar) and abs(hr - ar) >= 3:
        edge_team = home if hr > ar else away
        flags.append(f"🛌 Rest edge: {edge_team} (+{int(abs(hr - ar))} days)")
    wind = row.get("wind")
    if pd.notna(wind) and wind >= 15:
        flags.append(f"💨 Wind {int(wind)} mph — suppresses passing/scoring (market leans under)")
    temp = row.get("temp")
    if pd.notna(temp) and temp <= 20:
        flags.append(f"🥶 {int(temp)}°F — cold-weather game")
    if row.get("div_game") == 1:
        flags.append("🤝 Division game — historically tighter than the spread")
    return flags


# --- full assessment ---------------------------------------------------------
def assess(row: pd.Series, off: pd.DataFrame, deff: pd.DataFrame, extras: dict) -> dict:
    home, away = row["home_team"], row["away_team"]
    margin = project_margin(off, deff, home, away)     # + = home favored
    p_home = win_prob(margin)

    mkt_spread = row.get("spread_line")                # + = home favored
    mkt_p_home = devig_home_prob(row.get("home_moneyline"), row.get("away_moneyline"))

    # our line vs market line (both home-favored positive)
    edge_pts = (margin - mkt_spread) if pd.notna(margin) and pd.notna(mkt_spread) else np.nan
    edge_prob = (p_home - mkt_p_home) if pd.notna(p_home) and pd.notna(mkt_p_home) else np.nan

    # value side on the spread: if our margin > market spread, we like HOME
    value_side = None
    if pd.notna(edge_pts) and abs(edge_pts) >= config.VALUE_SPREAD_PTS:
        value_side = home if edge_pts > 0 else away

    # disagreement on the outright favorite
    our_fav = home if (pd.notna(margin) and margin > 0) else (away if pd.notna(margin) else None)
    mkt_fav = home if (pd.notna(mkt_spread) and mkt_spread > 0) else (away if pd.notna(mkt_spread) else None)
    disagree = (our_fav and mkt_fav and our_fav != mkt_fav)

    # why: our strongest weighted edges for the side we favor
    fav = our_fav
    why = []
    if fav:
        opp = away if fav == home else home
        fe = sorted(edges.facet_edges(fav, opp, off, deff, extras),
                    key=lambda e: e["impact"], reverse=True)
        why = [e for e in fe if e["impact"] >= 6][:3]

    return {
        "home": home, "away": away,
        "model_margin": margin, "model_p_home": p_home,
        "mkt_spread": mkt_spread, "mkt_p_home": mkt_p_home,
        "total_line": row.get("total_line"),
        "edge_pts": edge_pts, "edge_prob": edge_prob,
        "value_side": value_side, "our_fav": our_fav, "mkt_fav": mkt_fav,
        "disagree": bool(disagree),
        "why": why, "context": context_flags(row, home, away, extras),
    }


def fmt_line(team_favored: str, margin: float) -> str:
    """'KC -6.5' style from a home-margin number and who's favored."""
    if pd.isna(margin):
        return "—"
    return f"{team_favored} -{abs(margin):.1f}"
