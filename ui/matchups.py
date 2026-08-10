"""The 'Matchups' tab: the week's games, auto-loaded, each broken down into the
unit and positional edges that actually drive picks.

Two layers of edge, both transparent (rank differentials, no black box):
  * Unit edges  — pass / rush / explosive / overall (offense rank vs the defense
    unit it faces).
  * Positional edges — does a team feature a position (e.g. pass-catching RBs)
    that the opponent struggles to cover?
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import loaders, positional, pressure, rushing, tendencies
from ui.components import fmt, ordinal


# --- unit edges --------------------------------------------------------------
def _edge(off_rank, def_rank) -> tuple[str, float]:
    if pd.isna(off_rank) or pd.isna(def_rank):
        return "—", 0.0
    magnitude = (32 - int(def_rank)) - (int(off_rank) - 1)
    if magnitude >= 12:
        return "🟢 Strong offense edge", magnitude
    if magnitude >= 5:
        return "🟢 Lean offense", magnitude
    if magnitude <= -12:
        return "🔴 Strong defense edge", magnitude
    if magnitude <= -5:
        return "🔴 Lean defense", magnitude
    return "🟡 Even", magnitude


def _unit_row(name, off_team, off_rank, def_team, def_rank) -> dict:
    label, _ = _edge(off_rank, def_rank)
    return {
        "Matchup": name,
        f"{off_team} O": ordinal(off_rank),
        f"{def_team} D": ordinal(def_rank),
        "Edge": label,
    }


def _direction(off, deff, blitz, extras, o_team, d_team) -> None:
    dvp, usage = extras["dvp"], extras["usage"]
    st.markdown(f"##### {o_team} offense → {d_team} defense")
    if o_team not in off.index or d_team not in deff.index:
        st.info("Not enough data for this side.")
        return
    o, d = off.loc[o_team], deff.loc[d_team]

    st.caption("Unit edges (rank 1 = best)")
    unit = pd.DataFrame([
        _unit_row("Passing", o_team, o["pass_epa_rank"], d_team, d["pass_epa_rank"]),
        _unit_row("Rushing", o_team, o["rush_epa_rank"], d_team, d["rush_epa_rank"]),
        _unit_row("Explosive", o_team, o["explosive_rate_rank"], d_team, d["explosive_rate_rank"]),
        _unit_row("Overall", o_team, o["epa_play_rank"], d_team, d["epa_play_rank"]),
    ])
    st.dataframe(unit, width="stretch", hide_index=True)

    # positional edges (RB / WR / TE weapons vs coverage soft spots)
    pos_tbl = positional.matchup_table(o_team, d_team, usage, dvp)
    if not pos_tbl.empty:
        st.caption("Positional edges (who they feature vs. what the D allows)")
        st.dataframe(pos_tbl.drop(columns=[c for c in ["_mag"] if c in pos_tbl.columns]),
                     width="stretch", hide_index=True)

    # WR1/2/3 tier detail
    wr_tbl = positional.wr_tier_matchup(o_team, d_team, extras["wr_off"], extras["wr_def"])
    if not wr_tbl.empty:
        with st.expander("WR1 / WR2 / WR3 detail"):
            st.dataframe(wr_tbl, width="stretch", hide_index=True)

    # QB mobility vs pass rush
    qb, prs = extras["qb"], extras["pressure"]
    bits = []
    if not qb.empty and o_team in qb.index:
        q = qb.loc[o_team]
        bits.append(f"**{o_team} QB:** {pressure.qb_label(q['qb_rush_rate'])} "
                    f"({fmt(q['qb_rush_rate'], 'pct')} rush rate)")
    if not prs.empty and d_team in prs.index:
        p = prs.loc[d_team]
        bits.append(f"**{d_team} rush:** {pressure.pressure_label(p['pressure_rate_rank'])} "
                    f"({fmt(p['pressure_rate'], 'pct')} pressure, {ordinal(p['pressure_rate_rank'])})")
    if bits:
        st.caption("  ·  ".join(bits))

    # RB rushing playstyle vs run defense
    rush = extras["rush"]
    if not rush.empty and o_team in rush.index:
        r = rush.loc[o_team]
        run_d = f"vs {d_team} run D {ordinal(d['rush_epa_rank'])}"
        st.caption(f"**{o_team} ground game:** {rushing.rushing_label(r.get('ryoe_rank'))} "
                   f"({r.get('ryoe_per_att', float('nan')):+.2f} yds over expected/att)  ·  {run_d}")

    if not blitz.empty and d_team in blitz.index:
        b = blitz.loc[d_team]
        st.caption(f"{d_team} blitz: {tendencies.blitz_label(b['blitz_rate'])} "
                   f"({fmt(b['blitz_rate'], 'pct')})")


def _breakdown(away, home, off, deff, blitz, extras) -> None:
    if away == home:
        st.info("Pick two different teams.")
        return
    st.markdown(f"### {away} @ {home}")
    left, right = st.columns(2)
    with left:
        _direction(off, deff, blitz, extras, away, home)
    with right:
        _direction(off, deff, blitz, extras, home, away)
    st.caption(
        "🟢 = offense edge, 🔴 = defense edge, 🟡 = even. Positional edges flag "
        "when a featured weapon (top-12 usage) meets a soft coverage (bottom-12). "
        "A decision aid — the pick is yours."
    )


def _custom(off, deff, blitz, extras, teams) -> None:
    c1, c2 = st.columns(2)
    with c1:
        away = st.selectbox("Away / Team A", teams, index=0, key="mu_away")
    with c2:
        home = st.selectbox("Home / Team B", teams, index=1 if len(teams) > 1 else 0, key="mu_home")
    _breakdown(away, home, off, deff, blitz, extras)


def render(off: pd.DataFrame, deff: pd.DataFrame, blitz: pd.DataFrame,
           schedule: pd.DataFrame, extras: dict) -> None:
    st.subheader("Matchups of the Week")
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
        wk = st.selectbox(f"Week ({season})", weeks, index=idx)
        games = s[s["week"] == wk].sort_values("gameday" if "gameday" in s.columns else "week")

        labels = [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
        if not labels:
            st.info("No games listed for this week.")
            return
        pick = st.selectbox("Game", labels)
        row = games.iloc[labels.index(pick)]
        _breakdown(row["away_team"], row["home_team"], off, deff, blitz, extras)

        with st.expander("Or build a custom matchup (any two teams)"):
            _custom(off, deff, blitz, extras, teams)
    else:
        st.info("Schedule not loaded — pick any two teams to compare.")
        _custom(off, deff, blitz, extras, teams)
