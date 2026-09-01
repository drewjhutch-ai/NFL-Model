"""The 'Matchups' tab: a Vegas-style head-to-head.

Reads top to bottom the way a sharp builds a card:

  1. **Model vs Market** — our projected spread/total/moneyline beside the real
     line, with the edge in points and a value lean. The bet, not just the better
     team.
  2. **Tale of the tape** — a side-by-side glance, each row won by a color.
  3. **Simulation** — win/cover/over probabilities, key-number leverage, and a
     projected box score.
  4. **Attack breakdowns + drill-downs** — the weighted edge chart, trenches, WR
     tiers, situational, environment, coverage scheme.
  5. **The Angle Finder** — every edge in the game ranked, including the ones the
     headline lean doesn't state (a total lean on a coin-flip side, live-dog
     value, a script-driven first-half angle).
  6. **Scouting notes** — the layered read tied together.

Coverage-scheme calculations are wired but light up fully once PFF offense-vs-
coverage data is connected.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betting, edges, form as form_mod, history, injuries, loaders
from data import positional, pressure, rushing, simulation
from data.providers import load_coverage
from data.weather import weather_effects
from ui.components import (edge_bar_chart, edge_meter_html, fmt,
                           matchup_advantage_grid, movement_arrow, ordinal,
                           rank_color, sparkline_fig, unicode_spark)


# --- banner ------------------------------------------------------------------
def _team_head(col, abbr: str, meta: dict) -> None:
    m = meta.get(abbr, {})
    color = m.get("color") or "#1f77b4"
    with col:
        if m.get("logo"):
            st.image(m["logo"], width=52)
        st.markdown(
            f"<span style='border-left:5px solid {color};padding-left:8px;"
            f"font-size:1.05rem;font-weight:700;'>{m.get('name', abbr)}</span>",
            unsafe_allow_html=True)


def _banner(away: str, home: str, game_row) -> None:
    meta = loaders.team_meta()
    c1, cm, c2 = st.columns([5, 1, 5])
    _team_head(c1, away, meta)
    cm.markdown("<div style='text-align:center;font-size:1.4rem;margin-top:14px;"
                "color:#888;'>@</div>", unsafe_allow_html=True)
    _team_head(c2, home, meta)
    if game_row is not None and "gameday" in game_row and pd.notna(game_row.get("gameday")):
        st.caption(f"{game_row['gameday']} · Week {int(game_row['week'])}")


def _injuries_row(away, home, extras) -> None:
    imap = extras.get("injuries", {})
    if extras.get("injury_week") is None:
        st.caption("Injury reports appear here once the season starts.")
        return
    c1, c2 = st.columns(2)
    c1.markdown(f"**{away}** {injuries.summary_line(imap.get(away, []))}")
    c2.markdown(f"**{home}** {injuries.summary_line(imap.get(home, []))}")


# --- 1. model vs market ------------------------------------------------------
def _lean_chip(text: str, kind: str = "neutral") -> str:
    palette = {"value": ("var(--edge)", "var(--edge-wash)"),
               "fade": ("var(--fade)", "var(--fade-wash)"),
               "neutral": ("var(--ink-faint)", "var(--surface-2)")}
    c, bg = palette.get(kind, palette["neutral"])
    return (f"<span style='color:{c};background:{bg};border-radius:6px;padding:2px 9px;"
            f"font-weight:700;font-size:0.85rem;'>{text}</span>")


def _mkt_card(col, title, model_val, mkt_val, lean_html, sub) -> None:
    with col:
        st.markdown(
            f"<div style='border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:12px 14px;'>"
            f"<div style='font-family:\"IBM Plex Mono\",monospace;font-size:0.62rem;letter-spacing:.14em;"
            f"text-transform:uppercase;color:var(--ink-faint);'>{title}</div>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin:6px 0 2px;'>"
            f"<div><div style='font-family:\"IBM Plex Mono\",monospace;font-size:1.4rem;font-weight:600;"
            f"line-height:1;color:var(--ink);'>{model_val}</div>"
            f"<div style='font-size:0.7rem;color:var(--ink-faint);'>our number</div></div>"
            f"<div style='text-align:right;'><div style='font-family:\"IBM Plex Mono\",monospace;font-size:1.05rem;"
            f"color:var(--ink-dim);line-height:1;'>{mkt_val}</div>"
            f"<div style='font-size:0.7rem;color:var(--ink-faint);'>market</div></div></div>"
            f"<div style='margin-top:6px;'>{lean_html}</div>"
            f"<div style='font-size:0.78rem;color:var(--ink-dim);margin-top:5px;'>{sub}</div>"
            f"</div>", unsafe_allow_html=True)


def _market_verdict(away, home, off, deff, extras, row) -> dict | None:
    """The headline: model line vs the real line for all three markets."""
    a = betting.assess(row, off, deff, extras)
    have_market = pd.notna(a["mkt_spread"]) or pd.notna(a["total_line"])
    if not have_market:
        return None

    st.markdown("### Model vs Market")
    c1, c2, c3 = st.columns(3)

    # --- spread ---
    m_margin = a["blended_margin"] if pd.notna(a["blended_margin"]) else a["model_margin"]
    our_line = betting.fmt_line(home if (pd.notna(m_margin) and m_margin > 0) else away,
                                m_margin) if pd.notna(m_margin) else "—"
    mkt_line = (betting.fmt_line(home if a["mkt_spread"] > 0 else away, a["mkt_spread"])
                if pd.notna(a["mkt_spread"]) else "—")
    if a["value_side"]:
        chip = _lean_chip(f"{a['value_side']} +{abs(a['edge_pts']):.1f} value", "value")
        sub = f"{a['confidence']} confidence · edge {a['edge_pts']:+.1f} pts"
    elif pd.notna(a["edge_pts"]):
        chip = _lean_chip("No spread edge", "neutral")
        sub = f"within {config.VALUE_SPREAD_PTS:g} pts of the line"
    else:
        chip = _lean_chip("—", "neutral"); sub = "no market spread"
    _mkt_card(c1, "Spread", our_line, mkt_line, chip, sub)

    # --- total ---
    our_total = f"{a['model_total']:.1f}" if pd.notna(a["model_total"]) else "—"
    mkt_total = f"{a['total_line']:.1f}" if pd.notna(a["total_line"]) else "—"
    if a["total_side"]:
        chip = _lean_chip(f"{a['total_side']} +{abs(a['total_edge']):.1f}", "value")
        sub = f"our total {a['total_edge']:+.1f} vs the number"
    elif pd.notna(a["total_edge"]):
        chip = _lean_chip("No total edge", "neutral")
        sub = f"within {config.VALUE_TOTAL_PTS:g} pts of the line"
    else:
        chip = _lean_chip("—", "neutral"); sub = "no market total"
    _mkt_card(c2, "Total", our_total, mkt_total, chip, sub)

    # --- moneyline ---
    our_p = f"{a['model_p_home']*100:.0f}% {home}" if pd.notna(a["model_p_home"]) else "—"
    mkt_p = f"{a['mkt_p_home']*100:.0f}% {home}" if pd.notna(a["mkt_p_home"]) else "—"
    if a["ml_side"]:
        chip = _lean_chip(f"{a['ml_side']} ML value", "value")
        sub = f"win-prob edge {a['edge_prob']*100:+.0f} pts"
    else:
        chip = _lean_chip("No ML edge", "neutral")
        sub = "model ≈ market on the winner"
    _mkt_card(c3, "Moneyline", our_p, mkt_p, chip, sub)

    # disagreement + drivers + what the market prices
    if a["disagree"]:
        st.warning(f"**We disagree with the book on the favorite** — our lean is "
                   f"**{a['our_fav']}**, the market favors **{a['mkt_fav']}**.")
    if a["why"]:
        drivers = " · ".join(f"{w['label']} ({w['detail']})" for w in a["why"])
        st.caption(f"**Our drivers:** {drivers}")
    if a["context"]:
        st.caption("**What the market is pricing:** " + " · ".join(a["context"]))
    if a["key_number"]:
        st.info(f"Our number and the market straddle the key number "
                f"**{a['key_number']}** — extra value if you can get this side.")
    return a


def _projection_verdict(away, home, off, deff, extras) -> None:
    """Fallback headline when there's no market line (custom matchup)."""
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    margin = betting.project_margin(off, deff, home, away, st_ppg, qb, extras.get("points_rtg"))  # + = home
    if pd.notna(margin):
        winner = home if margin > 0 else away
        stars, label = _stars(margin)
        st.markdown(f"## Projected lean: {winner} by {abs(margin):.1f} &nbsp; "
                    f"<span style='color:#f1c40f'>{stars}</span> "
                    f"<span style='color:#888;font-size:1rem'>({label})</span>",
                    unsafe_allow_html=True)
    st.caption("No market line for this matchup — showing our projection only. "
               "Pick a scheduled game above for the full model-vs-market read.")


def _stars(margin: float) -> tuple[str, str]:
    m = abs(margin)
    if m >= 7:
        return "★★★", "Strong lean"
    if m >= 3.5:
        return "★★☆", "Lean"
    if m >= 1.5:
        return "★☆☆", "Slight lean"
    return "☆☆☆", "Coin flip"


def _component_margins(away, home, off, deff, extras) -> dict:
    """Each ensemble signal's raw home-margin read (pre home-field), for the council."""
    import numpy as np
    comps: dict[str, float] = {}
    if home in off.index and away in off.index:
        ho = np.nanmean([off.loc[home, "epa_play"], deff.loc[away, "epa_play"]])
        ao = np.nanmean([off.loc[away, "epa_play"], deff.loc[home, "epa_play"]])
        if pd.notna(ho) and pd.notna(ao):
            comps["EPA efficiency"] = (ho - ao) * config.PLAYS_PER_TEAM
    pts = extras.get("points_rtg")
    if pts is not None and len(pts) and home in pts.index and away in pts.index:
        comps["Points differential"] = float(pts.get(home, 0.0) - pts.get(away, 0.0))
    elo = extras.get("elo")
    if elo is not None and len(elo) and home in elo.index and away in elo.index:
        from data.elo import expected_margin
        em = expected_margin(elo, home, away)
        if pd.notna(em):
            comps["Elo power"] = float(em)
    if extras.get("sharp"):
        from data import sharp_value
        sm = sharp_value.sharp_margin(extras["sharp"], home, away)
        if sm is not None and pd.notna(sm):
            comps["Sharp charted EPA"] = float(sm)
    return comps


def _model_council(away, home, off, deff, extras) -> None:
    """Show each independent signal's read — agreement is conviction, clash is where value/risk hides."""
    comps = _component_margins(away, home, off, deff, extras)
    if not comps:
        return
    st.markdown("### The model council")
    st.caption("Each independent signal's read on this game — home-positive, before home field. "
               "When they agree it's conviction; when they split, that's where the edge (or the trap) is.")
    maxabs = max(10.0, max(abs(v) for v in comps.values()))
    rows = ['<div style="margin-top:6px">']
    for name, val in comps.items():
        mag = abs(val) / maxabs * 50.0
        if val >= 0:
            fill = f"left:50%;width:{mag:.0f}%;background:var(--accent)"
            num = f'<span style="color:var(--accent);font-family:\'IBM Plex Mono\',monospace;font-size:.76rem;font-weight:600;min-width:78px;text-align:left">{home} +{val:.1f}</span>'
        else:
            fill = f"right:50%;width:{mag:.0f}%;background:var(--violet)"
            num = f'<span style="color:var(--violet);font-family:\'IBM Plex Mono\',monospace;font-size:.76rem;font-weight:600;min-width:78px;text-align:left">{away} +{abs(val):.1f}</span>'
        rows.append(f'<div class="k-ebar"><span class="nm">{name}</span>'
                    f'<div class="track"><span class="mid"></span>'
                    f'<span class="fill" style="{fill}"></span></div>{num}</div>')
    rows.append("</div>")
    st.markdown("".join(rows), unsafe_allow_html=True)


def _attack_meter(away, home, off, deff, extras) -> None:
    ae = edges.facet_edges(away, home, off, deff, extras)
    he = edges.facet_edges(home, away, off, deff, extras)
    a_net, h_net = edges.direction_net(ae), edges.direction_net(he)
    st.markdown(edge_meter_html(away, home, a_net, h_net), unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)
    k1.metric(f"{away} attack", f"{a_net:+.1f}", help="Importance-weighted attack edge")
    k2.metric(f"{home} attack", f"{h_net:+.1f}", help="Importance-weighted attack edge")
    diff = h_net - a_net
    k3.metric("Attack lean", home if diff > 0 else away, f"+{abs(diff):.1f}" if diff else None)
    if ae or he:
        st.markdown("##### Matchup advantage grid")
        st.markdown(matchup_advantage_grid(away, home, ae, he), unsafe_allow_html=True)


# --- 2. tale of the tape -----------------------------------------------------
def _rank_series(series: pd.Series, ascending: bool) -> pd.Series:
    return series.rank(ascending=ascending, method="min")


def _tale_of_the_tape(away, home, off, deff, extras) -> None:
    """A side-by-side comparison, each row shaded to the team that wins it."""
    meta = loaders.team_meta()
    pace = extras.get("pace"); st_ppg = extras.get("st_ppg")
    prs = extras.get("pressure"); osit = extras.get("off_sit")
    # ad-hoc ranks for metrics that don't carry one
    pace_rank = _rank_series(pace, ascending=False) if pace is not None else None
    st_rank = _rank_series(st_ppg, ascending=False) if st_ppg is not None else None
    power = betting.power_ratings(off, deff)

    def row(label, o_col_df, col, better_low_rank=True, kind="epa", rank_override=None):
        out = {}
        for t in (away, home):
            val, rk = None, None
            if rank_override is not None:
                src = rank_override[0]
                if src is not None and t in getattr(src, "index", []):
                    val = src.get(t); rk = rank_override[1].get(t) if rank_override[1] is not None else None
            elif o_col_df is not None and t in o_col_df.index and col in o_col_df.columns:
                val = o_col_df.loc[t, col]
                rcol = col.replace("_rate", "").replace("_epa", "_epa") + "_rank"
                rcol = {"epa_play": "epa_play_rank", "pass_epa": "pass_epa_rank",
                        "rush_epa": "rush_epa_rank", "explosive_rate": "explosive_rate_rank",
                        "qb_rank": "qb_rank"}.get(col, col + "_rank")
                rk = o_col_df.loc[t].get(rcol) if rcol in o_col_df.columns else None
            out[t] = (val, rk)
        return label, kind, out

    rows = [
        row("Net power", None, None, rank_override=(power["net"], power["power_rank"]), kind="epa"),
        row("Offense (EPA)", off, "epa_play"),
        row("Defense (EPA allowed)", deff, "epa_play"),
        row("Pass offense", off, "pass_epa"),
        row("Pass defense", deff, "pass_epa"),
        row("Rush offense", off, "rush_epa"),
        row("Run defense", deff, "rush_epa"),
        row("Explosive", off, "explosive_rate", kind="pct"),
        row("QB / passing", off, "qb_rank", kind="rankonly"),
    ]
    if prs is not None and not prs.empty:
        rows.append(row("Pass rush", prs, "pressure_rate", kind="pct",
                        rank_override=(prs["pressure_rate"] if "pressure_rate" in prs else None,
                                       prs["pressure_rate_rank"] if "pressure_rate_rank" in prs else None)))
    if osit is not None and not osit.empty:
        rows.append(row("3rd down O", osit, "third_conv", kind="pct",
                        rank_override=(osit["third_conv"] if "third_conv" in osit else None,
                                       osit["third_rank"] if "third_rank" in osit else None)))
    if pace is not None:
        rows.append(("Pace (plays/gm)", "num0", {t: (pace.get(t), pace_rank.get(t) if pace_rank is not None else None) for t in (away, home)}))
    if st_ppg is not None:
        rows.append(("Special teams", "pts", {t: (st_ppg.get(t), st_rank.get(t) if st_rank is not None else None) for t in (away, home)}))

    def cell(val, rk, kind):
        if kind == "rankonly":
            disp = ordinal(rk)
        elif kind == "pct":
            disp = fmt(val, "pct")
        elif kind == "num0":
            disp = f"{val:.0f}" if pd.notna(val) else "—"
        elif kind == "pts":
            disp = f"{val:+.1f}" if pd.notna(val) else "—"
        else:
            disp = fmt(val, "epa")
        badge = f"<span style='color:{rank_color(rk)};font-size:0.75rem;'> {ordinal(rk)}</span>" if pd.notna(rk) and kind != "rankonly" else ""
        return disp, badge

    a_color = meta.get(away, {}).get("color") or "#1f77b4"
    h_color = meta.get(home, {}).get("color") or "#e74c3c"
    html = ["<table style='width:100%;border-collapse:collapse;font-size:0.9rem;'>"]
    html.append(f"<tr><th style='text-align:left;color:{a_color};padding:6px 8px;'>{away}</th>"
                f"<th style='text-align:center;color:#8a8a8a;font-weight:500;'>matchup</th>"
                f"<th style='text-align:right;color:{h_color};padding:6px 8px;'>{home}</th></tr>")
    for label, kind, out in rows:
        (av, ar), (hv, hr) = out[away], out[home]
        adisp, ab = cell(av, ar, kind)
        hdisp, hb = cell(hv, hr, kind)
        # winner = better (lower) rank
        awin = pd.notna(ar) and pd.notna(hr) and ar < hr
        hwin = pd.notna(ar) and pd.notna(hr) and hr < ar
        aw = "background:rgba(46,204,113,0.12);border-radius:6px;" if awin else ""
        hw = "background:rgba(46,204,113,0.12);border-radius:6px;" if hwin else ""
        html.append(
            f"<tr style='border-top:1px solid rgba(128,128,128,0.15);'>"
            f"<td style='text-align:left;padding:5px 8px;{aw}'>{adisp}{ab}</td>"
            f"<td style='text-align:center;color:#9aa0a6;font-size:0.8rem;'>{label}</td>"
            f"<td style='text-align:right;padding:5px 8px;{hw}'>{hb and hb+' '}{hdisp}</td></tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)
    _movement_row(away, home, extras)
    st.caption("Green = the team that wins the row (better league rank). "
               "Ranks colored green (elite) → red (poor).")


def _movement_row(away, home, extras) -> None:
    """Recent-form arrows + EPA trajectory sparklines for both teams."""
    weekly = history.weekly_epa(extras.get("pbp"))
    fm = extras.get("form")
    cols = st.columns(2)
    for col, t in ((cols[0], away), (cols[1], home)):
        bits = []
        if fm is not None and not fm.empty and t in fm.index:
            f = fm.loc[t]
            bits.append(f"off {form_mod.arrow(f['off_delta'], True)} · def {form_mod.arrow(f['def_delta'], False)}")
        spark = unicode_spark(history.spark_series(weekly, t, "net"))
        if spark:
            bits.append(f"net EPA {spark}")
        if bits:
            col.caption(f"**{t}** " + " · ".join(bits))


# --- 3. simulation + key numbers + box score ---------------------------------
def _simulation(away, home, off, deff, extras, row) -> dict | None:
    sim = simulation.simulate(off, deff, home, away, extras, row)
    if not sim:
        return None
    st.markdown("### Simulation "
                f"<span style='color:#888;font-size:0.9rem'>({sim['n']:,} runs)</span>",
                unsafe_allow_html=True)
    k = st.columns(4)
    k[0].metric(f"{home} win", f"{sim['home_win']*100:.0f}%")
    k[1].metric(f"{away} win", f"{(1-sim['home_win'])*100:.0f}%")
    if "home_cover" in sim:
        cover_team = home if sim["home_cover"] >= 0.5 else away
        cover_pct = sim["home_cover"] if cover_team == home else 1 - sim["home_cover"]
        k[2].metric(f"{cover_team} covers", f"{cover_pct*100:.0f}%",
                    help=f"vs market {home} {sim['mkt_spread']:+.1f}")
    if "over" in sim:
        k[3].metric("Over hits", f"{sim['over']*100:.0f}%", help=f"vs market total {sim['mkt_total']}")
    st.caption(f"**Projected score:** {away} {sim['proj_away']:.0f} — {home} {sim['proj_home']:.0f} "
               f"· {simulation.game_script(sim['margin_mean'])}")
    cH, cK = st.columns([3, 2])
    with cH:
        _margin_hist(sim)
    with cK:
        _key_numbers(sim, away, home)
    return sim


def _margin_hist(sim) -> None:
    import plotly.graph_objects as go
    m = sim["margins"]
    fig = go.Figure(go.Histogram(x=m, nbinsx=40, marker_color="#1f77b4", opacity=0.85))
    fig.add_vline(x=0, line_color="rgba(200,200,200,0.6)")
    if "mkt_spread" in sim:
        fig.add_vline(x=sim["mkt_spread"], line_dash="dot", line_color="#e74c3c",
                      annotation_text="market", annotation_font_color="#e74c3c")
    fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=28),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False,
                      xaxis=dict(title=f"{sim['home']} margin (+ = {sim['home']} wins)",
                                 gridcolor="rgba(128,128,128,0.12)"),
                      yaxis=dict(visible=False))
    st.plotly_chart(fig, width="stretch")


def _key_numbers(sim, away, home) -> None:
    """Probability the game lands ON each key number, and cover leverage."""
    import numpy as np
    m = np.asarray(sim["margins"])
    st.markdown("**Key-number leverage**")
    rows = []
    for k in sorted(config.KEY_NUMBERS):
        # probability the final margin is exactly within [k-0.5, k+0.5] either way
        on_home = ((m >= k - 0.5) & (m <= k + 0.5)).mean()
        on_away = ((m <= -(k - 0.5)) & (m >= -(k + 0.5))).mean()
        rows.append({"Number": k,
                     f"{home} by ~{k}": f"{on_home*100:.0f}%",
                     f"{away} by ~{k}": f"{on_away*100:.0f}%"})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("How often the final margin lands right on a key number — where "
               "buying/selling the hook pays off.")


def _box_score(sim, away, home, extras) -> None:
    pace = extras.get("pace")
    dro, drd = extras.get("drives_off"), extras.get("drives_def")
    bits = []
    if pace is not None and away in pace.index and home in pace.index:
        drives_est = (pace.get(away) + pace.get(home)) / 2 / 6.0  # ~6 plays/drive → drives/team
        bits.append(f"~{drives_est:.0f} drives/team")
    for t in (away, home):
        if dro is not None and t in dro.index:
            bits.append(f"{t} {dro.loc[t,'pts_per_drive']:.2f} pts/drive")
    if bits:
        st.caption("**Projected box:** " + " · ".join(bits))


# --- 4. attack breakdowns + drill-downs (existing, lightly kept) --------------
def _direction(o_team, d_team, off, deff, blitz, extras) -> None:
    meta = loaders.team_meta().get(o_team, {})
    color = meta.get("color") or "#1f77b4"
    st.markdown(f"<div style='border-left:5px solid {color};padding-left:10px;'>"
                f"<b>{o_team} offense → {d_team} defense</b></div>", unsafe_allow_html=True)
    fe = edges.facet_edges(o_team, d_team, off, deff, extras)
    if fe:
        st.plotly_chart(edge_bar_chart(fe), width="stretch")
    pos_tbl = positional.matchup_table(o_team, d_team, extras.get("usage", pd.DataFrame()),
                                       extras.get("dvp", {}))
    if not pos_tbl.empty:
        st.dataframe(pos_tbl.drop(columns=[c for c in ["_mag"] if c in pos_tbl.columns]),
                     width="stretch", hide_index=True)
    with st.container(border=True):
        _notes(o_team, d_team, off, deff, blitz, extras)


def _notes(o_team, d_team, off, deff, blitz, extras) -> None:
    qb, prs = extras.get("qb"), extras.get("pressure")
    if qb is not None and not qb.empty and o_team in qb.index and \
       prs is not None and not prs.empty and d_team in prs.index:
        q, p = qb.loc[o_team], prs.loc[d_team]
        st.caption(f"**QB vs rush:** {q.get('qb_style', '—')} "
                   f"({fmt(q['qb_rush_rate'], 'pct')}) vs {pressure.pressure_label(p['pressure_rate_rank'])} "
                   f"({fmt(p['pressure_rate'], 'pct')} pressure)")
    rush = extras.get("rush")
    if rush is not None and not rush.empty and o_team in rush.index and d_team in deff.index:
        r = rush.loc[o_team]
        st.caption(f"**Ground game:** {rushing.rushing_label(r.get('ryoe_rank'))} "
                   f"({r.get('ryoe_per_att', float('nan')):+.2f} RYOE/att) vs "
                   f"{d_team} run D {ordinal(deff.loc[d_team, 'rush_epa_rank'])}")
    os_, ds_ = extras.get("off_sit"), extras.get("def_sit")
    if os_ is not None and not os_.empty and o_team in os_.index:
        o3 = os_.loc[o_team]
        d3 = f" vs {d_team} {ordinal(ds_.loc[d_team, 'third_rank'])}" if ds_ is not None and d_team in ds_.index else ""
        st.caption(f"**3rd down:** {fmt(o3['third_conv'], 'pct')} ({ordinal(o3['third_rank'])}){d3} · "
                   f"**Red zone:** {fmt(o3['rz_td_rate'], 'pct')} TD ({ordinal(o3['rz_rank'])})")
    if not blitz.empty and d_team in blitz.index:
        b = blitz.loc[d_team]
        st.caption(f"**{d_team} blitz:** {fmt(b['blitz_rate'], 'pct')} ({b.get('blitz_tendency', '—')})")


def _trench_rows(o_team, d_team, deff, extras) -> list[dict]:
    prot, prs = extras.get("protection"), extras.get("pressure")
    rush = extras.get("rush")
    rows = []
    if prot is not None and o_team in prot.index and prs is not None and d_team in prs.index:
        pr = int(prot.loc[o_team, "protection_rank"]); dr = int(prs.loc[d_team, "pressure_rate_rank"])
        rows.append({"Battle": "Pass protection", f"{o_team} O-line": ordinal(pr),
                     f"{d_team} pass rush": ordinal(dr), "Edge": _edge_word(dr - pr)})
    if rush is not None and o_team in rush.index and "rush_epa_rank" in deff.columns and d_team in deff.index:
        rr = rush.loc[o_team].get("ryoe_rank"); dr = int(deff.loc[d_team, "rush_epa_rank"])
        if pd.notna(rr):
            rows.append({"Battle": "Run blocking (RYOE)", f"{o_team} O-line": ordinal(int(rr)),
                         f"{d_team} pass rush": ordinal(dr), "Edge": _edge_word(dr - int(rr))})
    return rows


def _edge_word(mag) -> str:
    if mag >= 8:
        return "Strong offense"
    if mag >= 3:
        return "Offense"
    if mag <= -8:
        return "Strong defense"
    if mag <= -3:
        return "Defense"
    return "Even"


def _dropdowns(away, home, off, deff, extras) -> None:
    st.markdown("### Deeper breakdown")
    with st.expander("Trenches — O-line vs D-line (the undervalued battle)"):
        for o, d in ((away, home), (home, away)):
            rows = _trench_rows(o, d, deff, extras)
            if rows:
                st.markdown(f"**{o} blocking vs {d} front**")
                df = pd.DataFrame(rows).rename(columns={f"{d} pass rush": f"{d} front"})
                st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Pass protection = sacks allowed vs pressure generated. Run blocking = "
                   "rush yards over expected vs run defense. An underdog winning the trenches "
                   "is one of the strongest angles in football.")
    with st.expander("WR1 / WR2 / WR3 detail"):
        for o, d in ((away, home), (home, away)):
            wr = positional.wr_tier_matchup(o, d, extras.get("wr_off", pd.DataFrame()),
                                            extras.get("wr_def", {}))
            if not wr.empty:
                st.markdown(f"**{o} receivers vs {d} coverage**")
                st.dataframe(wr, width="stretch", hide_index=True)
    with st.expander("Situational & pace"):
        os_ = extras.get("off_sit"); pace = extras.get("pace")
        rows = []
        for o, d in ((away, home), (home, away)):
            if os_ is not None and o in os_.index:
                r = os_.loc[o]
                rows.append({"Team": o,
                             "3rd down": f"{fmt(r['third_conv'], 'pct')} ({ordinal(r['third_rank'])})",
                             "Red zone TD": f"{fmt(r['rz_td_rate'], 'pct')} ({ordinal(r['rz_rank'])})",
                             "Pace (plays/gm)": f"{pace.get(o, float('nan')):.0f}" if pace is not None else "—"})
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with st.expander("Environment — weather, rest, home field"):
        _environment(away, home, extras)
    with st.expander("Coverage scheme (unlocks with PFF)"):
        scheme = load_coverage(config.CURRENT_SEASON, st.session_state.get("pff_bytes"))
        if scheme is not None and not getattr(scheme, "empty", True):
            rows = []
            for t in (away, home):
                if t in scheme.index:
                    rows.append({"Team": t, "Zone": fmt(scheme.loc[t, "zone_rate"], "pct"),
                                 "Man": fmt(scheme.loc[t, "man_rate"], "pct")})
            if rows:
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("Zone/man rates show here from the blended feed. The **scheme-fit edge** "
                   "activates automatically once a PFF offense-vs-coverage export is uploaded.")


def _environment(away, home, extras) -> None:
    row = extras.get("_game_row")
    notes = []
    if row is not None:
        wx = weather_effects(row)
        if wx["note"]:
            notes.append(wx["note"])
        hr, ar = row.get("home_rest"), row.get("away_rest")
        if pd.notna(hr) and pd.notna(ar) and abs(hr - ar) >= 3:
            notes.append(f"Rest edge: {home if hr > ar else away} (+{int(abs(hr - ar))} days)")
        for t, rest in ((home, hr), (away, ar)):
            if pd.notna(rest):
                if rest >= 13:
                    notes.append(f"{t} off a bye ({int(rest)} days rest)")
                elif rest <= 4:
                    notes.append(f"{t} on a short week ({int(rest)} days — Thursday spot)")
        if row.get("div_game") == 1:
            notes.append("Division game — historically tighter.")
    hfa = betting.home_field(home)
    notes.append(f"{home} home field ≈ {hfa:.1f} pts")
    imap = extras.get("injuries", {})
    for t in (away, home):
        outs = [p for p in imap.get(t, []) if p["status"] == "Out"]
        if outs:
            notes.append(f"{t} without {', '.join(p['name'] for p in outs[:3])}")
    for n in notes:
        st.markdown(f"- {n}")


# --- 5. the angle finder -----------------------------------------------------
def _angle_finder(away, home, off, deff, extras, assessment, sim) -> None:
    """Rank every edge in the game, including ones the headline lean doesn't state."""
    st.markdown("### Angle Finder")
    angles = []  # each: (score, market, lean, confidence, rationale)

    a = assessment
    if a:
        if a.get("value_side") and pd.notna(a.get("edge_pts")):
            angles.append((abs(a["edge_pts"]), "Spread", a["value_side"], a["confidence"],
                           f"Our number is {abs(a['edge_pts']):.1f} pts off the line."))
        if a.get("total_side") and pd.notna(a.get("total_edge")):
            angles.append((abs(a["total_edge"]) * 0.9, "Total", a["total_side"],
                           betting._confidence(a["total_edge"]),
                           f"Model total {a['model_total']:.1f} vs {a['total_line']:.1f} "
                           f"({a['total_edge']:+.1f})."))
        if a.get("ml_side") and pd.notna(a.get("edge_prob")):
            angles.append((abs(a["edge_prob"]) * 20, "Moneyline", a["ml_side"],
                           betting._confidence(abs(a["edge_prob"]) * 8),
                           f"Win-prob edge {a['edge_prob']*100:+.0f} pts vs the market."))
        # live-dog: our dog win prob notably above market implied
        if pd.notna(a.get("model_p_home")) and pd.notna(a.get("mkt_p_home")):
            dog, our_p, mkt_p = (home, a["model_p_home"], a["mkt_p_home"]) if a["model_p_home"] < 0.5 \
                else (away, 1 - a["model_p_home"], 1 - a["mkt_p_home"])
            if our_p - mkt_p >= 0.04 and dog != a.get("ml_side"):
                angles.append((( our_p - mkt_p) * 18, "Live dog", f"{dog} +money",
                               "Medium", f"{dog} wins outright {our_p*100:.0f}% in the sim vs "
                               f"{mkt_p*100:.0f}% implied — a live underdog."))

    # script-driven total/first-half angle from the sim
    if sim:
        if abs(sim["margin_mean"]) >= 10:
            angles.append((3.0, "Script", f"{sim['home'] if sim['margin_mean']>0 else sim['away']} 1st-half",
                           "Low", "Projected blowout — favorite's first-half lean beats the full-game "
                           "number if garbage time tightens it."))

    # biggest facet mismatch as a lean/prop angle
    allx = [(t, e) for t, opp in ((away, home), (home, away))
            for e in edges.facet_edges(t, opp, off, deff, extras)]
    if allx:
        team, big = max(allx, key=lambda x: x[1]["impact"])
        if big["impact"] >= 10:
            angles.append((big["impact"] / 8, "Matchup", f"{team} {big['label']}",
                           "Lean", big["detail"]))

    if not angles:
        st.caption("No standout angles beyond the headline — this one's efficiently priced.")
        return
    angles.sort(key=lambda x: x[0], reverse=True)
    for _, market, lean, conf, why in angles[:6]:
        conf_color = {"High": "#2ecc71", "Medium": "#f1c40f", "Lean": "#f1c40f",
                      "Low": "#e67e22"}.get(conf, "#9aa0a6")
        st.markdown(
            f"<div style='border-left:3px solid {conf_color};padding:4px 0 4px 12px;margin:6px 0;'>"
            f"<b>{market}: {lean}</b> "
            f"<span style='color:{conf_color};font-size:0.8rem;'>· {conf}</span><br>"
            f"<span style='color:#9aa0a6;font-size:0.88rem;'>{why}</span></div>",
            unsafe_allow_html=True)
    st.caption("Ranked by edge size. These include secondary plays the headline lean doesn't state — "
               "your entry point for a pick the model didn't front.")


# --- 6. scouting notes -------------------------------------------------------
def _scouting(away, home, off, deff, extras) -> None:
    st.markdown("### Scouting notes")
    st_ppg, qb = extras.get("st_ppg"), extras.get("qb_value")
    margin = betting.project_margin(off, deff, home, away, st_ppg, qb, extras.get("points_rtg"))
    bullets = []
    if pd.notna(margin):
        w = home if margin > 0 else away
        bullets.append(f"Model leans **{w} by {abs(margin):.1f}** (efficiency + HFA + ST/QB).")
    for o, d in ((away, home), (home, away)):
        rows = _trench_rows(o, d, deff, extras)
        strong = [r for r in rows if "Strong offense" in r["Edge"]]
        if strong:
            bullets.append(f"**{o}** owns the trenches on {strong[0]['Battle'].lower()}.")
    allx = [(t, e) for t, opp in ((away, home), (home, away))
            for e in edges.facet_edges(t, opp, off, deff, extras)]
    if allx:
        team, big = max(allx, key=lambda x: x[1]["impact"])
        if big["impact"] >= 8:
            bullets.append(f"Key mismatch: **{team} {big['label']}** — {big['detail']}.")
    row = extras.get("_game_row")
    if row is not None:
        wx = weather_effects(row)
        if wx["note"] and wx["total_adj"]:
            bullets.append(f"Weather: {wx['note']} (total nudged {wx['total_adj']:+.1f}).")
    imap = extras.get("injuries", {})
    for t in (away, home):
        qout = [p for p in imap.get(t, []) if p["status"] == "Out" and p["pos"] == "QB"]
        if qout:
            bullets.append(f"**{t} QB {qout[0]['name']} OUT** — model has docked their projection.")
    for b in bullets:
        st.markdown(f"- {b}")
    st.caption("Layered read — trenches, skill, situational, and environment together. "
               "A decision aid, not a lock.")


# --- assembly ----------------------------------------------------------------
def _breakdown(away, home, off, deff, blitz, extras, game_row=None) -> None:
    if away == home:
        st.info("Pick two different teams.")
        return
    extras = {**extras, "_game_row": game_row}
    _banner(away, home, game_row)
    _injuries_row(away, home, extras)

    assessment = None
    if game_row is not None:
        assessment = _market_verdict(away, home, off, deff, extras, game_row)
    if assessment is None:
        _projection_verdict(away, home, off, deff, extras)

    st.divider()
    st.markdown("### Tale of the tape")
    _tale_of_the_tape(away, home, off, deff, extras)
    _attack_meter(away, home, off, deff, extras)

    st.divider()
    _model_council(away, home, off, deff, extras)

    st.divider()
    sim = _simulation(away, home, off, deff, extras, game_row)
    if sim:
        _box_score(sim, away, home, extras)

    st.divider()
    st.markdown("### Attack breakdowns")
    la, ra = st.columns(2)
    with la:
        _direction(away, home, off, deff, blitz, extras)
    with ra:
        _direction(home, away, off, deff, blitz, extras)
    st.caption("offense edge · defense edge. Bar length = raw edge; thickness = "
               "how much the facet decides games; ordered by weighted impact.")

    st.divider()
    _dropdowns(away, home, off, deff, extras)
    st.divider()
    _angle_finder(away, home, off, deff, extras, assessment, sim)
    st.divider()
    _scouting(away, home, off, deff, extras)


def _custom(off, deff, blitz, extras, teams) -> None:
    c1, c2 = st.columns(2)
    away = c1.selectbox("Away / Team A", teams, index=0, key="mu_away")
    home = c2.selectbox("Home / Team B", teams, index=1 if len(teams) > 1 else 0, key="mu_home")
    _breakdown(away, home, off, deff, blitz, extras)


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           schedule: pd.DataFrame, extras: dict) -> None:
    if off.empty or deff.empty:
        st.warning("Need offensive and defensive data to compare matchups.")
        return
    teams = sorted(set(off.index) | set(deff.index))
    season = config.CURRENT_SEASON
    have_sched = (schedule is not None and not schedule.empty
                  and (schedule["season"] == season).any())

    if have_sched:
        s = schedule[schedule["season"] == season]
        weeks = sorted(int(w) for w in s["week"].unique())
        default_wk = loaders.current_week(schedule, season) or weeks[0]
        idx = weeks.index(default_wk) if default_wk in weeks else 0
        cwk, cgm = st.columns([1, 3])
        wk = cwk.selectbox(f"Week ({season})", weeks, index=idx)
        games = s[s["week"] == wk].sort_values("gameday" if "gameday" in s.columns else "week")
        labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
        if not labels:
            st.info("No games listed for this week.")
            return
        pick = cgm.selectbox("Game", labels)
        row = games.iloc[labels.index(pick)]
        _breakdown(row["away_team"], row["home_team"], off, deff, blitz, extras, row)
        with st.expander("Or build a custom matchup (any two teams)"):
            _custom(off, deff, blitz, extras, teams)
    else:
        st.info("Schedule not loaded — pick any two teams to compare.")
        _custom(off, deff, blitz, extras, teams)
