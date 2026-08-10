"""Team abbreviation normalization.

Different sources spell teams differently -- nflverse uses "LAR", one site says
"Rams", another "LA" or "St. Louis". Everything gets funneled to the canonical
nflverse abbreviation so multi-source data merges cleanly.
"""
from __future__ import annotations

# Canonical nflverse abbreviations.
CANONICAL = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
    "TEN", "WAS",
}

# Full names / cities / nicknames / alternate abbreviations -> canonical.
_ALIASES = {
    # Arizona
    "arizona cardinals": "ARI", "cardinals": "ARI", "arizona": "ARI", "arz": "ARI",
    # Atlanta
    "atlanta falcons": "ATL", "falcons": "ATL", "atlanta": "ATL",
    # Baltimore
    "baltimore ravens": "BAL", "ravens": "BAL", "baltimore": "BAL", "blt": "BAL",
    # Buffalo
    "buffalo bills": "BUF", "bills": "BUF", "buffalo": "BUF",
    # Carolina
    "carolina panthers": "CAR", "panthers": "CAR", "carolina": "CAR",
    # Chicago
    "chicago bears": "CHI", "bears": "CHI", "chicago": "CHI",
    # Cincinnati
    "cincinnati bengals": "CIN", "bengals": "CIN", "cincinnati": "CIN",
    # Cleveland
    "cleveland browns": "CLE", "browns": "CLE", "cleveland": "CLE", "clv": "CLE",
    # Dallas
    "dallas cowboys": "DAL", "cowboys": "DAL", "dallas": "DAL",
    # Denver
    "denver broncos": "DEN", "broncos": "DEN", "denver": "DEN",
    # Detroit
    "detroit lions": "DET", "lions": "DET", "detroit": "DET",
    # Green Bay
    "green bay packers": "GB", "packers": "GB", "green bay": "GB", "gnb": "GB",
    # Houston
    "houston texans": "HOU", "texans": "HOU", "houston": "HOU", "hst": "HOU",
    # Indianapolis
    "indianapolis colts": "IND", "colts": "IND", "indianapolis": "IND",
    # Jacksonville
    "jacksonville jaguars": "JAX", "jaguars": "JAX", "jacksonville": "JAX", "jac": "JAX",
    # Kansas City
    "kansas city chiefs": "KC", "chiefs": "KC", "kansas city": "KC", "kan": "KC",
    # Las Vegas / Oakland
    "las vegas raiders": "LV", "raiders": "LV", "las vegas": "LV", "oakland": "LV",
    "oak": "LV", "lvr": "LV",
    # LA Chargers / San Diego
    "los angeles chargers": "LAC", "la chargers": "LAC", "chargers": "LAC",
    "san diego chargers": "LAC", "san diego": "LAC", "sd": "LAC", "sdg": "LAC",
    # LA Rams / St. Louis
    "los angeles rams": "LAR", "la rams": "LAR", "rams": "LAR",
    "st. louis rams": "LAR", "st louis rams": "LAR", "st. louis": "LAR",
    "st louis": "LAR", "stl": "LAR", "la": "LAR",
    # Miami
    "miami dolphins": "MIA", "dolphins": "MIA", "miami": "MIA",
    # Minnesota
    "minnesota vikings": "MIN", "vikings": "MIN", "minnesota": "MIN",
    # New England
    "new england patriots": "NE", "patriots": "NE", "new england": "NE", "nwe": "NE",
    # New Orleans
    "new orleans saints": "NO", "saints": "NO", "new orleans": "NO", "nor": "NO",
    # NY Giants
    "new york giants": "NYG", "giants": "NYG", "ny giants": "NYG",
    # NY Jets
    "new york jets": "NYJ", "jets": "NYJ", "ny jets": "NYJ",
    # Philadelphia
    "philadelphia eagles": "PHI", "eagles": "PHI", "philadelphia": "PHI",
    # Pittsburgh
    "pittsburgh steelers": "PIT", "steelers": "PIT", "pittsburgh": "PIT",
    # San Francisco
    "san francisco 49ers": "SF", "49ers": "SF", "niners": "SF",
    "san francisco": "SF", "sfo": "SF",
    # Seattle
    "seattle seahawks": "SEA", "seahawks": "SEA", "seattle": "SEA",
    # Tampa Bay
    "tampa bay buccaneers": "TB", "buccaneers": "TB", "bucs": "TB",
    "tampa bay": "TB", "tam": "TB",
    # Tennessee
    "tennessee titans": "TEN", "titans": "TEN", "tennessee": "TEN",
    # Washington
    "washington commanders": "WAS", "commanders": "WAS", "washington": "WAS",
    "washington football team": "WAS", "washington redskins": "WAS", "wsh": "WAS",
}


def normalize_team(value: str) -> str | None:
    """Return the canonical nflverse abbreviation for any team spelling.

    Returns ``None`` if it can't be resolved (caller decides whether to drop it).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    up = s.upper()
    if up in CANONICAL:
        return up
    return _ALIASES.get(s.lower())
