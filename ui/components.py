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
                   showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False,
                   tickvals=[0, 25, 50, 75, 100]),
        yaxis=dict(autorange="reversed"),
        height=max(180, 46 * len(rows) + 70),
        margin=dict(l=10, r=10, t=42, b=32),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, bargap=0.35,
    )
    # league-average reference
    fig.add_vline(x=50, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    return fig


def edge_bar_chart(edges: list[dict], title: str = ""):
    """Diverging horizontal bars of matchup edges (green = offense, red = defense).

    ``edges`` = list of {label, mag} with mag roughly -31..+31. Sorted so the
    biggest offense edge is on top.
    """
    import plotly.graph_objects as go

    rows = sorted(edges, key=lambda e: e["mag"])  # plotly draws bottom->top
    labels = [e["label"] for e in rows]
    mags = [e["mag"] for e in rows]
    colors = ["#2ecc71" if m > 3 else ("#e74c3c" if m < -3 else "#9aa0a6") for m in mags]
    texts = [("+" if m > 0 else "") + f"{m:.0f}" for m in mags]

    fig = go.Figure(go.Bar(
        x=mags, y=labels, orientation="h", marker=dict(color=colors),
        text=texts, textposition="outside", cliponaxis=False, hoverinfo="skip",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(range=[-34, 34], title="◄ defense edge   ·   offense edge ►",
                   showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        yaxis=dict(autorange="reversed"),
        height=max(180, 40 * len(rows) + 60),
        margin=dict(l=10, r=10, t=40, b=32),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, bargap=0.3,
    )
    fig.add_vline(x=0, line_color="rgba(128,128,128,0.6)")
    return fig


def edge_meter_html(away: str, home: str, away_net: float, home_net: float) -> str:
    """A centered meter showing which side's attack has the bigger edge."""
    diff = home_net - away_net           # >0 favors home
    pos = max(0, min(100, 50 + diff * 2.2))  # map to 0-100, clamp
    fav = home if diff > 0 else away
    return f"""
    <div style="margin:4px 0 2px;">
      <div style="position:relative;height:16px;border-radius:8px;
                  background:linear-gradient(90deg,#e74c3c,#444,#2ecc71);opacity:.85;">
        <div style="position:absolute;left:calc({pos}% - 7px);top:-4px;width:14px;height:24px;
                    background:#fff;border-radius:3px;border:2px solid #111;"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#bbb;margin-top:2px;">
        <span>◄ {away}</span><span><b>lean: {fav}</b></span><span>{home} ►</span>
      </div>
    </div>
    """


def sw_card_html(title: str, items: list[str], kind: str = "strength") -> str:
    """A tinted callout card for Strengths (green) or Struggles (red)."""
    tint = "rgba(46,204,113,0.12)" if kind == "strength" else "rgba(231,76,60,0.12)"
    edge = "#2ecc71" if kind == "strength" else "#e74c3c"
    if items:
        lis = "".join(f"<li style='margin:3px 0;'>{it}</li>" for it in items)
        body = f"<ul style='margin:0;padding-left:18px;'>{lis}</ul>"
    else:
        body = "<div style='opacity:.6;font-size:0.85rem;'>Nothing notable.</div>"
    return (f"<div style='background:{tint};border-left:4px solid {edge};"
            f"border-radius:8px;padding:8px 12px;height:100%;'>"
            f"<div style='font-weight:700;margin-bottom:4px;'>{title}</div>{body}</div>")


def facet_html(f: dict) -> str:
    """'<b>Coverage</b> — covering pass-catching RBs (30th)'."""
    return f"<b>{f['unit']}</b> — {f['detail']} ({ordinal(f['rank'])})"


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
