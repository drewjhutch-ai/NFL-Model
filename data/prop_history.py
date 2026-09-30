"""Banked book prop lines — the dataset the prop-side tuner needs.

The self-tuning loop can grade sides against results because we store the closing
spread. It can't grade the player-prop market-blend (``PROP_MODEL_TRUST``) the same
way, because that needs the *book's prop lines* at pick time and the free odds feed
only ever returns *current* lines — nothing historical to look back on.

So we bank them ourselves: ``scripts/snapshot_prop_lines.py`` writes each week's
posted prop lines here, one file per week:

    prop_line_history/props_<season>_w<week>.csv

Once enough weeks accrue (``tuning.MIN_PROP_WEEKS``), the loop can de-vig those
banked lines, compare them to what actually happened, and fit the blend. Until
then it holds the safe default and says how many weeks are in the bank.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "prop_line_history"


def dir_path() -> Path:
    return _DIR


def path_for(season: int, week: int) -> Path:
    return _DIR / f"props_{season}_w{int(week):02d}.csv"


def weeks_available(season: int) -> int:
    """How many distinct weeks of prop lines are banked for a season."""
    if not _DIR.exists():
        return 0
    return len(list(_DIR.glob(f"props_{season}_w*.csv")))


def load(season: int, week: int | None = None) -> pd.DataFrame:
    """Banked prop lines for a season (one week, or all weeks concatenated)."""
    if not _DIR.exists():
        return pd.DataFrame()
    files = [path_for(season, week)] if week is not None \
        else sorted(_DIR.glob(f"props_{season}_w*.csv"))
    frames = []
    for f in files:
        try:
            if f.exists():
                frames.append(pd.read_csv(f))
        except Exception:  # noqa: BLE001 - a bad file must never break a read
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
