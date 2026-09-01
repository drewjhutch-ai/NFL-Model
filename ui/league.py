"""The 'League' tab: power rankings, the efficiency quadrant, and stat tables.

Built the way the best public sites present team efficiency — a tiered power
ranking (opponent-adjusted net EPA) with week-over-week movement and a season
trend, the signature offense-vs-defense quadrant plotted with team logos, and
heatmap-shaded, filterable stat tables. A sample-size banner keeps early-season
noise honest. Coverage/scheme columns light up when a source is connected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import config
from data import betting, history, loaders, profiles, tendencies
from data.providers import load_coverage

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


def _tier(rank: int) -> str:
    if rank <= 6:
        return "Contender"
    if rank <= 14:
        return "Playoff caliber"
    if rank <= 22:
        return "In the mix"
    return "Rebuilding"


def _power_rankings(off, deff, extras, conf_filter, div_filter) -> None:
    pr = betting.power_ratings(off, deff)
    meta = loaders.team_meta()
    st_ppg = extras.get("st_ppg")
    sos = extras.get("sos")
    weekly = history.weekly_epa(extras.get("pbp"))
    hist = history.load_history(config.CURRENT_SEASON)
    move = history.rank_movement(hist, "power_rank")
    # Sharp's independent power rank (charted EPA) as a cross-check on ours.
    from data import sharp_value as sv
    sharp_rt = sv.epa_ratings(extras.get("sharp") or {})
    sharp_rank = None
    if not sharp_rt.empty and "off_epa" in sharp_rt.columns and "def_epa" in sharp_rt.columns:
        sharp_rank = (sharp_rt["off_epa"] - sharp_rt["def_epa"]).rank(ascending=False, method="min")
    rows = []
    for team, r in pr.sort_values("power_rank").iterrows():
        m = meta.get(team, {})
        if conf_filter != "All" and m.get("conf") != conf_filter:
            continue
        if div_filter != "All" and m.get("division") != div_filter:
            continue
        s, w = _team_sw(team, off, deff, extras)
        rows.append({
            "Rank": int(r["power_rank"]),
            "Move": move.get(team, np.nan),
            "Logo": m.get("logo", ""),
            "Team": m.get("name", team),
            "Trend": [round(v * 100, 1) for v in history.spark_series(weekly, team, "net")],
            "Tier": _tier(int(r["power_rank"])),
            "Net EPA": round(r["net"] * 100, 1),
            "Off": int(off.loc[team, "epa_play_rank"]) if team in off.index else None,
            "Def": int(deff.loc[team, "epa_play_rank"]) if team in deff.index else None,
            "Sharp": int(sharp_rank.get(team)) if sharp_rank is not None and team in sharp_rank.index else None,
            "ST": round(float(st_ppg.get(team)), 1) if st_ppg is not None and team in st_ppg.index else None,
            "SOS": round(float(sos.get(team)), 3) if sos is not None and team in sos.index else None,
            "Strength": s,
            "Struggle": w,
        })
    if not rows:
        st.info("No teams match that filter.")
        return
    df = pd.DataFrame(rows)
    has_move = df["Move"].notna().any()
    if not has_move:
        df = df.drop(columns=["Move"])
    if "Sharp" in df.columns and not df["Sharp"].notna().any():
        df = df.drop(columns=["Sharp"])
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Logo": st.column_config.ImageColumn(" ", width="small"),
        "Sharp": st.column_config.NumberColumn("Sharp", help="Sharp Football's independent power rank "
            "(charted EPA) — a cross-check on ours. Big gaps flag disagreement worth a look."),
        "Move": st.column_config.NumberColumn("Δ Wk", format="%+d",
            help="Power-rank change since last week (+ = climbing)") if has_move else None,
        "Trend": st.column_config.AreaChartColumn(
            "Trend", help="Weekly net-EPA trajectory — left = early season, right = recent. "
            "Rising line = improving.", width="small"),
        "Net EPA": st.column_config.NumberColumn("Net/100", format="%+.1f",
            help="Opponent-adjusted net EPA per 100 plays (offense minus defense). 0 = average."),
        "Off": st.column_config.NumberColumn("Off", help="Offensive efficiency rank"),
        "Def": st.column_config.NumberColumn("Def", help="Defensive efficiency rank"),
        "ST": st.column_config.NumberColumn("ST", format="%+.1f", help="Special-teams points/game"),
        "SOS": st.column_config.NumberColumn("SOS", format="%+.3f",
            help="Strength of schedule: average opponent net rating (played)."),
    })
    if not has_move:
        st.caption("↕ A weekly **Move** column (rank change) appears once the season logs two weeks.")


# --- efficiency quadrant (with logos + presets) ------------------------------
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
    meta = loaders.team_meta()
    xspec, yspec, xtitle, ytitle, y_rev, quad = _PRESETS[preset]

    def series(spec):
        side, col = spec.split(":")
        df = off if side == "off" else deff
        return df, col

    xdf, xcol = series(xspec)
    ydf, ycol = series(yspec)
    teams = [t for t in sorted(set(xdf.index) & set(ydf.index))
             if pd.notna(xdf.loc[t, xcol]) and pd.notna(ydf.loc[t, ycol])]
    if not teams:
        st.info("Not enough data to plot yet.")
        return
    # EPA columns are tiny decimals; plot them per-100-plays so the axis reads
    # in whole numbers (-10..+15) instead of -0.10..0.15.
    x = [float(xdf.loc[t, xcol]) * 100 for t in teams]
    y = [float(ydf.loc[t, ycol]) * 100 for t in teams]
    colors = [meta.get(t, {}).get("color") or "#888" for t in teams]

    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="markers+text", text=teams, textposition="top center",
        textfont=dict(size=8, color="rgba(150,150,150,0.9)"),
        marker=dict(size=10, color=colors, line=dict(width=1, color="rgba(255,255,255,0.5)")),
        hovertext=teams, hoverinfo="text"))

    # overlay team logos at each point (sized as a fraction of the axis span)
    xspan, yspan = (max(x) - min(x)) or 1, (max(y) - min(y)) or 1
    for t, xi, yi in zip(teams, x, y):
        logo = meta.get(t, {}).get("logo")
        if logo:
            fig.add_layout_image(dict(source=logo, xref="x", yref="y", x=xi, y=yi,
                                      sizex=xspan * 0.07, sizey=yspan * 0.07,
                                      xanchor="center", yanchor="middle",
                                      sizing="contain", layer="above", opacity=0.95))
    xm, ym = sum(x) / len(x), sum(y) / len(y)
    fig.add_vline(x=xm, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    fig.add_hline(y=ym, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    if quad:
        for txt, xside, yside in quad:
            ax = max(x) if xside == "max" else min(x)
            ay = min(y) if yside == "min" else max(y)
            fig.add_annotation(x=ax, y=ay, text=txt, showarrow=False,
                               font=dict(size=11, color="#999"),
                               xanchor="right" if xside == "max" else "left",
                               yanchor="bottom" if yside == "min" else "top")
    pad_x, pad_y = xspan * 0.10, yspan * 0.10
    fig.update_layout(
        height=580, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        xaxis=dict(title=xtitle, gridcolor="rgba(128,128,128,0.12)", zeroline=False,
                   range=[min(x) - pad_x, max(x) + pad_x]),
        yaxis=dict(title=ytitle, gridcolor="rgba(128,128,128,0.12)", zeroline=False,
                   autorange="reversed" if y_rev else True,
                   range=[max(y) + pad_y, min(y) - pad_y] if y_rev else [min(y) - pad_y, max(y) + pad_y]))
    st.plotly_chart(fig, width="stretch")
    st.caption("Dotted lines are league average. Logos plot each team at its true coordinates.")


# --- distributions -----------------------------------------------------------
def _distribution(off, deff, extras) -> None:
    import plotly.graph_objects as go
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
    colors = [meta.get(t, {}).get("color") or "#888" for t in teams]
    order = np.argsort(vals)[::-1] if good_high else np.argsort(vals)
    teams = [teams[i] for i in order]; vals = [vals[i] for i in order]
    colors = [colors[i] for i in order]
    fig = go.Figure(go.Bar(x=vals, y=teams, orientation="h", marker=dict(color=colors),
                           hoverinfo="x+y"))
    fig.add_vline(x=float(np.mean(vals)), line_dash="dot", line_color="rgba(200,200,200,0.6)",
                  annotation_text="league avg")
    fig.update_layout(height=max(400, 20 * len(teams)), margin=dict(l=10, r=10, t=20, b=20),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, yaxis=dict(autorange="reversed"),
                      xaxis=dict(gridcolor="rgba(128,128,128,0.12)", title=metric))
    st.plotly_chart(fig, width="stretch")
    spread = max(vals) - min(vals)
    st.caption(f"League spread: {spread:.1f}. The bigger the gap from the pack, the more real "
               "the edge — clustered metrics offer little separation to bet on.")


# --- color-coded stat tables (kept) ------------------------------------------
def _shade(df: pd.DataFrame, good_high_cols: list[str], good_low_cols: list[str],
           pct_cols: list[str]):
    sty = df.style
    for c in good_high_cols:
        if c in df.columns:
            sty = sty.background_gradient(cmap="RdYlGn", subset=[c])
    for c in good_low_cols:
        if c in df.columns:
            sty = sty.background_gradient(cmap="RdYlGn_r", subset=[c])
    fmts = {c: "{:.1%}" for c in pct_cols if c in df.columns}
    # EPA columns are stored as tiny decimals but shown per-100-plays (×100).
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
    st.caption("EPA columns are shown **per 100 plays** (0 = league average) — easier to read than the raw decimal.")


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


def _glossary() -> None:
    with st.expander("What these numbers mean"):
        st.markdown(
            "- **Net/100 & EPA/100** — efficiency shown as points per **100 plays** (the raw "
            "EPA/play ×100), so it reads in whole numbers. 0 = league average; elite offense ≈ "
            "+10–20, good defense is negative (fewer points allowed).\n"
            "- **Move (Δ Wk)** — power-rank change since last week. **Trend** — weekly net-EPA path.\n"
            "- **SR** — success rate. **Explosive** — big-play rate.\n"
            "- Tables are heat-shaded green→red (defense reversed, since lower is better)."
        )


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    extras = extras or {}
    st.subheader("League — Power Rankings & Efficiency")
    if off.empty and deff.empty:
        st.warning("No data loaded yet.")
        return
    _confidence_banner(extras)
    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))

    st.markdown("### Power rankings")
    c1, c2 = st.columns(2)
    conf_filter = c1.selectbox("Conference", ["All", "AFC", "NFC"], key="lg_conf")
    divs = ["All"] + ([f"{conf_filter} {d}" for d in ("East", "North", "South", "West")]
                      if conf_filter != "All" else [])
    div_filter = c2.selectbox("Division", divs, key="lg_div") if len(divs) > 1 else "All"
    _power_rankings(off, deff, extras, conf_filter, div_filter)

    st.divider()
    st.markdown("### The efficiency quadrant")
    preset = st.radio("Chart", list(_PRESETS.keys()), horizontal=True, label_visibility="collapsed")
    _quadrant(off, deff, preset)

    st.divider()
    st.markdown("### Stat tables")
    _glossary()
    view = st.radio("Show", ["Offense", "Defense", "Drives", "Turnovers", "Situational",
                             "Coaching", "Blitz / scheme", "Distributions"], horizontal=True)
    if view == "Offense":
        _offense_table(off)
    elif view == "Defense":
        _defense_table(deff, scheme_df)
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
