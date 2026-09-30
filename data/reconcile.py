"""Top-down / bottom-up reconciliation — make the player props add up to the game.

A sharp desk never lets its player projections contradict its game number: the sum
of a team's players has to reconcile with what the team is expected to *do*. Two
identities anchor this, and our bottom-up projections (usage × matchup, one player
at a time) don't enforce either on their own:

  1. **Internal (exact):** every receiving yard is a passing yard, so the projected
     receivers' rec-yds should sum to (near) the QB's projected pass-yds. The top
     few pass-catchers we surface capture ~92% of a team's pass yards.

  2. **To the total (top-down):** the game total + margin imply each team's points,
     points imply scrimmage yards (~14 yds/point), and the team pass rate splits
     those into pass vs rush. The players should sum to *that*.

We correct only gross divergence — every scale is clamped to a modest band — so this
fixes contradictions (a low total sitting under a stack of big individual lines)
without steamrolling the bottom-up read. Both tiers are config-gated and return a
report so the correction is auditable, never a silent hand on the scale.
"""
from __future__ import annotations

import pandas as pd

import config

# Fraction of a team's pass yards captured by the handful of receivers we project.
_RECEIVER_CAPTURE = 0.92
# Scrimmage yards per point of implied scoring (league-ish; a coarse but stable anchor).
_YARDS_PER_POINT = 14.2
# League-average team pass share of scrimmage yards, before script.
_BASE_PASS_SHARE = 0.60


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _scale_stats(proj: dict, keys, factor: float) -> None:
    for k in keys:
        if k in proj and pd.notna(proj[k]):
            proj[k] = proj[k] * factor


def reconcile_team(team_projs: list[tuple], *, qb_id=None, implied_points: float | None = None,
                   pass_share: float | None = None) -> dict:
    """Scale a team's player projections toward the two identities, in place.

    ``team_projs``: list of ``(player_row, proj_dict)`` for one team. ``player_row``
    exposes ``.name`` (id) and ``.get('pos')``. Mutates the proj dicts and returns a
    report ``{pass_factor, rush_factor, recv_factor, ...}`` for transparency.
    """
    report: dict = {}
    if not team_projs:
        return report

    def is_qb(pl):
        return (qb_id is not None and getattr(pl, "name", None) == qb_id) or str(pl.get("pos", "")) == "QB"

    qb_proj = next((pr for pl, pr in team_projs if is_qb(pl)), None)
    recv = [(pl, pr) for pl, pr in team_projs if not is_qb(pl)]

    # --- Tier 2: anchor team pass/rush yards to the game total (top-down) --------
    if getattr(config, "RECONCILE_TO_TOTAL", True) and implied_points and implied_points > 0:
        # Preserve the model's *own* pass/rush lean (it already reflects script);
        # only correct the aggregate magnitude to the total. Derive the split from
        # the current projections, falling back to the league base if we can't.
        cur_pass = (qb_proj.get("Pass yds") or 0) if qb_proj else 0
        cur_rush0 = sum(pr.get("Rush yds", 0) or 0 for _, pr in recv)
        if pass_share is not None:
            share = float(pass_share)
        elif (cur_pass + cur_rush0) > 0:
            share = cur_pass / (cur_pass + cur_rush0)
        else:
            share = _BASE_PASS_SHARE
        share = _clamp(share, 0.45, 0.72)
        team_yds = implied_points * _YARDS_PER_POINT
        target_pass = team_yds * share
        target_rush = team_yds * (1 - share)

        if qb_proj and qb_proj.get("Pass yds"):
            f = _clamp(target_pass / qb_proj["Pass yds"], 0.88, 1.12)
            _scale_stats(qb_proj, ("Pass yds", "Pass TD"), f)
            report["pass_factor"] = round(f, 3)
        cur_rush = sum(pr.get("Rush yds", 0) or 0 for _, pr in recv)
        if cur_rush > 0:
            # projected rushers capture ~all of a team's rush yards
            f = _clamp(target_rush / cur_rush, 0.85, 1.15)
            for _, pr in recv:
                _scale_stats(pr, ("Rush yds", "Carries"), f)
            report["rush_factor"] = round(f, 3)

    # --- Tier 1: receivers' rec-yds must sum to the QB's pass-yds (internal) -----
    if getattr(config, "RECONCILE_PROPS", True) and qb_proj and qb_proj.get("Pass yds"):
        cur_recv = sum(pr.get("Rec yds", 0) or 0 for _, pr in recv)
        if cur_recv > 0:
            target_recv = _RECEIVER_CAPTURE * qb_proj["Pass yds"]
            f = _clamp(target_recv / cur_recv, 0.85, 1.15)
            for _, pr in recv:
                _scale_stats(pr, ("Rec yds", "Rec", "Targets"), f)
            report["recv_factor"] = round(f, 3)
            report["team_pass_yds"] = round(float(qb_proj["Pass yds"]), 1)
    return report
