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


def percentile_chart(rows: list[tuple], title: str = ""):
    """Horizontal percentile bar chart from (label, value_str, rank) rows.

    Each metric becomes a bar whose length is its league percentile (100 = best,
    i.e. rank 1), colored green→red by rank, with the raw value + rank annotated.
    Returns a Plotly figure ready for ``st.plotly_chart``.
    """
    import plotly.graph_objects as go

    labels, pcts, colors, texts = [], [], [], []
    for label, value_str, rank in rows:
        labels.append(label)
        if rank is None or pd.isna(rank):
            pcts.append(0)
            colors.append(rank_color(None))
            texts.append(f"{value_str}")
        else:
            pcts.append(round((32 - int(rank)) / 31 * 100))
            colors.append(rank_color(rank))
            texts.append(f"{value_str} · {ordinal(rank)}")

    fig = go.Figure(
        go.Bar(
            x=pcts, y=labels, orientation="h",
            marker=dict(color=colors), text=texts, textposition="outside",
            cliponaxis=False, hoverinfo="skip",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        xaxis=dict(range=[0, 118], title="percentile (100 = best in NFL)",
                   showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        yaxis=dict(autorange="reversed"),
        height=max(180, 46 * len(rows) + 70),
        margin=dict(l=10, r=10, t=42, b=32),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, bargap=0.35,
    )
    return fig


def gauge_bar_html(value_pct: float, label_left: str = "Run", label_right: str = "Pass") -> str:
    """A run↔pass spectrum bar with a marker at value_pct (0-100)."""
    v = 0 if value_pct is None or pd.isna(value_pct) else max(0, min(100, value_pct))
    return f"""
    <div style="margin:6px 0 2px;">
      <div style="position:relative;height:14px;border-radius:7px;
                  background:linear-gradient(90deg,#8b5a2b,#666,#1f77b4);">
        <div style="position:absolute;left:calc({v}% - 6px);top:-3px;width:12px;height:20px;
                    background:#fff;border-radius:3px;border:2px solid #111;"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#999;">
        <span>{label_left}-heavy</span><span>{label_right}-heavy</span>
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
