"""The 'League' tab: pro-level power rankings, the EPA quadrant, and color-coded
efficiency tables.

Built the way the best public sites present team efficiency: a tiered power
ranking (opponent-adjusted net EPA), the signature offense-vs-defense EPA
quadrant (best teams up-and-to-the-right), and heatmap-shaded stat tables — plus
a per-team Strength/Struggle read like the other tabs. Coverage/scheme columns
light up when PFF data is uploaded.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, profiles, tendencies
from data import loaders
from data.providers import load_coverage

_EPA_HELP = ("Expected Points Added per play. 0 = league average; elite offenses "
             "run +0.10 to +0.20. For defense it's points allowed/play — lower is better.")


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
        return "🏆 Contender"
    if rank <= 14:
        return "🟢 Playoff caliber"
    if rank <= 22:
        return "🟡 In the mix"
    return "🔴 Rebuilding"


def _power_rankings(off, deff, extras) -> None:
    pr = betting.power_ratings(off, deff)
    meta = loaders.team_meta()
    st_ppg = extras.get("st_ppg")
    rows = []
    for team, r in pr.sort_values("power_rank").iterrows():
        s, w = _team_sw(team, off, deff, extras)
        rows.append({
            "Rank": int(r["power_rank"]),
            "Logo": meta.get(team, {}).get("logo", ""),
            "Team": meta.get(team, {}).get("name", team),
            "Tier": _tier(int(r["power_rank"])),
            "Net EPA": round(r["net"], 3),
            "Off": int(off.loc[team, "epa_play_rank"]) if team in off.index else None,
            "Def": int(deff.loc[team, "epa_play_rank"]) if team in deff.index else None,
            "ST": round(float(st_ppg.get(team)), 1) if st_ppg is not None and team in st_ppg.index else None,
            "Strength": s,
            "Struggle": w,
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Logo": st.column_config.ImageColumn(" ", width="small"),
        "Net EPA": st.column_config.NumberColumn("Net EPA", format="%+.3f",
            help="Opponent-adjusted offense EPA minus defense EPA allowed."),
        "Off": st.column_config.NumberColumn("Off", help="Offensive efficiency rank"),
        "Def": st.column_config.NumberColumn("Def", help="Defensive efficiency rank"),
        "ST": st.column_config.NumberColumn("ST", format="%+.1f", help="Special-teams points/game"),
    })


# --- EPA quadrant ------------------------------------------------------------
def _quadrant(off, deff) -> None:
    import plotly.graph_objects as go
    meta = loaders.team_meta()
    teams = sorted(set(off.index) & set(deff.index))
    if not teams:
        return
    x = [off.loc[t, "epa_play"] for t in teams]
    y = [deff.loc[t, "epa_play"] for t in teams]
    colors = [meta.get(t, {}).get("color") or "#888" for t in teams]
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="markers+text", text=teams, textposition="top center",
        textfont=dict(size=9), marker=dict(size=13, color=colors,
        line=dict(width=1, color="rgba(255,255,255,0.6)")), hoverinfo="text"))
    xm = sum(x) / len(x)
    ym = sum(y) / len(y)
    fig.add_vline(x=xm, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    fig.add_hline(y=ym, line_dash="dot", line_color="rgba(128,128,128,0.5)")
    # quadrant labels (y reversed: up = good defense)
    ann = [(max(x), min(y), "Complete", "right", "bottom"),
           (min(x), min(y), "Stout D, weak O", "left", "bottom"),
           (max(x), max(y), "Explosive, leaky", "right", "top"),
           (min(x), max(y), "Rebuilding", "left", "top")]
    for ax, ay, txt, xa, ya in ann:
        fig.add_annotation(x=ax, y=ay, text=txt, showarrow=False,
                           font=dict(size=11, color="#999"), xanchor=xa, yanchor=ya)
    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        xaxis=dict(title="Offense EPA/play  (better →)", gridcolor="rgba(128,128,128,0.12)", zeroline=False),
        yaxis=dict(title="Defense EPA/play allowed  (better ↑)", autorange="reversed",
                   gridcolor="rgba(128,128,128,0.12)", zeroline=False))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Opponent-adjusted EPA per play. **Up-and-to-the-right = the best teams** "
               "(good offense *and* defense). Dotted lines are league average.")


# --- color-coded stat tables -------------------------------------------------
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
    fmts.update({c: "{:+.3f}" for c in ["EPA/play", "Pass EPA", "Rush EPA"] if c in df.columns})
    return sty.format(fmts, na_rep="—")


def _offense_table(off) -> None:
    d = off.copy()
    d = d.rename(columns={"epa_play": "EPA/play", "pass_epa": "Pass EPA", "rush_epa": "Rush EPA",
                          "pass_sr": "Pass SR", "rush_sr": "Rush SR", "explosive_rate": "Explosive",
                          "neutral_pass_rate": "Neutral pass"})
    cols = ["EPA/play", "Pass EPA", "Rush EPA", "Pass SR", "Rush SR", "Explosive", "Neutral pass", "style"]
    d = d[[c for c in cols if c in d.columns]].rename(columns={"style": "Lean"})
    d = d.sort_values("EPA/play", ascending=False)
    st.dataframe(_shade(d, ["EPA/play", "Pass EPA", "Rush EPA", "Pass SR", "Rush SR", "Explosive"],
                        [], ["Pass SR", "Rush SR", "Explosive", "Neutral pass"]), width="stretch")


def _defense_table(deff, scheme_df) -> None:
    d = deff.copy()
    if scheme_df is not None:
        d["Zone%"] = [scheme_df.loc[t, "zone_rate"] if t in scheme_df.index else None for t in d.index]
    d = d.rename(columns={"epa_play": "EPA/play", "pass_epa": "Pass EPA", "rush_epa": "Rush EPA",
                          "pass_sr": "Pass SR", "rush_sr": "Rush SR", "explosive_rate": "Explosive"})
    cols = ["EPA/play", "Pass EPA", "Rush EPA", "Pass SR", "Rush SR", "Explosive"]
    if "Zone%" in d.columns:
        cols.append("Zone%")
    d = d[[c for c in cols if c in d.columns]].sort_values("EPA/play")
    st.dataframe(_shade(d, [], ["EPA/play", "Pass EPA", "Rush EPA", "Pass SR", "Rush SR", "Explosive"],
                        ["Pass SR", "Rush SR", "Explosive", "Zone%"]), width="stretch")


def _situational_table(extras) -> None:
    os_ = extras.get("off_sit")
    ds_ = extras.get("def_sit")
    if os_ is None or os_.empty:
        st.info("Situational data not available.")
        return
    d = pd.DataFrame(index=os_.index)
    d["3rd down O"] = os_["third_conv"]
    d["Red zone O"] = os_["rz_td_rate"]
    if ds_ is not None and not ds_.empty:
        d["3rd down D allowed"] = ds_["third_conv"]
        d["Red zone D allowed"] = ds_["rz_td_rate"]
    d = d.sort_values("3rd down O", ascending=False)
    st.dataframe(_shade(d, ["3rd down O", "Red zone O"], ["3rd down D allowed", "Red zone D allowed"],
                        list(d.columns)), width="stretch")


def _blitz_scheme(blitz, scheme_df) -> None:
    if not blitz.empty:
        b = blitz.copy().rename(columns={"blitz_rate": "Blitz%"})
        cols = [c for c in ["Blitz%", "avg_box"] if c in b.columns]
        st.markdown("#### Blitz rate")
        st.dataframe(_shade(b[cols].sort_values("Blitz%", ascending=False),
                            ["Blitz%"], [], ["Blitz%"]), width="stretch")
    st.markdown("#### Coverage scheme (zone/man)")
    if scheme_df is not None:
        sd = scheme_df[[c for c in ["zone_rate", "man_rate", "confidence"] if c in scheme_df.columns]].copy()
        sd = sd.rename(columns={"zone_rate": "Zone%", "man_rate": "Man%"}).sort_values("Zone%", ascending=False)
        st.dataframe(_shade(sd, [], [], ["Zone%", "Man%"]), width="stretch")
        st.caption("Blended from connected sources. Upload PFF for Cover 0–6 detail.")
    else:
        st.caption("🔒 Zone/man appears once a source is connected (free scrapers or a PFF upload).")


def _drives_table(extras) -> None:
    odr, ddr = extras.get("drives_off"), extras.get("drives_def")
    if odr is None or odr.empty:
        st.info("Drive data not available.")
        return
    d = pd.DataFrame(index=odr.index)
    d["Pts/drive (O)"] = odr["pts_per_drive"]
    d["Score% (O)"] = odr["score_rate"]
    d["TD% (O)"] = odr["td_rate"]
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
    with st.expander("📖 What these numbers mean"):
        st.markdown(
            "- **Net EPA** — opponent-adjusted offense minus defense; our power rating.\n"
            "- **EPA/play** — efficiency; 0 = average, elite O ≈ +0.10–0.20, good D is negative.\n"
            "- **SR** — success rate (on-schedule plays). **Explosive** — big-play rate.\n"
            "- Tables are heat-shaded green→red (defense reversed, since lower is better)."
        )


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           extras: dict | None = None) -> None:
    extras = extras or {}
    st.subheader("League — Power Rankings & Efficiency")
    if off.empty and deff.empty:
        st.warning("No data loaded yet.")
        return
    scheme_df = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))

    st.markdown("### 🏆 Power rankings")
    _power_rankings(off, deff, extras)

    st.divider()
    st.markdown("### 📈 The efficiency quadrant")
    _quadrant(off, deff)

    st.divider()
    st.markdown("### 📋 Stat tables")
    _glossary()
    view = st.radio("Show", ["Offense", "Defense", "Drives", "Turnovers", "Situational",
                             "Coaching", "Blitz / scheme"], horizontal=True)
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
    else:
        _blitz_scheme(blitz, scheme_df)
