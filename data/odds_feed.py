"""One shared, cached live-odds pull — quota-frugal.

Both the Betting desk and the CLV tab need the same multi-book odds. Routing
them through a single ``@st.cache_data`` function means opening both tabs (or
re-running the app) pulls the API **once** per cache window instead of once per
tab — each pull costs real credits on The Odds API's free tier.

The cache window is deliberately long (10 min): game lines don't move fast
enough to justify burning quota on tighter polling. A manual refresh clears it.
A low-quota guard refuses to auto-pull when the remaining monthly credits fall
below a floor, so an idle tab can never drain the last of the month's quota —
the user can still force a pull with the refresh button.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import odds_providers as op

# Stop auto-pulling when fewer than this many monthly credits remain. The manual
# refresh button bypasses it (force=True), so the user stays in control.
_QUOTA_FLOOR = 30


@st.cache_data(ttl=600, show_spinner="Pulling live multi-book odds…")
def _pull() -> tuple[pd.DataFrame, str]:
    prov = op.get_odds_provider()
    if not prov.is_available():
        return pd.DataFrame(), "no_key"
    try:
        df = prov.current()
    except Exception as exc:  # noqa: BLE001 - network/quota issues degrade to empty
        return pd.DataFrame(), f"error:{exc}"
    return (df, "ok") if not df.empty else (pd.DataFrame(), "empty")


def fetch(force: bool = False) -> tuple[pd.DataFrame, str]:
    """Return (odds, status). status ∈ ok | no_key | empty | low_quota | error:<msg>.

    Skips the API when remaining quota is below the floor unless ``force``.
    """
    if not force:
        rem = op.quota().get("remaining")
        if rem is not None and rem < _QUOTA_FLOOR:
            return pd.DataFrame(), "low_quota"
    return _pull()


def clear() -> None:
    _pull.clear()


def quota() -> dict:
    return op.quota()
