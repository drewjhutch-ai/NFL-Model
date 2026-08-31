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
    """Diverging matchup-edge bars, weighted by each facet's NFL importance.

    ``edges`` = list of {label, mag, weight, impact}. Bar **length** = the raw
    matchup edge (rank differential, +offense/-defense); bar **thickness** = the
    facet's importance weight; ordered by **impact** (edge × weight). So a big
    edge in a low-value facet (e.g. RB receiving) shows as a long *thin* bar,
    while QB/passing dominates — exactly how the modern NFL values them.
    """
    import plotly.graph_objects as go

    rows = sorted(edges, key=lambda e: e.get("impact", 0), reverse=True)
    ws = [e.get("weight", 1.0) for e in rows]
    lo, hi = (min(ws), max(ws)) if ws else (1.0, 1.0)
    widths = [(0.4 + 0.5 * (w - lo) / (hi - lo)) if hi > lo else 0.6 for w in ws]

    labels = [f"{e['label']}  ×{e.get('weight', 1):g}" for e in rows]
    mags = [e["mag"] for e in rows]
    colors = ["#2ecc71" if m > 3 else ("#e74c3c" if m < -3 else "#9aa0a6") for m in mags]
    texts = [("+" if m > 0 else "") + f"{m:.0f}" for m in mags]

    fig = go.Figure(go.Bar(
        x=mags, y=labels, orientation="h", width=widths, marker=dict(color=colors),
        text=texts, textposition="outside", cliponaxis=False, hoverinfo="skip",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(range=[-34, 34], title="◄ defense edge   ·   offense edge ►   (thickness = importance)",
                   showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        yaxis=dict(autorange="reversed"),
        height=max(190, 42 * len(rows) + 66),
        margin=dict(l=10, r=10, t=40, b=34),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
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


def _dot(color: str) -> str:
    return f"<span style='color:{color};'>●</span>"


_INJ_ICON = {"Out": _dot("#e5484d"), "Doubtful": _dot("#f5a623"),
             "Questionable": _dot("#e8c04b")}


def injury_card_html(items: list[dict], week=None, has_report: bool = True) -> str:
    """Amber/red injury card, green when healthy, gray in the offseason."""
    title = "Injury report" + (f" · Wk {week}" if week else "")
    if not has_report:
        return ("<div style='background:rgba(128,128,128,0.10);border-left:4px solid "
                "#888;border-radius:8px;padding:8px 12px;'><b>Injury report</b><br>"
                "<span style='opacity:.8;font-size:0.88rem;'>Updates weekly once the "
                "season starts (no report in the offseason).</span></div>")
    if not items:
        return (f"<div style='background:rgba(46,204,113,0.10);border-left:4px solid "
                f"#2ecc71;border-radius:8px;padding:8px 12px;'><b>{title}</b><br>"
                f"<span style='opacity:.85;'>No major injuries reported.</span></div>")
    lis = ""
    for p in items:
        ic = _INJ_ICON.get(p["status"], "•")
        inj = f" — {p['injury']}" if p.get("injury") else ""
        lis += (f"<li style='margin:2px 0;'>{ic} <b>{p['name']}</b> "
                f"<span style='opacity:.7;'>({p['pos']}, {p['side']})</span> · "
                f"{p['status']}{inj} · {p['pct'] * 100:.0f}% snaps</li>")
    return (f"<div style='background:rgba(231,76,60,0.10);border-left:4px solid "
            f"#e74c3c;border-radius:8px;padding:8px 12px;'><b>{title}</b>"
            f"<ul style='margin:4px 0 0;padding-left:18px;'>{lis}</ul></div>")


def _hex_rgb(color: str):
    c = str(color).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (127, 127, 127)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return (127, 127, 127)


def _readable(color: str, min_lum: float = 0.55) -> str:
    """Lighten a too-dark color toward white so it's visible on a dark backdrop."""
    r, g, b = _hex_rgb(color)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if lum >= min_lum:
        return f"#{r:02x}{g:02x}{b:02x}"
    t = min(max((min_lum - lum) / (1 - lum + 1e-6), 0.0), 0.72)
    r = int(r + (255 - r) * t); g = int(g + (255 - g) * t); b = int(b + (255 - b) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_rgb(color)
    return f"rgba({r},{g},{b},{alpha})"


def radar_chart(categories: list[str], series: list[tuple], title: str = ""):
    """Percentile radar ('pizza') chart. series = list of (name, values, color).

    Dark team colors are auto-brightened for the stroke so they stay visible, the
    fill stays translucent so overlaps read, and the plot sits on a subtle
    backdrop with a visible grid.
    """
    import plotly.graph_objects as go
    fig = go.Figure()
    for i, (name, values, color) in enumerate(series):
        vals = list(values) + [values[0]]
        cats = categories + [categories[0]]
        stroke = _readable(color)
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=cats, name=name, mode="lines+markers",
            fill="toself", fillcolor=_rgba(stroke, 0.28 if i == 0 else 0.22),
            line=dict(color=stroke, width=3),
            marker=dict(color=stroke, size=6, line=dict(color="rgba(0,0,0,0.5)", width=1)),
            hovertemplate="%{theta}: %{r:.0f}<extra>" + str(name) + "</extra>"))
    grid = "rgba(255,255,255,0.16)"
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        polar=dict(
            bgcolor="rgba(255,255,255,0.05)",     # subtle backdrop so dark teams show
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                            gridcolor=grid, linecolor=grid),
            angularaxis=dict(gridcolor=grid, linecolor=grid,
                             tickfont=dict(size=11, color="#c9d3da"))),
        height=390, margin=dict(l=30, r=30, t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)", showlegend=len(series) > 1,
        legend=dict(orientation="h", y=-0.12, font=dict(size=12)))
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


_SPARK_TICKS = "▁▂▃▄▅▆▇█"


def unicode_spark(values: list[float]) -> str:
    """A tiny inline sparkline from block glyphs — renders anywhere text does.

    Great inside dataframes and captions where a chart can't go. Empty string if
    there isn't enough data to draw a trend.
    """
    vals = [v for v in (values or []) if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return _SPARK_TICKS[3] * len(vals)
    out = []
    for v in vals:
        idx = int(round((v - lo) / (hi - lo) * (len(_SPARK_TICKS) - 1)))
        out.append(_SPARK_TICKS[idx])
    return "".join(out)


def movement_arrow(delta, spots_word: bool = False) -> str:
    """Rank-movement chip: ▲ improved (green), ▼ slipped (red), – unchanged.

    ``delta`` is the change toward #1 since last snapshot (positive = better).
    Returns an HTML span. Empty string when there's no prior week to compare.
    """
    if delta is None or pd.isna(delta):
        return ""
    d = int(round(delta))
    if d == 0:
        return "<span style='color:#8a8a8a;'>–</span>"
    up = d > 0
    color = "#2ecc71" if up else "#e74c3c"
    glyph = "▲" if up else "▼"
    tail = " spots" if spots_word else ""
    return (f"<span style='color:{color};font-weight:600;font-size:0.85em;'>"
            f"{glyph}{abs(d)}{tail}</span>")


def sparkline_fig(values: list[float], color: str = "#1f77b4", height: int = 44):
    """A minimal Plotly sparkline (no axes/grid) for headers and cards.

    Returns ``None`` when there isn't enough data, so callers can skip cleanly.
    """
    vals = [v for v in (values or []) if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return None
    import plotly.graph_objects as go
    up = vals[-1] >= vals[0]
    line_color = color if color else ("#2ecc71" if up else "#e74c3c")
    fig = go.Figure(go.Scatter(
        y=vals, mode="lines", line=dict(color=line_color, width=2),
        fill="tozeroy", fillcolor="rgba(127,127,127,0.10)", hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=[len(vals) - 1], y=[vals[-1]], mode="markers",
        marker=dict(color=line_color, size=6), hoverinfo="skip"))
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=2, b=2), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def fmt(x, kind: str = "num") -> str:
    """Format a metric value for display."""
    if x is None or pd.isna(x):
        return "—"
    if kind == "pct":
        return f"{x * 100:.1f}%"
    if kind == "epa":
        # EPA/play is a hard-to-read tiny decimal (-0.073). Show it "per 100
        # plays" instead (-7.3) — same stat, far easier to read. 0 = average.
        return f"{x * 100:+.1f}"
    if kind == "num1":
        return f"{x:.1f}"
    return f"{x:.3f}"
