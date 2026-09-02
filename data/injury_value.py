"""Injury point-values — what a missing player is worth to the spread.

The market moves a real line 1-3 points when a difference-maker sits, and it's
often slow to price backups and secondary injuries — a classic soft spot. We
already dock the QB (data/qbvalue.py); this quantifies *everyone else* who is Out
or Doubtful, by position and snap share, and subtracts it from that team's
strength so the projection reflects who's actually playing.

Values are deliberately conservative and capped — enough to nudge the number the
way sharp injury-adjusted models do, without letting one report swing a game.
"""
from __future__ import annotations

# Points a lost, full-time starter costs, by position (spread impact).
_BASE = {
    "WR": 1.2, "RB": 0.7, "TE": 0.6, "FB": 0.2,
    "T": 0.8, "OT": 0.8, "G": 0.6, "OG": 0.6, "C": 0.7, "OL": 0.7,
    "EDGE": 1.0, "DE": 0.9, "OLB": 0.8, "DT": 0.6, "NT": 0.5, "IDL": 0.6, "DL": 0.7,
    "CB": 0.9, "DB": 0.7, "S": 0.5, "FS": 0.5, "SS": 0.5,
    "LB": 0.5, "ILB": 0.5, "MLB": 0.5,
}
# Availability weight by report status. A player who is definitively out for the
# game or the season (Out/IR/PUP/Suspended) costs full value; Doubtful usually
# sits; Questionable usually plays — but a *lingering* Questionable (limited or
# non-participation in practice, week after week) plays compromised, so it earns
# a small effectiveness dock the market is slow to price.
_STATUS_W = {"Out": 1.0, "IR": 1.0, "PUP": 1.0, "Suspended": 1.0, "Doubtful": 0.6}
_LINGER_W = 0.25   # a nagging Questionable who'll play but hobbled
_CAP = 6.0         # most a single team's injuries can move our number


def _is_lingering(status: str, practice: str) -> bool:
    """A Questionable tag backed by limited / DNP practice — playing through it."""
    if status != "Questionable":
        return False
    p = (practice or "").strip().lower()
    return ("limited" in p) or ("did not" in p) or ("dnp" in p) or ("out" in p)


def player_value(pos: str, pct, status: str, practice: str = "") -> float:
    """Point value of one missing/compromised player, scaled by role and status."""
    sw = _STATUS_W.get(status, 0.0)
    if not sw and _is_lingering(status, practice):
        sw = _LINGER_W
    if not sw:
        return 0.0
    base = _BASE.get((pos or "").upper(), 0.5)
    share = 0.5 if pct is None else pct
    snap = min(max(share / 0.75, 0.3), 1.3)   # heavy starter > rotational piece
    return base * snap * sw


def injury_points(items: list[dict]) -> float:
    """Total spread points a team loses to absent + lingering players (QB excluded —
    it's already handled by the QB-value model, so we don't double-count)."""
    if not items:
        return 0.0
    total = sum(player_value(p.get("pos", ""), p.get("pct"), p.get("status", ""),
                             p.get("practice", ""))
               for p in items if p.get("pos") != "QB")
    return round(min(total, _CAP), 2)


def injury_detail(items: list[dict]) -> list[dict]:
    """Per-player point values for display (biggest first, QB excluded)."""
    rows = []
    for p in items or []:
        if p.get("pos") == "QB":
            continue
        v = player_value(p.get("pos", ""), p.get("pct"), p.get("status", ""),
                         p.get("practice", ""))
        if v > 0:
            rows.append({"name": p.get("name"), "pos": p.get("pos"),
                         "status": p.get("status"), "pts": round(v, 2),
                         "lingering": bool(p.get("lingering") or _is_lingering(
                             p.get("status", ""), p.get("practice", "")))})
    return sorted(rows, key=lambda r: r["pts"], reverse=True)


def team_injury_points(injuries: dict) -> dict:
    """team -> total injury point value, from the injuries map in extras."""
    return {t: injury_points(items) for t, items in (injuries or {}).items()}
