"""Scheme-data providers (zone/man coverage, advanced blitz, etc.).

The free nflverse data can't tell you how much a defense plays zone vs. man --
that's charting data behind a paid wall (PFF, SIS, Sportradar, SportsDataIO…).
This package defines a single interface the dashboard talks to, so whichever
paid feed you buy plugs in without touching the rest of the app.
"""
from .base import SchemeDataProvider, SchemeUnavailable
from .manual_csv import ManualCSVProvider

__all__ = ["SchemeDataProvider", "SchemeUnavailable", "ManualCSVProvider", "get_provider"]


def get_provider() -> SchemeDataProvider:
    """Return the active scheme provider.

    Swap this out (or read from config/secrets) once you've chosen a paid feed.
    Until then it returns the CSV-drop provider, which reports 'unavailable'
    unless you've placed a coverage CSV in ``scheme_data/``.
    """
    return ManualCSVProvider()
