"""Market-anchored player props — treat the book's prop line like we treat the spread.

Sides and totals are already priced *against the market*: we blend our number toward
the consensus line and measure edge off the de-vigged price (``betting.assess``).
Props historically weren't — the auto board compared a projection to the player's
season average, which answers "is he trending up?" not "is there value at the number
the book actually hung?".

This closes that gap. Given the posted over/under prices for a prop it:

  * **de-vigs** them (Shin's method) into a fair P(over) — the market's honest read;
  * **blends** our model's P(over) toward that fair number (``PROP_MODEL_TRUST``),
    exactly as sides blend toward the spread, because prop markets are efficient too
    (if softer than sides — hence a touch more model trust is defensible);
  * measures **edge** as blended − market, i.e. value versus the true line, not versus
    a season norm.

The book line also *replaces* the season-average baseline the projection is scored
at, so the over/under probability is computed at the number that's actually bettable.
All of this is optional: with no odds feed (or no key / spent quota) the props fall
back to the season-baseline behaviour unchanged.
"""
from __future__ import annotations

import pandas as pd

import config
from data import betting


def devig_over(over_ml, under_ml) -> float:
    """Fair P(over) from a two-way prop price (Shin's method). NaN on bad input."""
    ph, pa = betting.implied_prob(over_ml), betting.implied_prob(under_ml)
    if pd.isna(ph) or pd.isna(pa) or (ph + pa) == 0:
        return float("nan")
    fair = betting.shin_devig([ph, pa])
    return float(fair[0]) if fair else float(ph / (ph + pa))


def blend(model_p: float, market_p: float, trust: float | None = None) -> float:
    """Blend our P(over) toward the market's, mirroring the spread blend in assess."""
    if pd.isna(model_p):
        return market_p
    if pd.isna(market_p):
        return model_p
    t = config.PROP_MODEL_TRUST if trust is None else trust
    return t * float(model_p) + (1 - t) * float(market_p)


def norm_name(s) -> str:
    """Loose match key: lowercase, drop punctuation/suffixes ('A.J. Brown Jr.' → 'aj brown')."""
    s = str(s).lower().strip()
    for junk in (".", ",", "'", "’", "-"):
        s = s.replace(junk, "")
    for suf in (" jr", " sr", " ii", " iii", " iv", " v"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return " ".join(s.split())


def index_lines(prop_lines: pd.DataFrame) -> dict:
    """Collapse per-book prop rows to one consensus entry per (player, stat).

    Returns ``{(norm_name, stat): {line, market_p, over_odds, under_odds, n_books}}``:

      * ``line``       — median line across books (robust to a stale book);
      * ``market_p``   — de-vigged P(over) at the median over/under price;
      * ``over_odds``/``under_odds`` — best (highest) price available each way, so a
        bet is priced at the sharpest number a shopper could actually take.
    """
    if prop_lines is None or getattr(prop_lines, "empty", True):
        return {}
    need = {"player", "stat", "line"}
    if not need.issubset(prop_lines.columns):
        return {}
    out: dict = {}
    for (who, stat), g in prop_lines.groupby(["player", "stat"]):
        line = pd.to_numeric(g["line"], errors="coerce").dropna()
        if line.empty:
            continue
        med_line = float(line.median())
        over = pd.to_numeric(g.get("over"), errors="coerce").dropna() if "over" in g else pd.Series(dtype=float)
        under = pd.to_numeric(g.get("under"), errors="coerce").dropna() if "under" in g else pd.Series(dtype=float)
        market_p = float("nan")
        if not over.empty and not under.empty:
            market_p = devig_over(float(over.median()), float(under.median()))
        out[(norm_name(who), stat)] = {
            "line": med_line,
            "market_p": market_p,
            "over_odds": float(over.max()) if not over.empty else None,
            "under_odds": float(under.max()) if not under.empty else None,
            "n_books": int(g["book"].nunique()) if "book" in g else int(len(g)),
        }
    return out


def lookup(index: dict, player: str, stat: str) -> dict | None:
    """Find a player's line for a stat by normalized name; None if not posted."""
    if not index:
        return None
    return index.get((norm_name(player), stat))
