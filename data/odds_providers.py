"""Live-odds providers for the betting model.

The free schedule feed gives one consensus number. A live feed adds multi-book
prices (line shopping), book disagreement, movement over time, and a sharp-book
signal. This module wires up **The Odds API** (the-odds-api.com):

  1. Get a free key (~500 requests/mo) at the-odds-api.com.
  2. Put it in Streamlit secrets as ODDS_API_KEY (or the env var of the same name).
  3. The Betting tab lights up with live odds automatically.

The free tier is *current* odds only, so line movement is built by snapshotting
each pull (stored locally). True bet%/handle% sharp splits are paid; as a free
proxy we compare a recognized sharp book (Pinnacle, etc.) to the market consensus,
since sharp books move on sharp money.
"""
from __future__ import annotations

import datetime as _dt
import os
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests

from data.teams import normalize_team

_SPORT = "americanfootball_nfl"
_SNAP_DIR = Path(__file__).resolve().parents[1] / "odds_snapshots"
# Books widely regarded as sharp (they move on sharp money, not public).
SHARP_BOOKS = {"pinnacle", "circa", "circa sports", "betonline.ag", "bookmaker", "betcris"}

# The Odds API bills regions × markets per request. US books are all a US bettor
# can act on, so default to the two US regions (DK/FD/MGM/Caesars + Fanatics/ESPN
# BET/etc.) — 2 regions × 3 markets = 6 credits/pull. Override with the
# ODDS_API_REGIONS secret (e.g. "us" for the leanest 3-credit pull, or add
# uk,au,eu only if you truly want offshore numbers).
_DEFAULT_REGIONS = "us,us2"

# Last quota the API reported (from response headers), for the UI to surface.
LAST_QUOTA: dict = {}


def _regions() -> str:
    r = os.environ.get("ODDS_API_REGIONS")
    if r:
        return r
    try:
        import streamlit as st
        return st.secrets.get("ODDS_API_REGIONS") or _DEFAULT_REGIONS
    except Exception:  # noqa: BLE001
        return _DEFAULT_REGIONS


def _record_quota(resp) -> None:
    """Stash the API's remaining/used credits from the response headers."""
    try:
        h = resp.headers
        rem = h.get("x-requests-remaining")
        used = h.get("x-requests-used")
        last = h.get("x-requests-last")
        if rem is not None:
            LAST_QUOTA.update({
                "remaining": int(float(rem)),
                "used": int(float(used)) if used is not None else None,
                "last_cost": int(float(last)) if last is not None else None,
            })
    except Exception:  # noqa: BLE001 - quota headers are best-effort
        pass


def quota() -> dict:
    """Most recent {remaining, used, last_cost} the API reported, or empty."""
    return dict(LAST_QUOTA)


class LiveOddsProvider(ABC):
    name: str = "unnamed"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def current(self) -> pd.DataFrame:
        """Long frame: one row per book per game.

        Columns: away, home, book, home_spread (+ = home favored), total,
        ml_home, ml_away, commence, is_sharp.
        """

    def movement(self, away: str, home: str) -> dict:
        return {}


class NoLiveOdds(LiveOddsProvider):
    name = "none"

    def is_available(self) -> bool:
        return False

    def current(self) -> pd.DataFrame:
        return pd.DataFrame()


def _api_key() -> str | None:
    k = os.environ.get("ODDS_API_KEY")
    if k:
        return k
    try:
        import streamlit as st
        return st.secrets.get("ODDS_API_KEY")
    except Exception:  # noqa: BLE001
        return None


class TheOddsAPIProvider(LiveOddsProvider):
    name = "The Odds API"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or _api_key()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def current(self) -> pd.DataFrame:
        url = f"https://api.the-odds-api.com/v4/sports/{_SPORT}/odds"
        # Cost = regions × markets. Default us,us2 (6 credits) keeps every book a
        # US bettor can use without paying for offshore lines. Configurable via
        # the ODDS_API_REGIONS secret.
        params = {"apiKey": self.api_key, "regions": _regions(),
                  "markets": "spreads,totals,h2h", "oddsFormat": "american"}
        resp = requests.get(url, params=params, timeout=20)
        _record_quota(resp)
        resp.raise_for_status()
        df = self._normalize(resp.json())
        if not df.empty:
            self._snapshot(df)
        return df

    @staticmethod
    def _normalize(data) -> pd.DataFrame:
        rows = []
        for g in data or []:
            home = normalize_team(g.get("home_team"))
            away = normalize_team(g.get("away_team"))
            if not home or not away:
                continue
            for bk in g.get("bookmakers", []):
                title = bk.get("title", "?")
                hs = tot = mlh = mla = None
                for mkt in bk.get("markets", []):
                    for o in mkt.get("outcomes", []):
                        nm = normalize_team(o.get("name"))
                        if mkt["key"] == "spreads" and nm == home:
                            # API point negative when home favored; flip to our
                            # convention (positive = home favored).
                            hs = -o.get("point") if o.get("point") is not None else None
                        elif mkt["key"] == "totals" and o.get("name") == "Over":
                            tot = o.get("point")
                        elif mkt["key"] == "h2h":
                            if nm == home:
                                mlh = o.get("price")
                            elif nm == away:
                                mla = o.get("price")
                rows.append({"away": away, "home": home, "book": title,
                             "home_spread": hs, "total": tot, "ml_home": mlh,
                             "ml_away": mla, "commence": g.get("commence_time"),
                             "is_sharp": title.lower() in SHARP_BOOKS})
        return pd.DataFrame(rows)

    def _snapshot(self, df: pd.DataFrame) -> None:
        try:
            _SNAP_DIR.mkdir(exist_ok=True)
            stamp = _dt.datetime.utcnow().isoformat(timespec="minutes")
            out = df.copy()
            out["ts"] = stamp
            path = _SNAP_DIR / f"odds_{_dt.date.today().isoformat()}.csv"
            out.to_csv(path, mode="a", header=not path.exists(), index=False)
        except Exception:  # noqa: BLE001 - snapshots are best-effort
            pass

    def movement(self, away: str, home: str) -> dict:
        """Open (earliest snapshot today) vs current consensus home_spread/total."""
        try:
            files = sorted(_SNAP_DIR.glob("odds_*.csv")) if _SNAP_DIR.exists() else []
            if not files:
                return {}
            snaps = pd.concat([pd.read_csv(f) for f in files[-2:]], ignore_index=True)
            g = snaps[(snaps["away"] == away) & (snaps["home"] == home)]
            if g.empty or "ts" not in g.columns:
                return {}
            first_ts, last_ts = g["ts"].min(), g["ts"].max()
            first = g[g["ts"] == first_ts]["home_spread"].mean()
            last = g[g["ts"] == last_ts]["home_spread"].mean()
            if pd.isna(first) or pd.isna(last):
                return {}
            return {"open_spread": first, "current_spread": last, "delta": last - first}
        except Exception:  # noqa: BLE001
            return {}


# --- consensus / shopping helpers -------------------------------------------
def consensus(df: pd.DataFrame) -> dict:
    """Consensus + best available across books for one game's rows."""
    if df.empty:
        return {}
    hs = df["home_spread"].dropna()
    tot = df["total"].dropna()
    out = {
        "home_spread": float(hs.mean()) if not hs.empty else None,
        "total": float(tot.mean()) if not tot.empty else None,
        "n_books": int(df["book"].nunique()),
        "spread_range": (float(hs.min()), float(hs.max())) if not hs.empty else None,
        # best number for a backer: fewest points laid on home / most for away
        "best_home_spread": float(hs.min()) if not hs.empty else None,
        "best_away_spread": float(hs.max()) if not hs.empty else None,
    }
    sharp = df[df["is_sharp"]]
    if not sharp.empty and not sharp["home_spread"].dropna().empty:
        out["sharp_spread"] = float(sharp["home_spread"].dropna().mean())
        out["sharp_book"] = ", ".join(sorted(sharp["book"].unique()))
    return out


# Our prop stat names -> The Odds API market keys.
PROP_MARKETS = {
    "Pass yds": "player_pass_yds", "Pass TD": "player_pass_tds",
    "Rush yds": "player_rush_yds", "Rec yds": "player_reception_yds",
    "Rec": "player_receptions",
}


def player_props(max_events: int = 16) -> pd.DataFrame:
    """Player-prop lines from The Odds API (empty without a key or on any error).

    Long frame: player, stat (our name), line, over, under, book. Props are a
    per-event endpoint, so this fans out over the week's events. Best-of numbers
    are taken per player/stat so the finder shows the sharpest available line.
    """
    key = _api_key()
    if not key:
        return pd.DataFrame()
    try:
        ev = requests.get(f"https://api.the-odds-api.com/v4/sports/{_SPORT}/events",
                          params={"apiKey": key}, timeout=20)
        ev.raise_for_status()
        events = ev.json()[:max_events]
        markets = ",".join(sorted(set(PROP_MARKETS.values())))
        inv = {v: k for k, v in PROP_MARKETS.items()}
        rows = []
        for e in events:
            eid = e.get("id")
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{_SPORT}/events/{eid}/odds",
                params={"apiKey": key, "regions": "us", "markets": markets,
                        "oddsFormat": "american"}, timeout=20)
            if r.status_code != 200:
                continue
            for bk in r.json().get("bookmakers", []):
                book = bk.get("title", "?")
                for mkt in bk.get("markets", []):
                    stat = inv.get(mkt.get("key"))
                    if not stat:
                        continue
                    byplayer: dict = {}
                    for o in mkt.get("outcomes", []):
                        who, side = o.get("description"), o.get("name")
                        d = byplayer.setdefault(who, {"line": o.get("point")})
                        d["over" if side == "Over" else "under"] = o.get("price")
                    for who, d in byplayer.items():
                        rows.append({"player": who, "stat": stat, "line": d.get("line"),
                                     "over": d.get("over"), "under": d.get("under"), "book": book})
        return pd.DataFrame(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[odds] player props unavailable: {exc}")
        return pd.DataFrame()


def get_odds_provider() -> LiveOddsProvider:
    p = TheOddsAPIProvider()
    return p if p.is_available() else NoLiveOdds()
