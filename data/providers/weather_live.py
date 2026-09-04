"""Live game-day wind/temperature forecast — the piece the schedule can't give.

nflverse fills a game's wind/temp only AFTER it's played, so upcoming games carry
none and the model applies no weather. Wind is the biggest totals mover in the
NFL, so this pulls a forecast for each open-air stadium at kickoff from Open-Meteo
(free, no API key, generous limits — no quota worry like the odds feed) and fills
wind/temp onto the schedule row, where every consumer (totals, sim, TDs, props)
already reacts to it.

Reachable from Streamlit Cloud and the Action; any failure degrades to no forecast
(the model simply reverts to weather-neutral for that game).
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import requests

from data import stadiums

_URL = "https://api.open-meteo.com/v1/forecast"
_MEMO: dict = {}          # (lat, lon) -> hourly forecast DataFrame (per process/run)
_HORIZON_DAYS = 16        # Open-Meteo forecast reach


def _fetch(lat: float, lon: float) -> pd.DataFrame:
    key = (round(lat, 3), round(lon, 3))
    if key in _MEMO:
        return _MEMO[key]
    try:
        r = requests.get(_URL, params={
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_gusts_10m,temperature_2m",
            "wind_speed_unit": "mph", "temperature_unit": "fahrenheit",
            "timezone": "auto", "forecast_days": _HORIZON_DAYS,
        }, timeout=15)
        r.raise_for_status()
        h = r.json().get("hourly", {})
        df = pd.DataFrame({
            "time": pd.to_datetime(h.get("time", [])),
            "wind": h.get("wind_speed_10m", []),
            "gust": h.get("wind_gusts_10m", []),
            "temp": h.get("temperature_2m", []),
        })
    except Exception:  # noqa: BLE001 - degrade to no forecast
        df = pd.DataFrame()
    _MEMO[key] = df
    return df


def _kickoff(row: pd.Series):
    gd = row.get("gameday")
    if pd.isna(gd):
        return None
    try:
        d = pd.to_datetime(gd).date()
    except Exception:  # noqa: BLE001
        return None
    gt = str(row.get("gametime") or "").strip()
    hour, minute = 13, 0
    if ":" in gt:
        try:
            hour, minute = int(gt.split(":")[0]), int(gt.split(":")[1])
        except Exception:  # noqa: BLE001
            pass
    return _dt.datetime(d.year, d.month, d.day, hour, minute)


def game_conditions(home_team: str, row: pd.Series) -> dict:
    """{wind, gust, temp} forecast at kickoff for an open-air game, or {}."""
    if not stadiums.is_wind_exposed(home_team):
        return {}
    c = stadiums.coords(home_team)
    ko = _kickoff(row)
    if c is None or ko is None:
        return {}
    if ko.date() - _dt.date.today() > _dt.timedelta(days=_HORIZON_DAYS) or ko.date() < _dt.date.today():
        return {}   # outside the forecast window (or already past)
    fc = _fetch(*c)
    if fc.empty:
        return {}
    idx = (fc["time"] - pd.Timestamp(ko)).abs().idxmin()
    r = fc.loc[idx]
    return {"wind": float(r["wind"]), "gust": float(r["gust"]), "temp": float(r["temp"])}


def enrich_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    """Fill wind/temp (+ wind_gust) on upcoming open-air games missing them."""
    if schedule is None or schedule.empty or "home_team" not in schedule.columns:
        return schedule
    out = schedule.copy()
    for col in ("wind", "temp", "wind_gust"):
        if col not in out.columns:
            out[col] = pd.NA
    unplayed = out["result"].isna() if "result" in out.columns else pd.Series(True, index=out.index)
    for i, row in out[unplayed].iterrows():
        if pd.notna(row.get("wind")):
            continue
        cond = game_conditions(row["home_team"], row)
        if cond:
            out.at[i, "wind"] = cond["wind"]
            out.at[i, "wind_gust"] = cond["gust"]
            if pd.isna(row.get("temp")):
                out.at[i, "temp"] = cond["temp"]
    return out
