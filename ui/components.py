"""Small shared UI helpers for rendering ranks and metrics consistently."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ordinal(n) -> str:
    """1 -> '1st', 2 -> '2nd', 32 -> '32nd'. Blank for missing."""
    if n is None or (isinstance(n, float) and np.isnan(n)) or pd.isna(n):
        return "—"
    n = int(n)
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def rank_color(rank, total: int = 32) -> str:
    """Green (elite) -> red (poor) for a 1..total rank. Returns a hex string."""
    if rank is None or pd.isna(rank):
        return "#666666"
    frac = (int(rank) - 1) / max(total - 1, 1)  # 0 = best, 1 = worst
    # interpolate green (46,204,113) -> yellow (241,196,15) -> red (231,76,60)
    if frac < 0.5:
        t = frac / 0.5
        r = int(46 + t * (241 - 46))
        g = int(204 + t * (196 - 204))
        b = int(113 + t * (15 - 113))
    else:
        t = (frac - 0.5) / 0.5
        r = int(241 + t * (231 - 241))
        g = int(196 + t * (76 - 196))
        b = int(15 + t * (60 - 15))
    return f"#{r:02x}{g:02x}{b:02x}"


def rank_badge_html(label: str, value: str, rank, total: int = 32) -> str:
    """A compact metric card: label, value, and a color-coded rank chip."""
    color = rank_color(rank, total)
    return f"""
    <div style="border:1px solid #333;border-radius:10px;padding:10px 14px;margin:4px 0;">
      <div style="font-size:0.8rem;color:#aaa;">{label}</div>
      <div style="display:flex;align-items:baseline;justify-content:space-between;">
        <span style="font-size:1.35rem;font-weight:600;">{value}</span>
        <span style="background:{color};color:#111;border-radius:6px;
                     padding:2px 8px;font-weight:700;font-size:0.85rem;">
          {ordinal(rank)}
        </span>
      </div>
    </div>
    """


def fmt(x, kind: str = "num") -> str:
    """Format a metric value for display."""
    if x is None or pd.isna(x):
        return "—"
    if kind == "pct":
        return f"{x * 100:.1f}%"
    if kind == "epa":
        return f"{x:+.3f}"
    if kind == "num1":
        return f"{x:.1f}"
    return f"{x:.3f}"
