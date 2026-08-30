"""Touchdown model — anytime / 2+ scorer probabilities the Vegas way.

Touchdowns aren't yards. They're driven by **who gets the ball near the goal
line**, how many TDs the team is likely to score (a function of its projected
points, which folds in the matchup, spread, total, and weather), and how those
TDs split between the run and the pass against this defense. So we:

  1. Measure each player's red-zone and goal-line usage from play-by-play.
  2. Project the team's expected offensive TDs from its projected points.
  3. Split those into rush vs pass TDs, nudged by the opponent's run/pass defense.
  4. Distribute them to players by their goal-line (rush) and red-zone (target)
     share, giving an expected-TD rate per player.
  5. Turn that into anytime (1 − e^−λ) and 2+ (Poisson) scoring probabilities.

Everything is fed by the same engines as the rest of the app — no separate data.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config
from data import betting
from data.weather import weather_effects

SKILL = ("QB", "RB", "WR", "TE", "FB")
# league split of offensive TDs and share of points that come from TDs
_BASE_RUSH_SHARE = 0.44
_PTS_PER_TD_DRIVE = 7.0
_TD_POINT_SHARE = 0.74   # ~74% of a team's points come from offensive TDs


def redzone_usage(pbp: pd.DataFrame, posmap: dict, name_map: dict | None = None) -> pd.DataFrame:
    """Per player: carries/targets plus red-zone (≤20) and goal-line (≤5/≤10) usage."""
    if pbp is None or pbp.empty or "yardline_100" not in pbp.columns:
        return pd.DataFrame()
    df = pbp
    if "season" in df.columns:
        season = (config.CURRENT_SEASON if (df["season"] == config.CURRENT_SEASON).any()
                  else config.PRIOR_SEASON)
        df = df[df["season"] == season]
    if df.empty:
        return pd.DataFrame()
    name_map = name_map or {}
    yl = df["yardline_100"]

    rush = df[df.get("rush") == 1].copy()
    rush_g = rush.groupby("rusher_player_id").agg(
        team=("posteam", "last"), games=("game_id", "nunique"),
        carries=("rush", "sum"),
        rz_carries=("yardline_100", lambda s: (s <= 20).sum()),
        gl_carries=("yardline_100", lambda s: (s <= 5).sum()),
        rush_td=("touchdown", "sum"))
    rec = df[(df.get("pass") == 1) & df["receiver_player_id"].notna()].copy()
    rec_g = rec.groupby("receiver_player_id").agg(
        team=("posteam", "last"), games=("game_id", "nunique"),
        targets=("pass", "sum"),
        rz_targets=("yardline_100", lambda s: (s <= 20).sum()),
        gl_targets=("yardline_100", lambda s: (s <= 10).sum()),
        rec_td=("touchdown", "sum"))

    out = pd.concat([rush_g, rec_g], axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    for c in ("carries", "rz_carries", "gl_carries", "rush_td",
              "targets", "rz_targets", "gl_targets", "rec_td"):
        if c not in out.columns:
            out[c] = 0
        out[c] = out[c].fillna(0)
    # team & games from whichever role has data
    team = pd.concat([f["team"] for f in (rush_g, rec_g) if not f.empty], axis=1).bfill(axis=1).iloc[:, 0]
    games = pd.concat([f["games"] for f in (rush_g, rec_g) if not f.empty], axis=1).max(axis=1)
    out["team"] = team
    out["games"] = games.fillna(1).clip(lower=1)
    out["pos"] = [posmap.get(i, "") for i in out.index]
    out["name"] = [name_map.get(i, i) for i in out.index]
    return out[out["pos"].isin(SKILL)]


def team_expected_tds(off, deff, extras: dict, row: pd.Series) -> dict:
    """Projected offensive TDs for each team in a game (matchup + script + weather)."""
    home, away = row["home_team"], row["away_team"]
    total = betting.project_total(off, deff, home, away, extras.get("pace"))
    margin = betting.project_margin(off, deff, home, away, extras.get("st_ppg"), extras.get("qb_value"))
    wx = weather_effects(row)
    if pd.notna(total):
        total = total + wx.get("total_adj", 0)
    if pd.isna(total) or pd.isna(margin):
        return {}
    home_pts = (total + margin) / 2
    away_pts = (total - margin) / 2
    out = {}
    for team, pts in ((home, home_pts), (away, away_pts)):
        exp_td = max(pts, 0) * _TD_POINT_SHARE / _PTS_PER_TD_DRIVE
        opp = away if team == home else home
        rush_share = _BASE_RUSH_SHARE
        if opp in deff.index:
            rr = deff.loc[opp].get("rush_epa_rank")
            pr = deff.loc[opp].get("pass_epa_rank")
            if pd.notna(rr) and pd.notna(pr):
                # soft run D (high rank) → more rush TDs; soft pass D → more pass TDs
                rush_share += (int(rr) - int(pr)) / 32 * 0.12
        rush_share = min(max(rush_share, 0.28), 0.62)
        out[team] = {"exp_td": exp_td, "rush_td": exp_td * rush_share,
                     "pass_td": exp_td * (1 - rush_share), "points": pts,
                     "weather": wx.get("note", "")}
    return out


def _shares(usage: pd.DataFrame, team: str) -> pd.DataFrame:
    t = usage[usage["team"] == team].copy()
    if t.empty:
        return t
    # goal-line weighting for rush TDs; red-zone target weighting for pass TDs
    t["_rush_w"] = t["gl_carries"] * 2 + t["rz_carries"] + t["carries"] * 0.15
    t["_rec_w"] = t["gl_targets"] * 1.5 + t["rz_targets"] + t["targets"] * 0.2
    rush_sum = t["_rush_w"].sum()
    rec_sum = t["_rec_w"].sum()
    t["rush_share"] = t["_rush_w"] / rush_sum if rush_sum else 0.0
    t["rec_share"] = t["_rec_w"] / rec_sum if rec_sum else 0.0
    return t


def td_board(off, deff, extras: dict, games: pd.DataFrame, min_share: float = 0.03) -> pd.DataFrame:
    """Anytime / 2+ TD probabilities for every meaningful player across a slate."""
    usage = extras.get("rz_usage")
    if usage is None or usage.empty or games is None or games.empty:
        return pd.DataFrame()
    rows = []
    for _, g in games.iterrows():
        exp = team_expected_tds(off, deff, extras, g)
        if not exp:
            continue
        home, away = g["home_team"], g["away_team"]
        for team in (away, home):
            opp = home if team == away else away
            info = exp.get(team, {})
            t = _shares(usage, team)
            for _, p in t.iterrows():
                lam = p["rush_share"] * info.get("rush_td", 0) + p["rec_share"] * info.get("pass_td", 0)
                if lam < min_share:
                    continue
                anytime = 1 - math.exp(-lam)
                two_plus = 1 - math.exp(-lam) * (1 + lam)
                gl = int(p["gl_carries"] + p["gl_targets"])
                driver = []
                if p["gl_carries"] >= 1:
                    driver.append("goal-line back")
                if p["rz_targets"] >= 3:
                    driver.append("red-zone target")
                opp_rank = deff.loc[opp].get("rush_epa_rank" if p["pos"] in ("RB", "FB", "QB")
                                             else "pass_epa_rank") if opp in deff.index else None
                rows.append({
                    "Player": p["name"], "Pos": p["pos"], "Team": team,
                    "Game": f"{away} @ {home}", "Opp": opp,
                    "xTD": round(lam, 2), "Anytime%": round(anytime * 100),
                    "2+%": round(two_plus * 100), "fair": betting.fair_moneyline(anytime),
                    "GL touches": gl, "TeamTotal": round(info.get("points", 0), 1),
                    "Driver": ", ".join(driver) or "volume",
                    "OppRank": int(opp_rank) if opp_rank is not None and pd.notna(opp_rank) else None,
                    "Weather": info.get("weather", ""),
                    "_anytime": anytime,
                })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("xTD", ascending=False).reset_index(drop=True)


def edge_vs_odds(anytime: float, american: float) -> dict:
    """Edge & Kelly for an anytime-TD price the user enters."""
    implied = betting.implied_prob(american)
    edge = anytime - implied if pd.notna(implied) else np.nan
    kelly = betting.kelly_stake(anytime, american)
    return {"implied": implied, "edge": edge, "kelly": kelly,
            "fair": betting.fair_moneyline(anytime)}
