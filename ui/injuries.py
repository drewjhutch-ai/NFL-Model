"""The 'Injuries' tab — being in the know, feeding the projection.

Layers three free sources into one read:
  1. Official weekly game status (nflverse) → snap-share → point-values that
     already move our line (data/injury_value.py). This is the engine input.
  2. Practice participation (DNP / Limited / Full) — the tell behind a
     Questionable: trending out vs likely playing.
  3. ESPN's public feed — a faster layer with a short "in the know" comment,
     surfacing names before the official report catches up.

Plus a manual intel field for beat-report / hidden-injury reads the feeds can't
catch — logged so it isn't lost. No paid feed, no Twitter scraper.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import injuries as injmod
from data import injury_value, loaders

_TONE = {"bad": "#ff5468", "warn": "#ffb43d", "good": "#2fe0a0", "flat": "#566a7d"}


@st.cache_data(ttl=900, show_spinner="Checking the ESPN injury feed…")
def _load_espn() -> dict:
    from data.providers import espn_injuries
    return espn_injuries.by_team()


def _impact_table(inj_map: dict, inj_pts: dict) -> None:
    st.markdown("### League injury impact")
    st.caption("Points the model has **docked each team** for who's Out or Doubtful (snap-share × "
               "position value, QB handled separately). This is what actually moves the projection.")
    rows = []
    for team, pts in sorted(inj_pts.items(), key=lambda kv: kv[1], reverse=True):
        items = inj_map.get(team, [])
        if pts <= 0 and not items:
            continue
        outs = sum(1 for p in items if p["status"] == "Out")
        q = sum(1 for p in items if p["status"] == "Questionable")
        rows.append({
            "Team": team, "Pts docked": round(pts, 2),
            "Out": outs, "Doubtful": sum(1 for p in items if p["status"] == "Doubtful"),
            "Quest.": q, "Key absences": injmod.summary_line(items, limit=3),
        })
    if not rows:
        st.info("No major injuries on the board (offseason, or no report posted yet).")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Pts docked": st.column_config.NumberColumn("Pts docked", format="%.2f",
            help="Spread points subtracted from this team in the projection."),
    })


def _espn_flat(espn: dict) -> pd.DataFrame:
    """Flatten the ESPN by-team dict into one league frame."""
    if not espn:
        return pd.DataFrame()
    frames = []
    for team, g in espn.items():
        if g is None or g.empty:
            continue
        gg = g.copy()
        gg["team"] = team
        frames.append(gg)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


_SEASON_LONG = ("IR", "PUP", "Suspended")


def _season_long_board(espn: dict) -> None:
    """League-wide IR / PUP / Suspended — the year-round board that works in the offseason.

    The official nflverse report is in-season only, so between slates and through
    the summer this ESPN-fed board is what keeps the tab alive: who's on injured
    reserve, the PUP list, and suspensions across all 32 teams.
    """
    st.markdown("### Season-long absences — IR · PUP · Suspended")
    st.caption("Year-round from the ESPN feed — the long-term list the weekly game report doesn't "
               "cover. This is the board that stays populated in the offseason and through camp.")
    flat = _espn_flat(espn)
    if flat.empty:
        st.info("ESPN feed unreachable from this host right now — the season-long board fills in "
                "when the feed is reachable (it works on the Streamlit Cloud host).")
        return
    board = flat[flat["espn_status"].isin(_SEASON_LONG)].copy()
    if board.empty:
        st.caption("No IR / PUP / suspended players on the ESPN feed right now.")
        return
    order = {"IR": 0, "PUP": 1, "Suspended": 2}
    board["_o"] = board["espn_status"].map(order).fillna(9)
    board = board.sort_values(["team", "_o", "pos"])
    c = st.columns(4)
    c[0].metric("On IR", int((board["espn_status"] == "IR").sum()))
    c[1].metric("On PUP", int((board["espn_status"] == "PUP").sum()))
    c[2].metric("Suspended", int((board["espn_status"] == "Suspended").sum()))
    c[3].metric("Teams affected", int(board["team"].nunique()))
    show = board[["team", "name", "pos", "espn_status", "detail"]].rename(columns={
        "team": "Team", "name": "Player", "pos": "Pos",
        "espn_status": "Status", "detail": "Note"})
    st.dataframe(show, width="stretch", hide_index=True)


def _team_drill(inj_map: dict, espn: dict) -> None:
    st.markdown("### Team injury room")
    teams = sorted(set(inj_map) | set(espn))
    if not teams:
        st.info("No injury data to drill into yet.")
        return
    team = st.selectbox("Team", teams, key="inj_team")
    items = inj_map.get(team, [])
    espn_df = espn.get(team, pd.DataFrame())

    if items:
        st.caption("Official report + practice signal + the point-value each absence costs us.")
        for p in items:
            lean, tone = injmod.practice_read(p.get("practice", ""), p.get("status", ""))
            color = _TONE.get(tone, _TONE["flat"])
            pts = injury_value.player_value(p.get("pos", ""), p.get("pct"), p.get("status", ""))
            watch = " · 👁 WATCH" if injmod.is_watch(p) else ""
            prac = injmod.practice_short(p.get("practice", ""))
            prac_txt = f" · practice {prac}" if prac else ""
            pts_txt = f" · −{pts:.2f} pts" if pts > 0 else ""
            share = f"{float(p.get('pct') or 0)*100:.0f}% snaps"
            st.markdown(
                f"<div style='border-left:4px solid {color};padding:5px 0 5px 12px;margin:6px 0;'>"
                f"<b>{p['name']}</b> <span style='color:var(--ink-faint);'>{p.get('pos','')} · {share}"
                f"{pts_txt}</span><br>"
                f"<span style='color:{color};font-weight:600;'>{p['status']} — {lean}</span>"
                f"<span style='color:var(--ink-faint);font-size:0.9rem;'> · {p.get('injury','') or '—'}"
                f"{prac_txt}{watch}</span></div>",
                unsafe_allow_html=True)
    else:
        st.caption("No official designations for this team — showing the ESPN feed only.")

    # ESPN-only names (faster than the official report)
    if not espn_df.empty:
        known = {p["name"].lower() for p in items}
        extra = espn_df[~espn_df["name"].str.lower().isin(known)]
        extra = extra[extra["espn_status"].isin(["Out", "Doubtful", "Questionable", "IR", "Day-To-Day"])]
        if not extra.empty:
            st.markdown("**ESPN feed — faster / not yet on the official report**")
            st.dataframe(
                extra[["name", "pos", "espn_status", "detail"]].rename(columns={
                    "name": "Player", "pos": "Pos", "espn_status": "ESPN status", "detail": "Note"}),
                width="stretch", hide_index=True)


def _manual_intel() -> None:
    st.markdown("### Manual intel — your insider reads")
    st.caption("Beat-report and hidden-injury intel the feeds can't catch (Schefter / Rapoport / beat "
               "writers). Logged against the slate so it isn't lost. Your human edge.")
    if "injury_notes" not in st.session_state:
        st.session_state["injury_notes"] = []
    with st.form("add_intel", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        team = c1.text_input("Team / player", placeholder="SF — Aiyuk")
        source = c2.text_input("Source (optional)", placeholder="Rapoport")
        note = st.text_input("The read", placeholder="Expected to play despite Q tag — full practice Fri")
        if st.form_submit_button("Log intel") and (team or note):
            st.session_state["injury_notes"].append(
                {"Team/Player": team, "Read": note, "Source": source})
    notes = st.session_state["injury_notes"]
    if not notes:
        st.caption("No intel logged yet.")
        return
    st.dataframe(pd.DataFrame(notes), width="stretch", hide_index=True)
    if st.button("Clear intel"):
        st.session_state["injury_notes"] = []
        st.rerun()


def render(off: pd.DataFrame, deff: pd.DataFrame, schedule: pd.DataFrame,
           extras: dict) -> None:
    st.subheader("Injuries — being in the know")
    st.caption("Official designations, the practice signal behind them, and a faster free feed — turned "
               "into the point-values that move the projection. Serious, minor, lingering, and hidden all "
               "read differently.")
    inj_map = extras.get("injuries") or {}
    week = extras.get("injury_week")
    inj_pts = extras.get("injury_pts") or {}
    espn = _load_espn()

    in_season = bool(week) and bool(inj_pts)
    flat = _espn_flat(espn)
    n_season_long = int(flat["espn_status"].isin(_SEASON_LONG).sum()) if not flat.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Report week", week if week else "offseason")
    c2.metric("Teams with absences", sum(1 for v in inj_pts.values() if v > 0))
    c3.metric("IR / PUP / susp.", n_season_long if espn else "—")
    c4.metric("ESPN feed", "Live ✓" if espn else "Unavailable")
    if not espn:
        st.caption("ESPN feed unreachable from this host right now — the official report + practice signal "
                   "below still drive everything. The feed refreshes when reachable (works on the cloud host).")
    st.divider()
    # Year-round board first when the weekly report isn't posted (offseason / between slates).
    if in_season:
        _impact_table(inj_map, inj_pts)
        st.divider()
        _season_long_board(espn)
    else:
        _season_long_board(espn)
        st.divider()
        _impact_table(inj_map, inj_pts)
    st.divider()
    _team_drill(inj_map, espn)
    st.divider()
    _manual_intel()
    st.divider()
    st.caption("How it feeds the model: every Out/Doubtful player is scored by position × snap share and "
               "subtracted from that team's strength in the projection (QB handled by the QB-value model). "
               "Questionables are flagged to watch, not yet priced — your manual intel is the tiebreaker.")
