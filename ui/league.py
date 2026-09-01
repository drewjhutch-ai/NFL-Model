"""The 'League' tab — a command center for the whole NFL.

Rebuilt in the This-Week style: a state-of-the-league KPI strip, a sleek
power board (ranked rows with a net-EPA bar, tier, records, point differential,
movement, and a trend spark), the signature efficiency quadrant, and a stat
explorer whose heat tables are themed to the kit palette. Every number the old
tab had is kept; a sortable full table lives one click away.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import config
from data import betting, history, loaders, profiles
from data import sharp_value as sv
from data.providers import load_coverage
from ui import kit
from ui.components import ordinal, unicode_spark

_EPA_HELP = ("Expected Points Added per play. 0 = league average; elite offenses "
             "run +0.10 to +0.20. For defense it's points allowed/play — lower is better.")


# --- sample-size confidence --------------------------------------------------
def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    if cur.empty or "week" not in cur.columns:
        return 0
    return int(cur["week"].nunique())


def _confidence_banner(extras) -> None:
    n = _games_played(extras)
    if n == 0:
        st.warning("**Offseason / Week 1** — ranks are last season's phantom baseline until "
                   "current-season games are played. Treat everything as a prior, not a read.")
    elif n < 4:
        st.warning(f"**Small sample ({n} week{'s' if n != 1 else ''})** — early-season ranks are "
                   "noisy and regress hard. High-confidence reads come after ~Week 4.")
    elif n < 8:
        st.info(f"**{n} weeks in** — ranks are stabilizing but still firming up.")
    else:
        st.success(f"**{n} weeks of data** — the sample is mature; ranks are reliable.")


# --- records / scoring (from the schedule) -----------------------------------
def _records(schedule, season: int) -> dict:
    """team -> {W,L,T,PF,PA,G} from completed current-season games."""
    rec: dict[str, dict] = {}
    if schedule is None or schedule.empty:
        return rec
    need = {"season", "result", "home_score", "away_score", "home_team", "away_team"}
    if not need.issubset(schedule.columns):
        return rec
    g = schedule[(schedule["season"] == season) & schedule["result"].notna()
                 & schedule["home_score"].notna()]
    for _, r in g.iterrows():
        h, a, hs, as_ = r["home_team"], r["away_team"], r["home_score"], r["away_score"]
        for t in (h, a):
            rec.setdefault(t, {"W": 0, "L": 0, "T": 0, "PF": 0, "PA": 0, "G": 0})
        rec[h]["PF"] += hs; rec[h]["PA"] += as_; rec[h]["G"] += 1
        rec[a]["PF"] += as_; rec[a]["PA"] += hs; rec[a]["G"] += 1
        if hs > as_:
            rec[h]["W"] += 1; rec[a]["L"] += 1
        elif as_ > hs:
            rec[a]["W"] += 1; rec[h]["L"] += 1
        else:
            rec[h]["T"] += 1; rec[a]["T"] += 1
    return rec


def _rec_text(r: dict | None) -> str:
    if not r or r["G"] == 0:
        return ""
    base = f"{r['W']}-{r['L']}"
    return base + (f"-{r['T']}" if r["T"] else "")


# --- strength / struggle -----------------------------------------------------
def _team_sw(team, off, deff, extras) -> tuple[str, str]:
    facets = profiles.offense_facets(team, off, extras) + profiles.defense_facets(team, deff, extras)
    s, w = profiles.strengths_and_struggles(facets, n=1)

    def short(fs):
        if not fs:
            return "—"
        f = fs[0]
        return f"{f['unit']} ({profiles._ordinal(f['rank'])})"
    return short(s), short(w)


_TIERS = [(6, "Contender", "edge"), (14, "Playoff caliber", "accent"),
          (22, "In the mix", "sharp"), (32, "Rebuilding", "fade")]


def _tier(rank: int) -> tuple[str, str]:
    for cutoff, label, kind in _TIERS:
        if rank <= cutoff:
            return label, kind
    return "Rebuilding", "fade"


def _sharp_power(extras) -> pd.Series | None:
    rt = sv.epa_ratings(extras.get("sharp") or {})
    if rt.empty or "off_epa" not in rt.columns or "def_epa" not in rt.columns:
        return None
    return (rt["off_epa"] - rt["def_epa"]).rank(ascending=False, method="min")


# --- state of the league (leader strip) -------------------------------------
def _leader_card(label: str, team: str | None, value: str, metric: str, accent: str) -> str:
    meta = loaders.team_meta().get(team, {}) if team else {}
    logo = f'<img src="{meta["logo"]}" alt="{team}">' if meta.get("logo") else ""
    abbr = team or "—"
    return (f'<div class="k-lead" style="--la:var(--{accent})">'
            f'<div class="ll">{label}</div><div class="lv">{value}</div>'
            f'<div class="lt">{logo} <b>{abbr}</b> · {metric}</div></div>')


def _state_of_league(off, deff, extras, pr) -> None:
    def top(df, col, ascending):
        if df is None or getattr(df, "empty", True) or col not in df.columns:
            return None, None
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            return None, None
        t = s.sort_values(ascending=ascending).index[0]
        return t, float(s.loc[t])

    best_net = pr.sort_values("power_rank").index[0] if not pr.empty else None
    net_v = pr.loc[best_net, "net"] * 100 if best_net else None
    to_t, to_v = top(off, "epa_play", False)
    td_t, td_v = top(deff, "epa_play", True)
    po_t, po_v = top(off, "pass_epa", False)
    pd_t, pd_v = top(deff, "pass_epa", True)
    pace = extras.get("pace")
    fast_t = pace.sort_values(ascending=False).index[0] if pace is not None and len(pace) else None
    fast_v = float(pace.loc[fast_t]) if fast_t is not None else None

    cards = [
        _leader_card("Model #1", best_net, f"{net_v:+.1f}" if net_v is not None else "—",
                     "net EPA / 100", "accent"),
        _leader_card("Top offense", to_t, f"{to_v*100:+.1f}" if to_v is not None else "—",
                     "EPA / 100", "edge"),
        _leader_card("Top defense", td_t, f"{td_v*100:+.1f}" if td_v is not None else "—",
                     "EPA / 100 allowed", "edge"),
        _leader_card("Best pass O", po_t, f"{po_v*100:+.1f}" if po_v is not None else "—",
                     "pass EPA / 100", "accent"),
        _leader_card("Best pass D", pd_t, f"{pd_v*100:+.1f}" if pd_v is not None else "—",
                     "pass EPA / 100 allow", "violet"),
        _leader_card("Fastest pace", fast_t, f"{fast_v:.1f}" if fast_v is not None else "—",
                     "plays / game", "sharp"),
    ]
    st.markdown(f'<div class="k-leads">{"".join(cards)}</div>', unsafe_allow_html=True)


# --- power board (sleek rows) ------------------------------------------------
def _netbar(net_per100: float, maxabs: float) -> str:
    v = max(-maxabs, min(maxabs, net_per100))
    mag = abs(v) / maxabs * 50.0
    if v >= 0:
        fill = f"left:50%;width:{mag:.0f}%;background:var(--edge)"
    else:
        fill = f"right:50%;width:{mag:.0f}%;background:var(--fade)"
    return (f'<div class="k-nb"><span class="mid"></span>'
            f'<span class="fill" style="{fill}"></span>'
            f'<span class="nv">{net_per100:+.1f}</span></div>')


def _rank_cell(rank) -> str:
    if rank is None or pd.isna(rank):
        return '<span class="rc">—</span>'
    r = int(rank)
    cls = "rc hi" if r <= 8 else ("rc lo" if r >= 25 else "rc")
    return f'<span class="{cls}">{r}</span>'


def _spark_svg(vals: list[float], color: str, w: int = 58, h: int = 18) -> str:
    vals = [v for v in vals if v == v]  # drop NaN
    if len(vals) < 2:
        return '<span style="color:var(--ink-faint);font-size:.7rem">–</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = i / (n - 1) * (w - 3) + 1.5
        y = (h - 2) - (v - lo) / rng * (h - 4) + 1
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="1.9" fill="{color}"/></svg>')


def _power_board(off, deff, extras, teams_filter, recs) -> None:
    pr = betting.power_ratings(off, deff)
    meta = loaders.team_meta()
    weekly = history.weekly_epa(extras.get("pbp"))
    move = history.rank_movement(history.load_history(config.CURRENT_SEASON), "power_rank")
    sos = extras.get("sos")
    accent = kit.PALETTE["accent"]
    ordered = [t for t in pr.sort_values("power_rank").index if t in teams_filter]
    if not ordered:
        st.info("No teams match that filter.")
        return
    maxabs = max(10.0, max(abs(pr.loc[t, "net"] * 100) for t in ordered))

    head = ('<div class="k-pwh"><span>#</span><span></span><span class="l">Team</span>'
            '<span>Net EPA / 100</span><span>Off</span><span>Def</span><span>Pass O</span>'
            '<span>Pass D</span><span>SOS</span><span>Δ</span><span>Trend</span></div>')
    rows = ['<div class="k-pw">', head]
    for t in ordered:
        r = pr.loc[t]
        m = meta.get(t, {})
        logo = f'<img src="{m["logo"]}" alt="{t}">' if m.get("logo") else ""
        rec = _rec_text(recs.get(t))
        rec_html = f'<span class="rec">{rec}</span>' if rec else ""
        o = off.loc[t, "epa_play_rank"] if t in off.index else None
        d = deff.loc[t, "epa_play_rank"] if t in deff.index else None
        po = off.loc[t, "pass_epa_rank"] if t in off.index else None
        pdf = deff.loc[t, "pass_epa_rank"] if t in deff.index else None
        sos_v = f"{float(sos.get(t)):+.2f}" if sos is not None and t in sos.index else "—"
        mv = move.get(t, 0)
        mv_html = (f'<span class="mv" style="color:var(--edge)">▲{int(mv)}</span>' if mv > 0
                   else f'<span class="mv" style="color:var(--fade)">▼{abs(int(mv))}</span>' if mv < 0
                   else '<span class="mv" style="color:var(--ink-faint)">–</span>')
        spark = _spark_svg([v * 100 for v in history.spark_series(weekly, t, "net")], accent)
        rows.append(
            f'<div class="k-pwrow"><span class="rk">{int(r["power_rank"])}</span>{logo}'
            f'<span><span class="tm">{m.get("name", t)}</span>{rec_html}</span>'
            f'{_netbar(r["net"] * 100, maxabs)}'
            f'{_rank_cell(o)}{_rank_cell(d)}{_rank_cell(po)}{_rank_cell(pdf)}'
            f'<span class="rc">{sos_v}</span>{mv_html}'
            f'<span class="spk">{spark}</span></div>')
    rows.append("</div>")
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("Net EPA/100 is opponent-adjusted (offense − defense). Off/Def/Pass ranks: 1 = best "
               "(green top-8, red bottom-8). SOS = avg opponent net rating. Δ and trend fill in weekly.")

    with st.expander("Full sortable table — records, point differential, Sharp cross-check & more"):
        _power_table(off, deff, extras, teams_filter, recs, _sharp_power(extras), move)


def _power_table(off, deff, extras, teams_filter, recs, sharp_rank, move) -> None:
    pr = betting.power_ratings(off, deff)
    meta = loaders.team_meta()
    st_ppg, sos = extras.get("st_ppg"), extras.get("sos")
    rows = []
    for team, r in pr.sort_values("power_rank").iterrows():
        if team not in teams_filter:
            continue
        s, w = _team_sw(team, off, deff, extras)
        rec = recs.get(team) or {}
        pd_gm = round((rec["PF"] - rec["PA"]) / rec["G"], 1) if rec.get("G") else None
        rows.append({
            "Rank": int(r["power_rank"]), "Move": move.get(team, np.nan),
            "Team": meta.get(team, {}).get("name", team), "Record": _rec_text(rec) or "—",
            "Net/100": round(r["net"] * 100, 1),
            "PD/gm": pd_gm,
            "Off": int(off.loc[team, "epa_play_rank"]) if team in off.index else None,
            "Def": int(deff.loc[team, "epa_play_rank"]) if team in deff.index else None,
            "Sharp": int(sharp_rank.get(team)) if sharp_rank is not None and team in sharp_rank.index else None,
            "ST": round(float(st_ppg.get(team)), 1) if st_ppg is not None and team in st_ppg.index else None,
            "SOS": round(float(sos.get(team)), 3) if sos is not None and team in sos.index else None,
            "Strength": s, "Struggle": w,
        })
    df = pd.DataFrame(rows)
    for col in ("Move", "Sharp", "PD/gm"):
        if col in df.columns and not df[col].notna().any():
            df = df.drop(columns=col)
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Move": st.column_config.NumberColumn("Δ Wk", format="%+d") if "Move" in df.columns else None,
        "Net/100": st.column_config.NumberColumn("Net/100", format="%+.1f", help=_EPA_HELP),
        "PD/gm": st.column_config.NumberColumn("PD/gm", format="%+.1f",
            help="Point differential per game (actual scoreboard)."),
        "SOS": st.column_config.NumberColumn("SOS", format="%+.3f",
            help="Strength of schedule: average opponent net rating (played)."),
    })


# --- efficiency quadrant (kit-themed) ----------------------------------------
_PRESETS = {
    "Offense vs Defense": ("off:epa_play", "def:epa_play", "Offense (net pts / 100 plays, better →)",
                           "Defense (pts allowed / 100 plays, better ↑)", True,
                           [("Complete", "max", "min"), ("Stout D, weak O", "min", "min"),
                            ("Explosive, leaky", "max", "max"), ("Rebuilding", "min", "max")]),
    "Pass vs Rush (offense)": ("off:pass_epa", "off:rush_epa", "Pass (pts / 100 plays, better →)",
                               "Rush (pts / 100 plays, better ↑)", False, None),
    "Pass O vs Pass D": ("off:pass_epa", "def:pass_epa", "Pass offense (pts / 100, better →)",
                         "Pass defense allowed (pts / 100, better ↑)", True, None),
}


def _quadrant(off, deff, preset: str) -> None:
    import plotly.graph_objects as go
    P = kit.PALETTE
    meta = loaders.team_meta()
    xspec, yspec, xtitle, ytitle, y_rev, quad = _PRESETS[preset]

    def series(spec):
        side, col = spec.split(":")
        return (off if side == "off" else deff), col

    xdf, xcol = series(xspec)
    ydf, ycol = series(yspec)
    teams = [t for t in sorted(set(xdf.index) & set(ydf.index))
             if pd.notna(xdf.loc[t, xcol]) and pd.notna(ydf.loc[t, ycol])]
    if not teams:
        st.info("Not enough data to plot yet.")
        return
    x = [float(xdf.loc[t, xcol]) * 100 for t in teams]
    y = [float(ydf.loc[t, ycol]) * 100 for t in teams]
    colors = [meta.get(t, {}).get("color") or P["accent"] for t in teams]

    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="markers+text", text=teams, textposition="top center",
        textfont=dict(size=8, color=P["ink_faint"]),
        marker=dict(size=10, color=colors, line=dict(width=1, color="rgba(255,255,255,0.4)")),
        hovertext=teams, hoverinfo="text"))
    xspan, yspan = (max(x) - min(x)) or 1, (max(y) - min(y)) or 1
    for t, xi, yi in zip(teams, x, y):
        logo = meta.get(t, {}).get("logo")
        if logo:
            fig.add_layout_image(dict(source=logo, xref="x", yref="y", x=xi, y=yi,
                                      sizex=xspan * 0.07, sizey=yspan * 0.07,
                                      xanchor="center", yanchor="middle",
                                      sizing="contain", layer="above", opacity=0.95))
    xm, ym = sum(x) / len(x), sum(y) / len(y)
    fig.add_vline(x=xm, line_dash="dot", line_color=P["ink_faint"])
    fig.add_hline(y=ym, line_dash="dot", line_color=P["ink_faint"])
    if quad:
        for txt, xside, yside in quad:
            ax = max(x) if xside == "max" else min(x)
            ay = min(y) if yside == "min" else max(y)
            fig.add_annotation(x=ax, y=ay, text=txt, showarrow=False,
                               font=dict(size=11, color=P["ink_dim"]),
                               xanchor="right" if xside == "max" else "left",
                               yanchor="bottom" if yside == "min" else "top")
    pad_x, pad_y = xspan * 0.10, yspan * 0.10
    fig.update_layout(
        height=580, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        font=dict(color=P["ink_dim"]),
        xaxis=dict(title=xtitle, gridcolor=P["line"], zeroline=False,
                   range=[min(x) - pad_x, max(x) + pad_x]),
        yaxis=dict(title=ytitle, gridcolor=P["line"], zeroline=False,
                   autorange="reversed" if y_rev else True,
                   range=[max(y) + pad_y, min(y) - pad_y] if y_rev else [min(y) - pad_y, max(y) + pad_y]))
    st.plotly_chart(fig, width="stretch")
    st.caption("Dotted lines are league average. Logos plot each team at its true coordinates.")


# --- distributions (kit-themed) ----------------------------------------------
def _distribution(off, deff, extras) -> None:
    import plotly.graph_objects as go
    P = kit.PALETTE
    meta = loaders.team_meta()
    options = {
        "Offense (pts/100 plays)": (off, "epa_play", True, 100),
        "Defense (pts/100 allowed)": (deff, "epa_play", False, 100),
        "Pass offense (pts/100)": (off, "pass_epa", True, 100),
        "Pass defense (pts/100)": (deff, "pass_epa", False, 100),
        "Rush offense (pts/100)": (off, "rush_epa", True, 100),
        "Explosive rate (%)": (off, "explosive_rate", True, 100),
    }
    metric = st.selectbox("Metric", list(options.keys()))
    df, col, good_high, scale = options[metric]
    teams = [t for t in df.index if pd.notna(df.loc[t, col])]
    if not teams:
        st.info("No data yet.")
        return
    vals = [float(df.loc[t, col]) * scale for t in teams]
    colors = [meta.get(t, {}).get("color") or P["accent"] for t in teams]
    order = np.argsort(vals)[::-1] if good_high else np.argsort(vals)
    teams = [teams[i] for i in order]; vals = [vals[i] for i in order]
    colors = [colors[i] for i in order]
    fig = go.Figure(go.Bar(x=vals, y=teams, orientation="h", marker=dict(color=colors), hoverinfo="x+y"))
    fig.add_vline(x=float(np.mean(vals)), line_dash="dot", line_color=P["ink_dim"],
                  annotation_text="league avg")
    fig.update_layout(height=max(400, 20 * len(teams)), margin=dict(l=10, r=10, t=20, b=20),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, font=dict(color=P["ink_dim"]),
                      yaxis=dict(autorange="reversed"),
                      xaxis=dict(gridcolor=P["line"], title=metric))
    st.plotly_chart(fig, width="stretch")
    spread = max(vals) - min(vals)
    st.caption(f"League spread: {spread:.1f}. The bigger the gap from the pack, the more real "
               "the edge — clustered metrics offer little separation to bet on.")


# --- kit-themed heat tables --------------------------------------------------
def _heat(series: pd.Series, good_high: bool) -> list[str]:
    s = pd.to_numeric(series, errors="coerce")
    lo, hi = s.min(), s.max()
    rng = (hi - lo) or 1.0
    out = []
    for v in s:
        if pd.isna(v):
            out.append(""); continue
        good = (v - lo) / rng if good_high else 1 - (v - lo) / rng
        if good >= 0.5:
            a = (good - 0.5) * 2
            out.append(f"background-color:rgba(47,224,160,{0.10 + 0.34 * a:.2f})")
        else:
            a = (0.5 - good) * 2
            out.append(f"background-color:rgba(255,84,104,{0.10 + 0.34 * a:.2f})")
    return out


def _shade(df: pd.DataFrame, good_high_cols, good_low_cols, pct_cols):
    sty = df.style
    for c in good_high_cols:
        if c in df.columns:
            sty = sty.apply(lambda col: _heat(col, True), subset=[c])
    for c in good_low_cols:
        if c in df.columns:
            sty = sty.apply(lambda col: _heat(col, False), subset=[c])
    fmts = {c: "{:.1%}" for c in pct_cols if c in df.columns}
    for c in ["EPA/100", "Pass/100", "Rush/100"]:
        if c in df.columns:
            fmts[c] = lambda v: "—" if pd.isna(v) else f"{v * 100:+.1f}"
    return sty.format(fmts, na_rep="—")


def _offense_table(off) -> None:
    d = off.copy().rename(columns={"epa_play": "EPA/100", "pass_epa": "Pass/100", "rush_epa": "Rush/100",
                                   "pass_sr": "Pass SR", "rush_sr": "Rush SR", "explosive_rate": "Explosive",
                                   "neutral_pass_rate": "Neutral pass"})
    cols = ["EPA/100", "Pass/100", "Rush/100", "Pass SR", "Rush SR", "Explosive", "Neutral pass", "style"]
    d = d[[c for c in cols if c in d.columns]].rename(columns={"style": "Lean"}).sort_values("EPA/100", ascending=False)
    st.dataframe(_shade(d, ["EPA/100", "Pass/100", "Rush/100", "Pass SR", "Rush SR", "Explosive"],
                        [], ["Pass SR", "Rush SR", "Explosive", "Neutral pass"]), width="stretch")
    st.caption("EPA columns shown **per 100 plays** (0 = league average) — easier to read than the raw decimal.")


def _defense_table(deff, scheme_df) -> None:
    d = deff.copy()
    if scheme_df is not None:
        d["Zone%"] = [scheme_df.loc[t, "zone_rate"] if t in scheme_df.index else None for t in d.index]
    d = d.rename(columns={"epa_play": "EPA/100", "pass_epa": "Pass/100", "rush_epa": "Rush/100",
                          "pass_sr": "Pass SR", "rush_sr": "Rush SR", "explosive_rate": "Explosive"})
    cols = ["EPA/100", "Pass/100", "Rush/100", "Pass SR", "Rush SR", "Explosive"]
    if "Zone%" in d.columns:
        cols.append("Zone%")
    d = d[[c for c in cols if c in d.columns]].sort_values("EPA/100")
    st.dataframe(_shade(d, [], ["EPA/100", "Pass/100", "Rush/100", "Pass SR", "Rush SR", "Explosive"],
                        ["Pass SR", "Rush SR", "Explosive", "Zone%"]), width="stretch")


def _scoring_table(extras, recs) -> None:
    """Records + points for/against + differential — the scoreboard view."""
    if not recs:
        st.info("Records & scoring populate once current-season games are played.")
        return
    rows = []
    meta = loaders.team_meta()
    for t, r in recs.items():
        if r["G"] == 0:
            continue
        rows.append({"Team": meta.get(t, {}).get("name", t), "Record": _rec_text(r),
                     "PF/gm": round(r["PF"] / r["G"], 1), "PA/gm": round(r["PA"] / r["G"], 1),
                     "Diff/gm": round((r["PF"] - r["PA"]) / r["G"], 1)})
    if not rows:
        st.info("No completed games yet this season.")
        return
    d = pd.DataFrame(rows).set_index("Team").sort_values("Diff/gm", ascending=False)
    st.dataframe(_shade(d, ["PF/gm", "Diff/gm"], ["PA/gm"], []), width="stretch",
                 column_config={"PF/gm": st.column_config.NumberColumn(format="%.1f"),
                                "PA/gm": st.column_config.NumberColumn(format="%.1f"),
                                "Diff/gm": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("Actual scoreboard: points for/against per game and differential — the most predictive "
               "simple stat there is, shown next to the efficiency ranks above.")


def _situational_table(extras) -> None:
    os_ = extras.get("off_sit"); ds_ = extras.get("def_sit")
    if os_ is None or os_.empty:
        st.info("Situational data not available.")
        return
    d = pd.DataFrame(index=os_.index)
    d["3rd down O"] = os_["third_conv"]; d["Red zone O"] = os_["rz_td_rate"]
    if ds_ is not None and not ds_.empty:
        d["3rd down D allowed"] = ds_["third_conv"]; d["Red zone D allowed"] = ds_["rz_td_rate"]
    d = d.sort_values("3rd down O", ascending=False)
    st.dataframe(_shade(d, ["3rd down O", "Red zone O"], ["3rd down D allowed", "Red zone D allowed"],
                        list(d.columns)), width="stretch")


def _blitz_scheme(blitz, scheme_df) -> None:
    if not blitz.empty:
        b = blitz.copy().rename(columns={"blitz_rate": "Blitz%"})
        cols = [c for c in ["Blitz%", "avg_box"] if c in b.columns]
        st.markdown("#### Blitz rate")
        st.dataframe(_shade(b[cols].sort_values("Blitz%", ascending=False), ["Blitz%"], [], ["Blitz%"]),
                     width="stretch")
    st.markdown("#### Coverage scheme (zone/man)")
    if scheme_df is not None:
        sd = scheme_df[[c for c in ["zone_rate", "man_rate", "confidence"] if c in scheme_df.columns]].copy()
        sd = sd.rename(columns={"zone_rate": "Zone%", "man_rate": "Man%"}).sort_values("Zone%", ascending=False)
        st.dataframe(_shade(sd, [], [], ["Zone%", "Man%"]), width="stretch")
        st.caption("Blended from connected sources. Upload PFF for Cover 0–6 detail.")
    else:
        st.caption("Zone/man appears once a source is connected (weekly auto-fetch or a PFF upload).")


def _drives_table(extras) -> None:
    odr, ddr = extras.get("drives_off"), extras.get("drives_def")
    if odr is None or odr.empty:
        st.info("Drive data not available.")
        return
    d = pd.DataFrame(index=odr.index)
    d["Pts/drive (O)"] = odr["pts_per_drive"]; d["Score% (O)"] = odr["score_rate"]; d["TD% (O)"] = odr["td_rate"]
    if ddr is not None and not ddr.empty:
        d["Pts/drive allowed"] = ddr["pts_per_drive"]
    d = d.sort_values("Pts/drive (O)", ascending=False)
    st.dataframe(_shade(d, ["Pts/drive (O)", "Score% (O)", "TD% (O)"], ["Pts/drive allowed"],
                        ["Score% (O)", "TD% (O)"]), width="stretch")
    st.caption("Points per drive ties efficiency straight to scoring — a sharp favorite.")


def _turnovers_table(extras) -> None:
    to = extras.get("turnovers")
    if to is None or to.empty:
        st.info("Turnover data not available.")
        return
    d = to[["giveaways", "takeaways", "margin", "reg_margin"]].copy()
    d.columns = ["Giveaways/gm", "Takeaways/gm", "Margin/gm", "Regressed margin"]
    d = d.sort_values("Margin/gm", ascending=False)
    st.dataframe(_shade(d, ["Takeaways/gm", "Margin/gm", "Regressed margin"], ["Giveaways/gm"], []),
                 width="stretch")
    st.caption("Turnovers are ~60% luck — **Regressed margin** is the more predictive number.")


def _coaching_table(extras) -> None:
    co = extras.get("coaching")
    if co is None or co.empty:
        st.info("Coaching-tendency data (FTN charting) not available for these seasons.")
        return
    d = co[["play_action_rate", "no_huddle_rate", "motion_rate"]].copy()
    d.columns = ["Play-action%", "No-huddle%", "Motion%"]
    d = d.sort_values("Play-action%", ascending=False)
    st.dataframe(_shade(d, [], [], list(d.columns)), width="stretch")
    st.caption("How a staff plays: play-action, tempo, and pre-snap motion (FTN charting).")


def _sharp_table(extras) -> None:
    """Sharp charting league view — pace, trenches, coverage-by-position."""
    sharp = extras.get("sharp") or {}
    if not sv.available(sharp):
        st.info("Sharp Football tables populate weekly via the Action.")
        return
    meta = loaders.team_meta()
    d = pd.DataFrame(index=sorted(set(off_index(extras))))
    pace = extras.get("pace")
    if pace is not None and len(pace):
        d["Plays/gm"] = [round(float(pace.get(t)), 1) if t in pace.index else None for t in d.index]
    pr_ = sv.pass_rush_ranks(sharp); pp = sv.pass_pro_ranks(sharp)
    if not pr_.empty:
        d["Pass-rush rk"] = [int(pr_.get(t)) if t in pr_.index else None for t in d.index]
    if not pp.empty:
        d["Pass-pro rk"] = [int(pp.get(t)) if t in pp.index else None for t in d.index]
    cbp = sv.coverage_by_position(sharp)
    for pos in ("WR", "TE", "RB", "Slot"):
        col = f"ypt_{pos}"
        if col in cbp.columns:
            d[f"YPT {pos}"] = [round(float(cbp.loc[t, col]), 1) if t in cbp.index else None for t in d.index]
    d.index = [meta.get(t, {}).get("name", t) for t in d.index]
    d = d.dropna(how="all")
    if d.empty:
        st.info("No Sharp rows to show yet.")
        return
    low_good = [c for c in d.columns if "rk" in c or c.startswith("YPT")]
    high_good = [c for c in d.columns if c == "Plays/gm"]
    st.dataframe(_shade(d.sort_values(d.columns[0]), high_good, low_good, []), width="stretch")
    st.caption("Sharp Football charting. Ranks: 1 = best. YPT allowed by position: lower = tougher "
               "coverage (green), higher = softer (red) — the prop-matchup map at league scale.")


def off_index(extras):
    pace = extras.get("pace")
    return list(pace.index) if pace is not None and len(pace) else []


def _glossary() -> None:
    with st.expander("What these numbers mean"):
        st.markdown(
            "- **Net/100 & EPA/100** — efficiency as points per **100 plays** (raw EPA/play ×100). "
            "0 = league average; elite offense ≈ +10–20, good defense is negative (fewer points allowed).\n"
            "- **PD/gm** — actual point differential per game (the scoreboard).\n"
            "- **Move (Δ Wk)** — power-rank change since last week. **Trend** — weekly net-EPA path.\n"
            "- **SR** — success rate. **Explosive** — big-play rate. **YPT** — yards allowed per target.\n"
            "- Tables are heat-shaded green→red (defense reversed, since lower is better)."
        )


# --- render ------------------------------------------------------------------
def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    extras = extras or {}
    st.subheader("League — the state of the NFL")
    if off.empty and deff.empty:
        st.warning("No data loaded yet.")
        return
    schedule = extras.get("schedule")
    recs = _records(schedule, config.CURRENT_SEASON)
    pr = betting.power_ratings(off, deff)

    _state_of_league(off, deff, extras, pr)
    st.divider()
    _confidence_banner(extras)

    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))

    st.markdown("### Power board")
    meta = loaders.team_meta()
    c1, c2 = st.columns(2)
    conf_filter = c1.selectbox("Conference", ["All", "AFC", "NFC"], key="lg_conf")
    divs = ["All"] + ([f"{conf_filter} {d}" for d in ("East", "North", "South", "West")]
                      if conf_filter != "All" else [])
    div_filter = c2.selectbox("Division", divs, key="lg_div") if len(divs) > 1 else "All"
    teams_filter = {t for t in set(off.index) | set(deff.index)
                    if (conf_filter == "All" or meta.get(t, {}).get("conf") == conf_filter)
                    and (div_filter == "All" or meta.get(t, {}).get("division") == div_filter)}
    _power_board(off, deff, extras, teams_filter, recs)

    st.divider()
    st.markdown("### The efficiency quadrant")
    preset = st.radio("Chart", list(_PRESETS.keys()), horizontal=True, label_visibility="collapsed")
    _quadrant(off, deff, preset)

    st.divider()
    st.markdown("### Stat explorer")
    _glossary()
    view = st.radio("Show", ["Scoring", "Offense", "Defense", "Sharp charting", "Drives",
                             "Turnovers", "Situational", "Coaching", "Blitz / scheme", "Distributions"],
                    horizontal=True)
    if view == "Scoring":
        _scoring_table(extras, recs)
    elif view == "Offense":
        _offense_table(off)
    elif view == "Defense":
        _defense_table(deff, scheme_df)
    elif view == "Sharp charting":
        _sharp_table(extras)
    elif view == "Drives":
        _drives_table(extras)
    elif view == "Turnovers":
        _turnovers_table(extras)
    elif view == "Situational":
        _situational_table(extras)
    elif view == "Coaching":
        _coaching_table(extras)
    elif view == "Distributions":
        _distribution(off, deff, extras)
    else:
        _blitz_scheme(blitz, scheme_df)
