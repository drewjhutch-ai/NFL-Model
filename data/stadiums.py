"""Home-stadium coordinates and roof type — for the live wind forecast.

Only open-air stadiums get a wind adjustment. Fixed domes never do; retractable
roofs are treated as no-wind because teams almost always close them in bad
weather (the conservative call — better to miss a rare open-roof wind game than
to invent wind at a closed one). The per-game schedule ``roof`` still overrides:
a game the feed marks dome/closed reads as indoors regardless.
"""
from __future__ import annotations

# team -> (lat, lon, wind_exposed)
STADIUMS: dict[str, tuple[float, float, bool]] = {
    "ARI": (33.5277, -112.2626, False),   # State Farm — retractable
    "ATL": (33.7554, -84.4008, False),    # Mercedes-Benz — retractable/dome
    "BAL": (39.2780, -76.6227, True),
    "BUF": (42.7738, -78.7870, True),     # notoriously windy
    "CAR": (35.2258, -80.8528, True),
    "CHI": (41.8623, -87.6167, True),     # lakefront wind
    "CIN": (39.0954, -84.5160, True),
    "CLE": (41.5061, -81.6995, True),     # lakefront wind
    "DAL": (32.7473, -97.0945, False),    # AT&T — retractable
    "DEN": (39.7439, -105.0201, True),
    "DET": (42.3400, -83.0456, False),    # Ford Field — dome
    "GB": (44.5013, -88.0622, True),      # cold/wind
    "HOU": (29.6847, -95.4107, False),    # NRG — retractable
    "IND": (39.7601, -86.1639, False),    # Lucas Oil — retractable
    "JAX": (30.3239, -81.6373, True),
    "KC": (39.0489, -94.4839, True),
    "LV": (36.0909, -115.1830, False),    # Allegiant — dome
    "LAC": (33.9535, -118.3392, False),   # SoFi — roofed
    "LAR": (33.9535, -118.3392, False),   # SoFi — roofed
    "MIA": (25.9580, -80.2389, True),
    "MIN": (44.9736, -93.2575, False),    # U.S. Bank — dome
    "NE": (42.0909, -71.2643, True),
    "NO": (29.9511, -90.0812, False),     # Superdome — dome
    "NYG": (40.8135, -74.0745, True),
    "NYJ": (40.8135, -74.0745, True),
    "PHI": (39.9008, -75.1675, True),
    "PIT": (40.4468, -80.0158, True),
    "SF": (37.4030, -121.9700, True),
    "SEA": (47.5952, -122.3316, True),
    "TB": (27.9759, -82.5033, True),
    "TEN": (36.1665, -86.7713, True),
    "WAS": (38.9077, -76.8645, True),
}


def is_wind_exposed(team: str) -> bool:
    s = STADIUMS.get(team)
    return bool(s and s[2])


def coords(team: str):
    s = STADIUMS.get(team)
    return (s[0], s[1]) if s else None
