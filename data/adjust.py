"""Opponent adjustment (strength of schedule) for EPA metrics.

Raw EPA doesn't care *who* you played. This solves simple offense/defense ratings
so that a play's expected EPA ≈ offense_rating[posteam] + defense_rating[defteam]
+ league_average, via alternating weighted means (a light, fast version of the
fixed-effects regression DVOA-style ratings use). The result: a team that fed on
weak defenses gets marked down, and a good team stuck with a brutal schedule gets
marked up — which research shows is meaningfully more predictive than raw EPA.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def opponent_adjust(pbp_weighted: pd.DataFrame, value: str = "epa",
                    mask: pd.Series | None = None, iters: int = 15
                    ) -> tuple[float, pd.Series, pd.Series]:
    """Return (league_mean, offense_rating, defense_rating) for ``value``.

    Ratings are in EPA/play units relative to league average, so:
      opponent-adjusted offense = league_mean + offense_rating[team]
      opponent-adjusted defense allowed = league_mean + defense_rating[team]
    (a good defense has a negative rating).
    """
    df = pbp_weighted
    if mask is not None:
        df = df[mask]
    df = df[df["posteam"].notna() & df["defteam"].notna() & df[value].notna()]
    if df.empty:
        return 0.0, pd.Series(dtype=float), pd.Series(dtype=float)

    w = df["w"].to_numpy(dtype=float)
    v = df[value].to_numpy(dtype=float)
    pos = df["posteam"].to_numpy()
    dfn = df["defteam"].to_numpy()
    league = float(np.average(v, weights=w))

    teams = pd.Index(sorted(set(pos) | set(dfn)))
    off = pd.Series(0.0, index=teams)
    dff = pd.Series(0.0, index=teams)
    pos_s, dfn_s, w_s = pd.Series(pos), pd.Series(dfn), pd.Series(w)
    wsum_off = w_s.groupby(pos_s).sum()
    wsum_def = w_s.groupby(dfn_s).sum()

    for _ in range(iters):
        resid_o = (v - league) - dfn_s.map(dff).to_numpy()
        off = (pd.Series(resid_o * w).groupby(pos_s).sum() / wsum_off).reindex(teams).fillna(0.0)
        off -= np.average(off.reindex(teams).fillna(0.0))  # center
        resid_d = (v - league) - pos_s.map(off).to_numpy()
        dff = (pd.Series(resid_d * w).groupby(dfn_s).sum() / wsum_def).reindex(teams).fillna(0.0)
        dff -= np.average(dff.reindex(teams).fillna(0.0))

    return league, off, dff


def apply_epa_adjustment(off_df: pd.DataFrame, def_df: pd.DataFrame,
                         pbp_weighted: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Overwrite overall/pass/rush EPA with opponent-adjusted values and re-rank.

    Raw values are preserved in ``*_raw`` columns.
    """
    from data.tendencies import _rank  # local import to avoid a cycle

    is_pass = pbp_weighted["pass"] == 1
    is_rush = pbp_weighted["rush"] == 1
    specs = [
        ("epa_play", None, "epa_play_rank"),
        ("pass_epa", is_pass, "pass_epa_rank"),
        ("rush_epa", is_rush, "rush_epa_rank"),
    ]
    for col, mask, rankcol in specs:
        league, off_r, def_r = opponent_adjust(pbp_weighted, "epa", mask=mask)
        if off_r.empty:
            continue
        for frame, ratings, best_high in ((off_df, off_r, True), (def_df, def_r, False)):
            if col not in frame.columns:
                continue
            frame[col + "_raw"] = frame[col]
            adj = league + ratings
            frame[col] = frame.index.to_series().map(adj).fillna(frame[col])
            frame[rankcol] = _rank(frame[col], best_high=best_high)
    return off_df, def_df
