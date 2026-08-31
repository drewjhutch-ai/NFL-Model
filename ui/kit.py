"""The design kit — one visual system every tab is built from.

Aesthetic: *broadcast scoreboard × trading terminal*. The calm density of a
trading terminal (monospace numerals, heat, scannable rows) with the clarity of
a Sunday scoreboard (team color used surgically, the one number that matters made
big). Dark-first and committed — this is a single-look product.

Two things live here:
  1. ``inject()`` — the global CSS: fonts, design tokens, Streamlit-chrome
     restyling, and the component classes below.
  2. small Python helpers that return HTML for the repeating components (KPI
     tiles, diverging edge bars, confidence meters, percentile rows, best-price
     rows, chips), so every tab draws the same shapes and a tweak lands app-wide.

Charts (radar / pizza / distributions) stay in ``ui/components.py`` and read the
palette from :data:`PALETTE`.
"""
from __future__ import annotations

import streamlit as st

# Palette exposed to Plotly and any chart code so graphics match the CSS.
PALETTE = {
    "ground": "#0b1116", "surface": "#121d21", "surface2": "#18262b", "line": "#25353c",
    "ink": "#e9f0f1", "ink_dim": "#93a6ad", "ink_faint": "#607277",
    "accent": "#35d0ba", "sharp": "#f2b544", "violet": "#a794f0",
    "edge": "#3fbf6f", "fade": "#e5544b",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root{
  --ground:#0b1116; --surface:#121d21; --surface-2:#18262b; --line:#25353c; --line-soft:#1c2a30;
  --ink:#e9f0f1; --ink-dim:#93a6ad; --ink-faint:#607277;
  --accent:#35d0ba; --sharp:#f2b544; --violet:#a794f0; --edge:#3fbf6f; --fade:#e5544b;
  --accent-wash:rgba(53,208,186,.12); --sharp-wash:rgba(242,181,68,.13);
  --edge-wash:rgba(63,191,111,.14); --fade-wash:rgba(229,84,75,.14); --violet-wash:rgba(167,148,240,.13);
}

/* ---- base typography ---- */
html, body, .stApp, [class*="css"]{
  font-family:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif; }
.stApp{ background:var(--ground); }
.block-container{ padding-top:2.2rem; padding-bottom:3rem; max-width:1320px; }
h1,h2,h3,h4{ font-family:'Archivo',system-ui,sans-serif; letter-spacing:-.02em; }
h1{ font-size:1.9rem; font-weight:900; } h2{ font-size:1.4rem; font-weight:800; }
h3{ font-size:1.12rem; font-weight:700; }
.mono, .stMarkdown code{ font-family:'IBM Plex Mono',ui-monospace,monospace; font-variant-numeric:tabular-nums; }
[data-testid="stCaptionContainer"]{ color:var(--ink-dim) !important; }

/* section headers get a quiet accent tick */
.stMarkdown h3{ border-left:3px solid var(--accent); padding-left:11px; margin:.6rem 0 .7rem; }

/* ---- tabs: segmented terminal bar ---- */
div[data-baseweb="tab-list"]{ gap:2px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
button[data-baseweb="tab"]{ font-weight:600; font-size:.9rem; color:var(--ink-faint); padding:9px 15px; }
button[data-baseweb="tab"]:hover{ color:var(--ink-dim); }
button[data-baseweb="tab"][aria-selected="true"]{ color:var(--ink); }
div[data-baseweb="tab-highlight"]{ background-color:var(--accent); height:2px; }

/* ---- metrics → KPI tiles ---- */
div[data-testid="stMetric"]{ background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:13px 16px; position:relative; overflow:hidden; }
div[data-testid="stMetric"]::before{ content:""; position:absolute; left:0; top:0; bottom:0;
  width:3px; background:var(--accent); }
div[data-testid="stMetricLabel"] p{ color:var(--ink-dim); font-size:.78rem; letter-spacing:.01em; }
div[data-testid="stMetricValue"]{ font-family:'IBM Plex Mono',monospace; font-weight:600;
  letter-spacing:-.01em; font-variant-numeric:tabular-nums; }
div[data-testid="stMetricDelta"]{ font-family:'IBM Plex Mono',monospace; font-size:.8rem; }

/* ---- buttons / inputs ---- */
.stButton>button{ border-radius:10px; border:1px solid var(--line); font-weight:600;
  background:var(--surface); color:var(--ink); }
.stButton>button:hover{ border-color:var(--accent); color:var(--accent); }
.stDownloadButton>button{ border-radius:10px; border:1px solid var(--line); font-weight:600; }
div[data-baseweb="select"]>div, .stNumberInput input, .stTextInput input{
  border-radius:9px !important; border-color:var(--line) !important; background:var(--surface) !important; }
div[data-baseweb="select"]>div:focus-within{ border-color:var(--accent) !important; }
div[data-testid="stSlider"] [role="slider"]{ background:var(--accent) !important; }
label p{ color:var(--ink-dim) !important; font-size:.82rem !important; }

/* ---- containers / tables ---- */
[data-testid="stDataFrame"]{ border:1px solid var(--line); border-radius:12px; }
div[data-testid="stVerticalBlockBorderWrapper"]{ border-color:var(--line) !important; border-radius:14px; }
div[data-testid="stExpander"]{ border:1px solid var(--line) !important; border-radius:12px !important; }
div[data-testid="stExpander"] summary{ font-weight:600; }
hr{ border-color:var(--line); margin:1rem 0; }
section[data-testid="stSidebar"]{ border-right:1px solid var(--line); background:var(--surface); }

/* ---- brand header ---- */
.k-brand{ display:flex; align-items:center; gap:13px; margin:0 0 4px; padding-bottom:12px;
  border-bottom:1px solid var(--line); }
.k-brand .mark{ font-size:1.15rem; color:var(--accent); }
.k-brand b{ font-family:'Archivo'; font-size:1.05rem; font-weight:800; letter-spacing:.16em; }
.k-brand .sep{ flex:1; }
.k-brand .stat{ font-family:'IBM Plex Mono',monospace; font-size:.72rem; color:var(--ink-faint);
  border:1px solid var(--line); border-radius:7px; padding:4px 9px; }
.k-brand .stat .on{ color:var(--edge); } .k-brand .stat .off{ color:var(--ink-faint); }

/* ---- KPI tile (custom) ---- */
.k-kpi{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; position:relative; overflow:hidden; height:100%; }
.k-kpi::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--kaccent,var(--accent)); }
.k-kpi .l{ font-size:.74rem; color:var(--ink-dim); }
.k-kpi .v{ font-family:'IBM Plex Mono',monospace; font-size:1.6rem; font-weight:600; letter-spacing:-.02em;
  line-height:1.25; font-variant-numeric:tabular-nums; }
.k-kpi .d{ font-family:'IBM Plex Mono',monospace; font-size:.74rem; font-weight:600; }
.up{ color:var(--edge); } .down{ color:var(--fade); } .flat{ color:var(--ink-faint); }

/* ---- diverging edge bar ---- */
.k-ebar{ display:flex; align-items:center; gap:9px; margin:8px 0; }
.k-ebar .nm{ font-size:.8rem; width:104px; color:var(--ink-dim); text-align:right; flex:none; }
.k-ebar .track{ flex:1; height:16px; background:var(--surface-2); border-radius:5px; position:relative;
  overflow:hidden; border:1px solid var(--line); }
.k-ebar .mid{ position:absolute; left:50%; top:0; bottom:0; width:1px; background:var(--ink-faint); opacity:.5; }
.k-ebar .fill{ position:absolute; top:0; bottom:0; border-radius:4px; }
.k-ebar .num{ font-family:'IBM Plex Mono',monospace; font-size:.74rem; width:38px; font-weight:600; flex:none; }
.k-ebar .det{ font-size:.72rem; color:var(--ink-faint); flex:1; }

/* ---- confidence meter ---- */
.k-meter{ height:9px; border-radius:5px;
  background:linear-gradient(90deg,var(--fade),var(--sharp),var(--edge)); position:relative; margin:11px 0 5px; }
.k-meter .pin{ position:absolute; top:-4px; width:12px; height:17px; border-radius:3px;
  background:var(--ink); border:2px solid var(--surface); transform:translateX(-6px); }
.k-mrow{ display:flex; justify-content:space-between; font-size:.7rem; color:var(--ink-faint);
  font-family:'IBM Plex Mono',monospace; }

/* ---- percentile row ---- */
.k-pc{ display:flex; align-items:center; gap:9px; margin:6px 0; font-size:.8rem; }
.k-pc .pl{ width:118px; color:var(--ink-dim); flex:none; }
.k-pc .pt{ flex:1; height:8px; background:var(--surface-2); border-radius:4px; overflow:hidden; border:1px solid var(--line); }
.k-pc .pf{ height:100%; border-radius:4px; background:linear-gradient(90deg,var(--accent),var(--edge)); }
.k-pc .pf.lo{ background:linear-gradient(90deg,var(--fade),var(--sharp)); }
.k-pc .pn{ font-family:'IBM Plex Mono',monospace; font-size:.72rem; width:34px; text-align:right; color:var(--ink); flex:none; }

/* ---- best-price row ---- */
.k-book{ display:flex; justify-content:space-between; align-items:center; padding:6px 10px;
  border-radius:7px; font-size:.82rem; margin:4px 0; border:1px solid transparent; }
.k-book .b{ color:var(--ink-dim); } .k-book .p{ font-family:'IBM Plex Mono',monospace; font-weight:600; }
.k-book.best{ background:var(--accent-wash); border-color:var(--accent); }
.k-book.best .p{ color:var(--accent); }

/* ---- chips / pills ---- */
.k-chip{ font-family:'IBM Plex Mono',monospace; font-size:.6rem; letter-spacing:.1em; text-transform:uppercase;
  font-weight:600; padding:3px 8px; border-radius:6px; white-space:nowrap; display:inline-block;
  background:var(--accent-wash); color:var(--accent); }
.k-chip.edge{ background:var(--edge-wash); color:var(--edge); }
.k-chip.fade{ background:var(--fade-wash); color:var(--fade); }
.k-chip.sharp{ background:var(--sharp-wash); color:var(--sharp); }
.k-chip.violet{ background:var(--violet-wash); color:var(--violet); }
.k-chip.mute{ background:var(--surface-2); color:var(--ink-faint); }

/* ---- generic stat card ---- */
.k-card{ background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:16px; }
.k-lbl{ font-family:'IBM Plex Mono',monospace; font-size:.6rem; letter-spacing:.13em; text-transform:uppercase;
  font-weight:600; color:var(--ink-faint); }

/* ---- slate board (Home) ---- */
.k-slate{ display:flex; flex-direction:column; gap:7px; }
.k-game{ display:grid; grid-template-columns:1.8fr 1.1fr 1.1fr 1.5fr; align-items:center; gap:12px;
  background:var(--surface); border:1px solid var(--line); border-radius:11px; padding:9px 14px; }
.k-game:hover{ border-color:var(--accent); }
.k-game .mu{ display:flex; align-items:center; gap:8px; font-weight:600; font-size:.9rem; }
.k-game .mu img{ width:22px; height:22px; object-fit:contain; }
.k-game .mu .at{ color:var(--ink-faint); font-weight:400; }
.k-game .ln{ font-family:'IBM Plex Mono',monospace; font-size:.84rem; }
.k-game .ln .mut{ color:var(--ink-faint); font-size:.72rem; }
.k-game .mini{ height:6px; border-radius:3px; position:relative;
  background:linear-gradient(90deg,var(--fade),var(--sharp),var(--edge)); }
.k-game .mini .pin{ position:absolute; top:-3px; width:9px; height:12px; border-radius:2px;
  background:var(--ink); border:2px solid var(--surface); transform:translateX(-4px); }
.k-ghead{ display:grid; grid-template-columns:1.8fr 1.1fr 1.1fr 1.5fr; gap:12px; padding:2px 14px 4px; }
.k-ghead span{ font-family:'IBM Plex Mono',monospace; font-size:.58rem; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-faint); }

/* ---- ticker (line moves / injuries) ---- */
.k-tick{ display:flex; flex-direction:column; }
.k-tick .it{ display:flex; align-items:center; gap:10px; font-size:.84rem; padding:7px 0;
  border-bottom:1px solid var(--line-soft); }
.k-tick .it:last-child{ border-bottom:none; }
.k-tick .it .dot{ width:7px; height:7px; border-radius:50%; flex:none; }
.k-tick .it .t{ color:var(--ink); } .k-tick .it .s{ color:var(--ink-dim); margin-left:auto;
  font-family:'IBM Plex Mono',monospace; font-size:.78rem; }

/* ---- bet card (top plays) ---- */
.k-bet{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 14px;
  border-left:4px solid var(--kbet,var(--accent)); margin-bottom:8px; }
.k-bet .sel{ font-weight:700; font-size:1rem; } .k-bet .meta{ color:var(--ink-faint); font-size:.78rem; }
.k-bet .row{ display:flex; align-items:center; gap:10px; margin-top:5px; font-size:.8rem; }
</style>
"""


def inject() -> None:
    """Inject the global design system. Call once at the top of the app."""
    st.markdown(_CSS, unsafe_allow_html=True)


# --- component helpers (return HTML; render with st.markdown(..., unsafe_allow_html=True)) ---
def _fmt_delta(delta, direction):
    if delta is None:
        return ""
    cls = {"up": "up", "down": "down"}.get(direction, "flat")
    arrow = {"up": "▲", "down": "▼"}.get(direction, "•")
    return f'<div class="d {cls}">{arrow} {delta}</div>'


def kpi(label: str, value: str, delta=None, direction: str | None = None,
        accent: str = "accent") -> str:
    """A KPI tile with a colored rail and optional delta. accent ∈ tokens."""
    return (f'<div class="k-kpi" style="--kaccent:var(--{accent})">'
            f'<div class="l">{label}</div><div class="v">{value}</div>'
            f'{_fmt_delta(delta, direction)}</div>')


def diverging_bar(name: str, value: float, maxabs: float = 24.0, detail: str = "") -> str:
    """A center-anchored bar: + = edge (green) right, − = fade (red) left."""
    v = max(-maxabs, min(maxabs, float(value or 0)))
    pct = abs(v) / maxabs * 50.0
    if v >= 0:
        fill = f"left:50%;width:{pct:.1f}%;background:var(--edge)"
        num = f'<span class="num up">+{v:.0f}</span>'
    else:
        fill = f"right:50%;width:{pct:.1f}%;background:var(--fade)"
        num = f'<span class="num down">{v:.0f}</span>'
    det = f'<span class="det">{detail}</span>' if detail else ""
    return (f'<div class="k-ebar"><span class="nm">{name}</span>'
            f'<div class="track"><span class="mid"></span>'
            f'<span class="fill" style="{fill}"></span></div>{num}{det}</div>')


def meter(score: float, label: str = "") -> str:
    """A 0–100 confidence meter with a pin."""
    pin = max(2.0, min(98.0, float(score or 0)))
    return (f'<div class="k-meter"><span class="pin" style="left:{pin:.0f}%"></span></div>'
            f'<div class="k-mrow"><span>thin</span><span>{label}</span><span>lock</span></div>')


def percentile_row(label: str, pct: float, rank=None, low_is_bad: bool = True) -> str:
    """A labeled percentile bar. pct in 0–1 (or 0–100); rank shown at right."""
    w = pct * 100 if pct <= 1 else pct
    w = max(2.0, min(100.0, w))
    lo = " lo" if (low_is_bad and w < 34) else ""
    rn = f'<span class="pn">{rank}</span>' if rank is not None else ""
    return (f'<div class="k-pc"><span class="pl">{label}</span>'
            f'<div class="pt"><span class="pf{lo}" style="width:{w:.0f}%"></span></div>{rn}</div>')


def best_price_row(book: str, price: str, best: bool = False) -> str:
    star = " ★" if best else ""
    cls = " best" if best else ""
    return (f'<div class="k-book{cls}"><span class="b">{book}</span>'
            f'<span class="p">{price}{star}</span></div>')


def chip(text: str, kind: str = "accent") -> str:
    """A monospace status pill. kind ∈ accent|edge|fade|sharp|violet|mute."""
    return f'<span class="k-chip {kind}">{text}</span>'


def heat_bg(rank, total: int = 32) -> str:
    """Background color for a 1..total rank cell (green best → red worst)."""
    if rank is None:
        return "transparent"
    import pandas as pd
    if pd.isna(rank):
        return "transparent"
    p = 1 - (float(rank) - 1) / max(total - 1, 1)   # 1 best → 0 worst
    if p >= 0.5:
        a = (p - 0.5) * 2
        return f"rgba(63,191,111,{0.10 + 0.38 * a:.2f})"
    a = (0.5 - p) * 2
    return f"rgba(229,84,75,{0.10 + 0.38 * a:.2f})"


def brand_header(week_txt: str, live: bool) -> str:
    dot = '<span class="on">● live</span>' if live else '<span class="off">○ offseason</span>'
    return (f'<div class="k-brand"><span class="mark">◆</span>'
            f'<b>NFL MODEL</b><span class="sep"></span>'
            f'<span class="stat">{week_txt}</span>'
            f'<span class="stat">{dot}</span></div>')
