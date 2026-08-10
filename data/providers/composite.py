"""Composite provider: blend several coverage sources into one consensus.

This is the "get the best of it all" layer. It:

1. Pulls from every child provider that has data (PFF, SumerSports, StatRankings).
2. Normalizes each onto canonical team abbreviations.
3. Blends per team with a trust-weighted average (PFF leads; free sources back
   it up), so no single source can drag a team's number around on its own.
4. Scores *agreement*: if the sources cluster tightly, confidence is High; if
   they disagree, it's Low -- surfaced in the UI so you know when to trust it.

Every child source is kept alongside the consensus (``zone_<key>`` columns) so
the blend is fully transparent, never a black box.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

from .base import COVERAGE_SCHEMA, SchemeDataProvider, SchemeUnavailable


def _confidence(zone_spread: float, n_sources: int) -> str:
    if n_sources <= 1:
        return "Single source"
    if pd.isna(zone_spread):
        return "—"
    if zone_spread <= config.SCHEME_AGREE_HIGH:
        return "High"
    if zone_spread <= config.SCHEME_AGREE_MED:
        return "Medium"
    return "Low"


class CompositeSchemeProvider(SchemeDataProvider):
    key = "composite"
    name = "Blended (multi-source)"

    def __init__(self, providers: list[SchemeDataProvider]):
        self.providers = providers

    def _trust(self, p: SchemeDataProvider) -> float:
        return float(config.SCHEME_SOURCE_TRUST.get(p.key, p.trust))

    def is_available(self) -> bool:
        return any(p.is_available() for p in self.providers)

    def _collect(self, season: int) -> dict[str, pd.DataFrame]:
        """Pull each available source, tolerating individual failures."""
        got: dict[str, pd.DataFrame] = {}
        for p in self.providers:
            if not p.is_available():
                continue
            try:
                df = p.coverage_tendencies(season)
            except SchemeUnavailable as exc:
                print(f"[composite] {p.name} unavailable: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - never let one source break the blend
                print(f"[composite] {p.name} errored: {exc}")
                continue
            if not df.empty:
                got[p.key] = df
        return got

    def coverage_tendencies(self, season: int) -> pd.DataFrame:
        sources = self._collect(season)
        if not sources:
            raise SchemeUnavailable("No coverage sources returned data.")

        key_to_trust = {p.key: self._trust(p) for p in self.providers}
        teams = sorted(set().union(*[df.index for df in sources.values()]))

        rows = []
        for team in teams:
            zones, mans, weights, snaps, present = [], [], [], [], []
            per_source = {}
            for key, df in sources.items():
                if team not in df.index:
                    continue
                z = df.loc[team].get("zone_rate", np.nan)
                m = df.loc[team].get("man_rate", np.nan)
                if pd.isna(z) and pd.isna(m):
                    continue
                if pd.isna(z) and not pd.isna(m):
                    z = 1.0 - m
                if pd.isna(m) and not pd.isna(z):
                    m = 1.0 - z
                w = key_to_trust.get(key, 1.0)
                zones.append(z); mans.append(m); weights.append(w)
                present.append(key)
                per_source[f"zone_{key}"] = z
                per_source[f"man_{key}"] = m
                s = df.loc[team].get("snaps", np.nan)
                if not pd.isna(s):
                    snaps.append(s)

            if not zones:
                continue
            wsum = sum(weights)
            zone_c = sum(z * w for z, w in zip(zones, weights)) / wsum
            man_c = sum(m * w for m, w in zip(mans, weights)) / wsum
            spread = (max(zones) - min(zones)) if len(zones) > 1 else np.nan

            row = {
                "team": team,
                "zone_rate": zone_c,
                "man_rate": man_c,
                "snaps": max(snaps) if snaps else pd.NA,
                "n_sources": len(zones),
                "zone_spread": spread,
                "confidence": _confidence(spread, len(zones)),
                "sources": ", ".join(present),
            }
            row.update(per_source)
            rows.append(row)

        out = pd.DataFrame(rows).set_index("team")
        # Guarantee the base schema is present for the rest of the app.
        for col in COVERAGE_SCHEMA:
            if col != "team" and col not in out.columns:
                out[col] = pd.NA
        return out
