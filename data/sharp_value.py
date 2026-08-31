"""Value the Sharp Football tables into model inputs.

``data/sharp.py`` reads the committed Sharp CSVs; this module turns their raw
columns into normalized, ranked signals the model can actually use: an ensemble
power rating (charted EPA), a pace factor for totals, defensive coverage-by-
position for prop matchups, and tidy per-facet frames for the UI.

Column names are the real ones the scraper produced (confirmed from the Action
log), matched by keyword so a minor Sharp layout change won't break us. Every
accessor returns empty/None when its table isn't present, so callers degrade
gracefully in the offseason.

Real columns per table (for reference):
  pace           : Rank, Play Clock Used, Neutral, Neutral Pass Rate, Gear Change, No Huddle
  off_personnel  : #, 11, 12, 13, 21, 22, 2+ TE, 2+ RB, 3+ WR, Plays
  def_line       : Pressure Rate, No Blitz Pressure Rate, Yards Before Contact Per RB Rush, Rush Stuff Rate
  def_tendencies : Blitz Rate, Light Box Rate, Heavy Box Rate, Sub Package Rate
  coverage_schemes: Man Rate, Zone Rate, Middle Closed Rate, Middle Open Rate
  def_metrics    : EPA/Play, Yards Per Play Allowed, Y/PL Last 5, Points Per Drive Allowed,
                   Explosive Play Rate Allowed, Down Conversion Rate Allowed
  off_line       : Pressure Rate Allowed, No Blitz Pressure Rate Allowed, Time to Throw,
                   Yards Before Contact Per RB Rush, Rush Stuff Rate
  coverage_by_pos: YPT Allowed WR/TE/RB/Outside/Slot
  off_metrics    : EPA/Play, Yards Per Play, Y/PL Last 5, Points Per Drive, Explosive Play Rate,
                   Down Conversion Rate
"""
from __future__ import annotations

import pandas as pd

import config


def _col(df: pd.DataFrame, *keywords: str):
    """First column whose lowercased name contains all keywords, else None."""
    if df is None or getattr(df, "empty", True):
        return None
    for c in df.columns:
        name = str(c).lower()
        if all(k.lower() in name for k in keywords):
            return c
    return None


def _series(df: pd.DataFrame, *keywords: str) -> pd.Series | None:
    c = _col(df, *keywords)
    if c is None:
        return None
    return pd.to_numeric(df[c], errors="coerce")


def _as_rate(s: pd.Series | None) -> pd.Series | None:
    """Normalize a percentage-ish series to a 0-1 fraction if it looks like %."""
    if s is None:
        return None
    if s.dropna().gt(1.5).any():
        return s / 100.0
    return s


# --- ensemble power rating (charted EPA) -------------------------------------
def epa_ratings(sharp: dict) -> pd.DataFrame:
    """team -> off_epa, def_epa (allowed) from Sharp's overall metrics.

    A charted second opinion, independent of our pbp EPA. Empty if absent.
    """
    off = sharp.get("off_metrics") if sharp else None
    deff = sharp.get("def_metrics") if sharp else None
    o = _series(off, "epa") if off is not None else None
    d = _series(deff, "epa") if deff is not None else None
    if o is None and d is None:
        return pd.DataFrame()
    out = pd.DataFrame(index=sorted(set(
        (o.index if o is not None else []) ) | set(d.index if d is not None else [])))
    if o is not None:
        out["off_epa"] = o
    if d is not None:
        out["def_epa"] = d          # EPA/play ALLOWED (lower = better defense)
    return out


def sharp_margin(sharp: dict, home: str, away: str, plays: int | None = None) -> float | None:
    """Expected home margin (points) from Sharp's charted EPA, or None.

    Standard EPA matchup expectation: each offense's EPA/play is blended with the
    opponent defense's EPA/play allowed, scaled to a game's plays.
    """
    rt = epa_ratings(sharp)
    if rt.empty or "off_epa" not in rt.columns or "def_epa" not in rt.columns:
        return None
    if home not in rt.index or away not in rt.index:
        return None
    plays = plays or config.PLAYS_PER_TEAM
    ho, hd = rt.loc[home, "off_epa"], rt.loc[home, "def_epa"]
    ao, ad = rt.loc[away, "off_epa"], rt.loc[away, "def_epa"]
    if any(pd.isna(v) for v in (ho, hd, ao, ad)):
        return None
    home_off = (float(ho) + float(ad)) / 2.0     # home O vs away D
    away_off = (float(ao) + float(hd)) / 2.0     # away O vs home D
    return (home_off - away_off) * plays


# --- pace (totals) -----------------------------------------------------------
def pace_factor(sharp: dict) -> pd.Series:
    """team -> pace multiplier around 1.0 (fast = >1). Empty if no pace table.

    Uses neutral seconds/play when available (lower = faster). Falls back to the
    play-clock-used column. Centered on the league mean so it's a clean nudge.
    """
    pace = sharp.get("pace") if sharp else None
    if pace is None or pace.empty:
        return pd.Series(dtype=float)
    secs = _series(pace, "neutral") if _col(pace, "neutral") and "rate" not in str(_col(pace, "neutral")).lower() else None
    if secs is None:
        secs = _series(pace, "play", "clock")
    if secs is None:
        return pd.Series(dtype=float)
    mean = secs.mean()
    if not mean or pd.isna(mean):
        return pd.Series(dtype=float)
    # fewer seconds/play => faster => more plays => factor > 1
    return (mean / secs).rename("pace_factor")


def neutral_pass_rate(sharp: dict) -> pd.Series:
    """team -> neutral pass rate (PROE-ish tendency), 0-1. Empty if absent."""
    pace = sharp.get("pace") if sharp else None
    s = _as_rate(_series(pace, "neutral", "pass")) if pace is not None else None
    return s.rename("neutral_pass_rate") if s is not None else pd.Series(dtype=float)


# --- coverage by position (prop matchups) ------------------------------------
_POS_KEYS = {"WR": ("ypt", "wr"), "TE": ("ypt", "te"), "RB": ("ypt", "rb"),
             "Outside": ("ypt", "outside"), "Slot": ("ypt", "slot")}


def coverage_by_position(sharp: dict) -> pd.DataFrame:
    """team -> YPT allowed by position + rank (1 = best/stingiest coverage).

    Lower yards-per-target allowed = better coverage. Empty if absent.
    """
    cbp = sharp.get("coverage_by_pos") if sharp else None
    if cbp is None or cbp.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=cbp.index)
    for pos, keys in _POS_KEYS.items():
        s = _series(cbp, *keys)
        if s is None:
            continue
        out[f"ypt_{pos}"] = s
        out[f"ypt_{pos}_rank"] = s.rank(ascending=True, method="min")  # low YPT = rank 1
    return out


# --- trenches (charted) ------------------------------------------------------
def pass_rush_ranks(sharp: dict) -> pd.Series:
    """team -> defensive pass-rush rank (1 = best) from Sharp pressure rate."""
    dl = sharp.get("def_line") if sharp else None
    s = _series(dl, "pressure", "rate") if dl is not None else None
    if s is None:
        return pd.Series(dtype=float)
    return s.rank(ascending=False, method="min").rename("pass_rush_rank")


def pass_pro_ranks(sharp: dict) -> pd.Series:
    """team -> offensive pass-protection rank (1 = best) from pressure allowed."""
    ol = sharp.get("off_line") if sharp else None
    s = _series(ol, "pressure", "allowed") if ol is not None else None
    if s is None:
        return pd.Series(dtype=float)
    return s.rank(ascending=True, method="min").rename("pass_pro_rank")  # low allowed = rank 1


def available(sharp: dict) -> bool:
    return bool(sharp) and any(not v.empty for v in sharp.values())
