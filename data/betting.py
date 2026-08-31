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
from data.qbvalue import qb_adjustment
from data.weather import weather_effects


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


# --- special teams -----------------------------------------------------------
def team_st_points(st_weighted: pd.DataFrame) -> pd.Series:
    """Special-teams points/game per team (weighted ST EPA per game)."""
    if st_weighted is None or st_weighted.empty or "game_id" not in st_weighted.columns:
        return pd.Series(dtype=float)
    out = {}
    for team, g in st_weighted.groupby("posteam"):
        wsum = g["w"].sum()
        games = g["game_id"].nunique()
        # weighted per-play ST EPA x plays/game — weight-scale-invariant.
        out[team] = float((g["w"] * g["epa"]).sum() / wsum * len(g) / games) if wsum and games else 0.0
    return pd.Series(out)


def home_field(home: str) -> float:
    """Home-field advantage in points (team-specific where it's known to differ)."""
    return config.TEAM_HFA.get(home, config.HOME_FIELD_ADVANTAGE)


def points_ratings(schedule: pd.DataFrame, season: int,
                   before_week: int | None = None) -> pd.Series:
    """Average point differential per team from played games (a stable, orthogonal
    signal to EPA). Falls back to the prior season when the current one has no
    results yet. ``before_week`` keeps the backtest honest (train on the past)."""
    if schedule is None or schedule.empty or "result" not in schedule.columns:
        return pd.Series(dtype=float)
    s = schedule[(schedule["season"] == season) & schedule["result"].notna()]
    if before_week is not None:
        s = s[s["week"] < before_week]
    if s.empty:
        s = schedule[(schedule["season"] == season - 1) & schedule["result"].notna()]
    if s.empty or "home_score" not in s.columns:
        return pd.Series(dtype=float)
    diff, games = {}, {}
    for _, r in s.iterrows():
        h, a, hs, as_ = r.get("home_team"), r.get("away_team"), r.get("home_score"), r.get("away_score")
        if pd.isna(hs) or pd.isna(as_):
            continue
        diff[h] = diff.get(h, 0) + (hs - as_); games[h] = games.get(h, 0) + 1
        diff[a] = diff.get(a, 0) + (as_ - hs); games[a] = games.get(a, 0) + 1
    return pd.Series({t: diff[t] / games[t] for t in games if games[t]})


def strength_of_schedule(schedule: pd.DataFrame, power: pd.DataFrame) -> pd.Series:
    """Avg opponent net power rating over completed games (played SOS)."""
    if schedule is None or schedule.empty or power.empty or "net" not in power.columns:
        return pd.Series(dtype=float)
    played = schedule[schedule.get("result").notna()] if "result" in schedule.columns else schedule
    if played.empty:
        return pd.Series(dtype=float)
    season = played["season"].max()
    played = played[played["season"] == season]
    opp = {}
    for _, r in played.iterrows():
        h, a = r.get("home_team"), r.get("away_team")
        if h in power.index and a in power.index:
            opp.setdefault(h, []).append(power.loc[a, "net"])
            opp.setdefault(a, []).append(power.loc[h, "net"])
    return pd.Series({t: float(pd.Series(v).mean()) for t, v in opp.items()})


# --- projection --------------------------------------------------------------
def project_margin(off: pd.DataFrame, deff: pd.DataFrame, home: str, away: str,
                   st: pd.Series | None = None, qb: pd.DataFrame | None = None,
                   points: pd.Series | None = None, elo: pd.Series | None = None,
                   injuries: dict | None = None, sharp_mgn: float | None = None) -> float:
    """Projected home margin (points, + = home favored), matchup-aware.

    An ensemble: EPA efficiency blended with a stable points-differential signal,
    an independent Elo power rating, and (when present) Sharp Football's charted
    EPA margin — then the special-teams edge, team home field, and injury
    adjustment.
    """
    if home not in off.index or away not in off.index:
        return np.nan

    def exp_off(o_team, d_team):
        o = off.loc[o_team, "epa_play"]
        d = deff.loc[d_team, "epa_play"]
        if pd.isna(o) and pd.isna(d):
            return np.nan
        return np.nanmean([o, d])

    home_off = exp_off(home, away)
    away_off = exp_off(away, home)
    if pd.isna(home_off) or pd.isna(away_off):
        return np.nan
    core = (home_off - away_off) * config.PLAYS_PER_TEAM
    # regress the noisier EPA margin toward actual point differential
    if points is not None and len(points) and home in points.index and away in points.index:
        pm = float(points.get(home, 0.0) - points.get(away, 0.0))
        core = (1 - config.POINTS_WEIGHT) * core + config.POINTS_WEIGHT * pm
    # blend in the independent Elo rating (ensemble + early-season prior)
    if elo is not None and len(elo) and home in elo.index and away in elo.index:
        from data.elo import expected_margin
        em = expected_margin(elo, home, away)
        if pd.notna(em):
            core = (1 - config.ELO_WEIGHT) * core + config.ELO_WEIGHT * em
    # blend in Sharp Football's independent charted-EPA margin (a second opinion
    # on the same quantity). Gated + low-weight; the review loop grades it and the
    # tuner can adjust once the season runs. Absent in the offseason → no effect.
    if sharp_mgn is not None and pd.notna(sharp_mgn) and config.SHARP_WEIGHT > 0:
        core = (1 - config.SHARP_WEIGHT) * core + config.SHARP_WEIGHT * float(sharp_mgn)
    margin = core + home_field(home)
    if st is not None and len(st):
        margin += st.get(home, 0.0) - st.get(away, 0.0)
    if qb is not None and not qb.empty:
        margin -= qb_adjustment(qb, home)   # home starter Out -> home worse
        margin += qb_adjustment(qb, away)   # away starter Out -> away worse
    if injuries:                            # non-QB injuries (WR1, edge, OL, CB…)
        margin -= injuries.get(home, 0.0)
        margin += injuries.get(away, 0.0)
    return margin


def win_prob(margin: float) -> float:
    """Home win probability from projected margin (normal CDF on the margin std)."""
    if pd.isna(margin):
        return np.nan
    return 0.5 * (1 + math.erf(margin / (config.MARGIN_STD * math.sqrt(2))))


def project_total(off: pd.DataFrame, deff: pd.DataFrame, home: str, away: str,
                  pace: pd.Series | None = None) -> float:
    """Projected combined points from matchup efficiency, adjusted for pace."""
    if home not in off.index or away not in off.index:
        return np.nan

    def exp_off(o_team, d_team):
        o = off.loc[o_team, "epa_play"]
        d = deff.loc[d_team, "epa_play"]
        if pd.isna(o) and pd.isna(d):
            return np.nan
        return np.nanmean([o, d])

    h, a = exp_off(home, away), exp_off(away, home)
    if pd.isna(h) or pd.isna(a):
        return np.nan
    total = 2 * config.LEAGUE_TEAM_PPG + (h + a) * config.PLAYS_PER_TEAM
    if pace is not None and len(pace) and home in pace.index and away in pace.index:
        lg = float(pace.mean())
        extra = (pace.get(home, lg) + pace.get(away, lg) - 2 * lg)
        total += extra * config.PACE_PTS_PER_PLAY
    return total


def _key_number_straddle(our_margin, mkt_spread) -> int | None:
    """Return a key number our number and the market land on opposite sides of."""
    if pd.isna(our_margin) or pd.isna(mkt_spread):
        return None
    lo, hi = sorted((abs(our_margin), abs(mkt_spread)))
    for k in config.KEY_NUMBERS:
        if lo < k < hi:  # they straddle key number k
            return k
    return None


def _confidence(edge_pts) -> str:
    if pd.isna(edge_pts):
        return "—"
    e = abs(edge_pts)
    if e >= 4:
        return "High"
    if e >= 2.5:
        return "Medium"
    return "Low"


def kelly_stake(p: float, odds_american: float = -110, fraction: float = 0.25) -> float:
    """Fractional-Kelly stake as a share of bankroll for win prob ``p``.

    Defaults to quarter-Kelly at standard -110 juice — the conservative sizing
    pros use so variance doesn't wreck the bankroll.
    """
    if p is None or pd.isna(p) or p <= 0 or p >= 1:
        return 0.0
    dec = 1 + (100 / abs(odds_american) if odds_american < 0 else odds_american / 100)
    b = dec - 1
    f = (b * p - (1 - p)) / b
    return max(0.0, f * fraction)


def fair_moneyline(prob: float) -> int | None:
    """Fair American odds for a win probability (no vig)."""
    if prob is None or pd.isna(prob) or prob <= 0 or prob >= 1:
        return None
    return int(round(-100 * prob / (1 - prob))) if prob >= 0.5 else int(round(100 * (1 - prob) / prob))


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
    qb = extras.get("qb_value") if extras else None
    for team in (away, home):
        outs = [p for p in inj.get(team, []) if p["status"] == "Out"]
        qb_out = [p for p in outs if p["pos"] == "QB"]
        if qb_out:
            pts = qb_adjustment(qb, team) if qb is not None else 0
            worth = f" (~{pts:.1f} pts, now priced in)" if pts else ""
            flags.append(f"{team} QB {qb_out[0]['name']} is OUT{worth}")
        elif len(outs) >= 2:
            flags.append(f"{team} missing {len(outs)} starters (Out)")
    # quantified non-QB injury impact (what our number has docked)
    inj_pts = extras.get("injury_pts", {}) if extras else {}
    for team in (away, home):
        v = inj_pts.get(team, 0.0)
        if v and v >= 0.5:
            flags.append(f"{team} injuries worth ~{v:.1f} pts (docked from our number)")
    hr, ar = row.get("home_rest"), row.get("away_rest")
    if pd.notna(hr) and pd.notna(ar) and abs(hr - ar) >= 3:
        edge_team = home if hr > ar else away
        flags.append(f"Rest edge: {edge_team} (+{int(abs(hr - ar))} days)")
    wx = weather_effects(row)
    if wx["note"] and wx["total_adj"]:
        flags.append(f"{wx['note']} — **priced in** ({wx['total_adj']:+.1f} total)")
    if row.get("div_game") == 1:
        flags.append("Division game — historically tighter than the spread")
    return flags


# --- full assessment ---------------------------------------------------------
def assess(row: pd.Series, off: pd.DataFrame, deff: pd.DataFrame, extras: dict) -> dict:
    home, away = row["home_team"], row["away_team"]
    st, qb = extras.get("st_ppg"), extras.get("qb_value")
    sharp_mgn = None
    if extras.get("sharp"):
        from data import sharp_value
        sharp_mgn = sharp_value.sharp_margin(extras["sharp"], home, away)
    margin = project_margin(off, deff, home, away, st, qb, extras.get("points_rtg"),
                            extras.get("elo"), extras.get("injury_pts"), sharp_mgn)  # + = home
    wx = weather_effects(row)
    if pd.notna(margin):
        margin *= (1 - wx["margin_compression"])   # bad weather => closer game
    p_home = win_prob(margin)

    mkt_spread = row.get("spread_line")                # + = home favored
    mkt_p_home = devig_home_prob(row.get("home_moneyline"), row.get("away_moneyline"))

    # Blend toward the market (it's highly efficient) — trust our divergence only
    # partway. The actionable edge is measured off this blended number.
    if pd.notna(margin) and pd.notna(mkt_spread):
        blended = config.MODEL_TRUST * margin + (1 - config.MODEL_TRUST) * mkt_spread
        p_home = win_prob(blended)
    else:
        blended = margin
    edge_pts = (blended - mkt_spread) if pd.notna(blended) and pd.notna(mkt_spread) else np.nan
    edge_prob = (p_home - mkt_p_home) if pd.notna(p_home) and pd.notna(mkt_p_home) else np.nan

    value_side = None
    if pd.notna(edge_pts) and abs(edge_pts) >= config.VALUE_SPREAD_PTS:
        value_side = home if edge_pts > 0 else away
    confidence = _confidence(edge_pts)
    key = _key_number_straddle(margin, mkt_spread)

    # disagreement uses our *raw* lean (our genuine opinion vs the book)
    our_fav = home if (pd.notna(margin) and margin > 0) else (away if pd.notna(margin) else None)
    mkt_fav = home if (pd.notna(mkt_spread) and mkt_spread > 0) else (away if pd.notna(mkt_spread) else None)
    disagree = (our_fav and mkt_fav and our_fav != mkt_fav)

    fav = value_side or our_fav
    why = []
    if fav:
        opp = away if fav == home else home
        fe = sorted(edges.facet_edges(fav, opp, off, deff, extras),
                    key=lambda e: e["impact"], reverse=True)
        why = [e for e in fe if e["impact"] >= 6][:3]

    # total (over/under): pace-aware, QB-out & weather adjusted, then market-blended
    model_total = project_total(off, deff, home, away, extras.get("pace"))
    if qb is not None and not qb.empty and pd.notna(model_total):
        model_total -= 0.5 * (qb_adjustment(qb, home) + qb_adjustment(qb, away))
    if pd.notna(model_total):
        model_total += wx["total_adj"]
    mkt_total = row.get("total_line")
    total_edge = np.nan
    total_side = None
    if pd.notna(model_total) and pd.notna(mkt_total):
        blended_total = config.MODEL_TRUST * model_total + (1 - config.MODEL_TRUST) * mkt_total
        total_edge = blended_total - mkt_total
        if abs(total_edge) >= config.VALUE_TOTAL_PTS:
            total_side = "Over" if total_edge > 0 else "Under"

    ml_side = None
    if pd.notna(edge_prob) and abs(edge_prob) >= config.VALUE_PROB:
        ml_side = home if edge_prob > 0 else away

    return {
        "home": home, "away": away,
        "model_margin": margin, "blended_margin": blended,
        "model_p_home": p_home, "model_total": model_total,
        "mkt_spread": mkt_spread, "mkt_p_home": mkt_p_home, "total_line": mkt_total,
        "edge_pts": edge_pts, "edge_prob": edge_prob, "total_edge": total_edge,
        "value_side": value_side, "total_side": total_side, "ml_side": ml_side,
        "confidence": confidence, "key_number": key,
        "our_fav": our_fav, "mkt_fav": mkt_fav, "disagree": bool(disagree),
        "why": why, "context": context_flags(row, home, away, extras),
    }


def fmt_line(team_favored: str, margin: float) -> str:
    """'KC -6.5' style from a home-margin number and who's favored."""
    if pd.isna(margin):
        return "—"
    return f"{team_favored} -{abs(margin):.1f}"
