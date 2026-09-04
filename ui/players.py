"""The 'Players' tab — prop picks first, digging optional.

Leads with the model's **top prop leans** for the week: the biggest mismatches
between a player's matchup-adjusted projection and their own baseline, ranked by
confidence, so the picks come to you. Below that, a streamlined prop-edge finder
prices any specific line you enter, and a usage explorer sits in a drawer.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import betengine, betting, loaders, players, props
from ui import kit
from ui.components import fmt, ordinal


def _games_played(extras) -> int:
    pbp = extras.get("pbp")
    if pbp is None or pbp.empty or "season" not in pbp.columns:
        return 0
    cur = pbp[pbp["season"] == config.CURRENT_SEASON]
    return int(cur["week"].nunique()) if not cur.empty and "week" in cur.columns else 0


def _script(off, deff, extras, team, opp, team_is_home) -> float:
    home, away = (team, opp) if team_is_home else (opp, team)
    margin = betting.project_margin(off, deff, home, away, extras.get("st_ppg"),
                                    extras.get("qb_value"), extras.get("points_rtg"))
    return 0.0 if pd.isna(margin) else float(margin if team_is_home else -margin)


# --- section 1: auto prop picks ----------------------------------------------
def _pick_card(col, r) -> None:
    conf = r["conf"]
    color = "var(--edge)" if conf >= 50 else ("var(--accent)" if conf >= 32 else "var(--ink-faint)")
    side_color = "var(--edge)" if r["Side"] == "Over" else "var(--fade)"
    col.markdown(
        f"<div style='border:1px solid var(--line);border-left:4px solid {color};border-radius:12px;"
        f"padding:13px 15px;height:100%;background:var(--surface);'>"
        f"<div style='font-weight:700;font-size:1.02rem;'>{r['Player']} "
        f"<span style='color:var(--ink-faint);font-weight:400;font-size:0.85rem;'>{r['Pos']} · {r['Team']}</span></div>"
        f"<div style='margin:4px 0;'><span style='color:{side_color};font-weight:700;'>{r['Side']} "
        f"{r['Stat']}</span> <span style='color:var(--ink-dim);'>· proj {r['Projection']:g} vs {r['Baseline']:g}</span></div>"
        f"<div style='font-size:0.85rem;color:var(--ink-dim);'>{r['Matchup']}</div>"
        f"<div style='margin-top:6px;'><span style='color:{color};font-weight:700;'>{r['Hit%']:.0f}% "
        f"lean</span> <span style='color:var(--ink-faint);font-size:0.8rem;'>· conf {conf:.0f}</span></div></div>",
        unsafe_allow_html=True)


def _coverage_matchups(extras) -> None:
    """Sharp coverage-by-position — which defenses are soft vs each position (prop targets)."""
    from data import sharp_value as sv
    from ui import kit
    cbp = sv.coverage_by_position(extras.get("sharp") or {})
    if cbp.empty:
        return
    st.markdown("### Defense coverage by position")
    st.caption("Yards allowed per target to each position (Sharp charting). "
               "Green = tough coverage, **red = soft — target the red cells** for that position's props.")
    order = ["WR", "TE", "RB", "Slot", "Outside"]
    val_cols = {f"ypt_{p}": p for p in order if f"ypt_{p}" in cbp.columns}
    disp = cbp[list(val_cols)].rename(columns=val_cols)
    ranks = {p: cbp[f"ypt_{p}_rank"] for p in val_cols.values() if f"ypt_{p}_rank" in cbp.columns}
    disp = disp.sort_index()

    def _style(colseries):
        rk = ranks.get(colseries.name)
        if rk is None:
            return [""] * len(colseries)
        # rank 1 = lowest YPT = tough coverage = green; rank 32 = soft = red (a target)
        return [f"background-color:{kit.heat_bg(rk.loc[i])}" for i in colseries.index]

    sty = disp.style.apply(_style).format("{:.1f}")
    st.dataframe(sty, width="stretch")


def _auto_picks(stats, off, deff, extras, games) -> None:
    st.markdown("### Top prop picks this week")
    st.caption("Starters only — the model's projection vs each player's **own season average** (not a "
               "sportsbook line). These are *targets*: enter the book's real number in the Prop edge "
               "finder below for the actual edge & Kelly.")
    gp = _games_played(extras)
    board = props.auto_prop_picks(stats, off, deff, extras, games, games_played=gp)
    if board.empty:
        st.info("No prop leans yet — needs player data for this slate.")
        return
    f1, f2, f3 = st.columns([2, 2, 1.6])
    positions = sorted(board["Pos"].dropna().unique())
    pos_sel = f1.multiselect("Position", positions, default=positions, key="pp_pos")
    game_opts = ["All games"] + sorted(board["Game"].unique())
    game_sel = f2.selectbox("Game", game_opts, key="pp_game")
    # data-aware range: confidences are modest, so a fixed 0–100 slider would be
    # mostly a dead zone. Cap it at the board's actual max so every step filters.
    top_conf = max(5, int((int(board["conf"].max()) // 5 + 1) * 5))
    if st.session_state.get("pp_conf", 0) > top_conf:   # a stale (wider-range) value
        st.session_state["pp_conf"] = 0
    min_conf = f3.slider("Min confidence", 0, top_conf, 0, 5, key="pp_conf")
    view = board[board["Pos"].isin(pos_sel) & (board["conf"] >= min_conf)]
    if game_sel != "All games":
        view = view[view["Game"] == game_sel]
    if view.empty:
        st.info("No leans match those filters.")
        return
    # headline cards (top 6)
    top = view.head(6).reset_index(drop=True)
    for i in range(0, len(top), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(top):
                _pick_card(col, top.iloc[i + j])
    # full ranked table
    with st.expander(f"All {len(view)} prop leans (ranked)"):
        show = view[["Player", "Pos", "Team", "Game", "Stat", "Side",
                     "Projection", "Baseline", "Hit%", "Matchup", "conf"]].rename(columns={"conf": "Conf", "Baseline": "Season avg"})
        st.dataframe(show, width="stretch", hide_index=True, column_config={
            "Hit%": st.column_config.NumberColumn("Hit%", format="%d%%"),
            "Conf": st.column_config.NumberColumn("Conf", format="%d"),
        })
    st.caption("**Hit%** is the model's over/under probability if the line sits at the player's "
               "baseline. Enter the book's real number in the finder below for exact edge & Kelly.")


# --- section 2: prop edge finder (streamlined) -------------------------------
def _finder(stats, off, deff, extras, schedule) -> None:
    st.markdown("### Prop edge finder")
    st.caption("Pick a player to see every projectable stat and its lean. Enter the book's line on "
               "any stat for the exact edge, fair odds, and Kelly stake.")
    teams = sorted(stats["team"].dropna().unique())
    c1, c2 = st.columns(2)
    team = c1.selectbox("Team", teams, key="pf_team")
    opp = c2.selectbox("Opponent", [t for t in teams if t != team], key="pf_opp")
    tp = players.team_players(stats, team)
    if tp.empty:
        st.info("No players for this team yet.")
        return
    who = st.selectbox("Player", list(tp["name"]), key="pf_player")
    p = tp[tp["name"] == who].iloc[0]
    team_is_home = True
    if schedule is not None and not schedule.empty:
        gm = schedule[(schedule["home_team"] == team) & (schedule["away_team"] == opp)]
        team_is_home = not gm.empty
    script = _script(off, deff, extras, team, opp, team_is_home)
    proj = props.project_player(p, opp, deff, extras.get("dvp", {}), script=script)
    if not proj:
        st.info("No projectable stats for this player vs this opponent.")
        return
    # all stats at a glance (projection + band + baseline lean)
    rows = []
    for stat, mean in proj.items():
        raw = props._RAW.get(stat)
        base = p.get(raw, 0) if raw else 0
        cv = props._CV.get(stat, 0.0)
        p_over = props.over_prob(mean, float(base), stat) if base else float("nan")
        lean = "—"
        if pd.notna(p_over):
            lean = f"{'Over' if p_over >= 0.5 else 'Under'} ({max(p_over,1-p_over)*100:.0f}%)"
        rows.append({"Stat": stat, "Projection": f"{mean:.1f}" + (f" ±{mean*cv:.0f}" if cv else ""),
                     "Season avg": f"{base:.1f}" if base else "—", "Lean vs avg": lean})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    _ngs_line(p)
    _expected_line(p)

    st.markdown("**Price a specific line:**")
    d1, d2, d3, d4 = st.columns([2, 1, 1, 1])
    stat = d1.selectbox("Stat", list(proj.keys()), key="pf_stat")
    mean = proj[stat]
    line = d2.number_input("Line", value=float(round(mean, 1)), step=0.5, key="pf_line")
    over_odds = d3.number_input("Over", value=-110, step=5, key="pf_over")
    under_odds = d4.number_input("Under", value=-110, step=5, key="pf_under")
    p_over = props.over_prob(mean, float(line), stat)
    if pd.isna(p_over):
        return
    side, p_side, odds, other = (("Over", p_over, over_odds, under_odds) if p_over >= 0.5
                                 else ("Under", 1 - p_over, under_odds, over_odds))
    bet = betengine._bet("finder", f"{team} vs {opp}", "Player prop",
                         f"{who} {stat} {side} {line:g}", p_side, odds, other, rationale="")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Model {side}", f"{p_side*100:.0f}%")
    m2.metric("Edge", f"{bet['edge']*100:+.1f} pts" if pd.notna(bet['edge']) else "—")
    m3.metric("Fair odds", betengine.fmt_odds(bet["fair_odds"]))
    m4.metric("Kelly", f"{bet['kelly']*100:.1f}u" if bet["kelly"] else "—")
    if pd.notna(bet["edge"]) and bet["edge"] > 0.02:
        st.success(f"Value on the **{side}** — fair {betengine.fmt_odds(bet['fair_odds'])} "
                   f"vs your {betengine.fmt_odds(odds)}.")
    else:
        st.info("No clear edge at this price.")


def _matchup_props(row, stats, off, deff, extras) -> None:
    """All favorite prop edges for one matchup — no player-picking required."""
    gp = _games_played(extras)
    board = props.auto_prop_picks(stats, off, deff, extras, pd.DataFrame([row]), games_played=gp)
    st.markdown("### Prop edges in this matchup")
    st.caption("Every favorite player-prop lean in this game, both teams — ranked by the model. "
               "Matchup-adjusted (usage × nflverse dvp × Sharp coverage × pace × script). No line needed.")
    if board.empty:
        st.info("No prop leans for this game yet.")
        return
    top = board.head(6).reset_index(drop=True)
    for i in range(0, len(top), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(top):
                _pick_card(col, top.iloc[i + j])
    with st.expander(f"All {len(board)} prop leans in this game (ranked)"):
        show = board[["Player", "Pos", "Team", "Stat", "Side", "Projection",
                      "Baseline", "Hit%", "Matchup", "conf"]].rename(columns={"conf": "Conf", "Baseline": "Season avg"})
        st.dataframe(show, width="stretch", hide_index=True, column_config={
            "Hit%": st.column_config.NumberColumn("Hit%", format="%d%%"),
            "Conf": st.column_config.NumberColumn("Conf", format="%d"),
        })


def _usage_matchup(row, stats) -> None:
    """Who's involved in THIS game — target/carry share for both teams, side by side."""
    away, home = row["away_team"], row["home_team"]
    st.markdown("### Who's involved — usage in this matchup")
    st.caption("Target and carry share for each team's skill players: who the ball actually runs through.")
    c = st.columns(2)
    for col, t in ((c[0], away), (c[1], home)):
        tp = stats[stats["team"] == t].copy()
        if tp.empty:
            col.caption(f"_No player data for {t}._")
            continue
        tt = tp["targets"].fillna(0).sum() or 1
        tc = tp["carries"].fillna(0).sum() or 1
        tp["_inv"] = tp["targets"].fillna(0) + tp["carries"].fillna(0) * 0.5
        tp = tp.sort_values("_inv", ascending=False).head(7)
        d = pd.DataFrame({
            "Player": tp["name"], "Pos": tp["pos"],
            "Tgt%": (tp["targets"].fillna(0) / tt * 100).round(0),
            "Rush%": (tp["carries"].fillna(0) / tc * 100).round(0),
        })
        col.markdown(f"**{t}**")
        col.dataframe(d, width="stretch", hide_index=True, column_config={
            "Tgt%": st.column_config.NumberColumn("Tgt%", format="%d%%"),
            "Rush%": st.column_config.NumberColumn("Rush%", format="%d%%"),
        })


def _coverage_matchup(row, extras) -> None:
    """The two defenses' coverage-by-position, side by side — where each is soft."""
    from data import sharp_value as sv
    cbp = sv.coverage_by_position(extras.get("sharp") or {})
    if cbp.empty:
        return
    away, home = row["away_team"], row["home_team"]
    st.markdown("### Coverage matchup — where each defense is soft")
    st.caption("Sharp yards-allowed per target by position. Red = soft (target that position's props); "
               "green = tough. Left defense faces the away offense, right faces home.")
    order = ["WR", "TE", "RB", "Slot", "Outside"]
    c = st.columns(2)
    for col, d in ((c[0], home), (c[1], away)):
        if d not in cbp.index:
            col.caption(f"_No coverage data for {d}._")
            continue
        rows = [f'<div class="k-lbl" style="margin-bottom:5px">{d} DEFENSE · YPT allowed</div>'
                f'<div class="k-speclist">']
        for p in order:
            vc, rc = f"ypt_{p}", f"ypt_{p}_rank"
            if vc in cbp.columns and pd.notna(cbp.loc[d, vc]):
                rk = int(cbp.loc[d, rc]) if rc in cbp.columns and pd.notna(cbp.loc[d, rc]) else None
                bg = kit.heat_bg(rk) if rk else "transparent"
                rtxt = f" ({ordinal(rk)})" if rk else ""
                rows.append(f'<div class="k-spec" style="background:{bg};border-radius:6px;padding-left:8px">'
                            f'<span class="sk">vs {p}</span>'
                            f'<span class="sv"><b>{cbp.loc[d, vc]:.1f}</b>{rtxt}</span></div>')
        rows.append("</div>")
        col.markdown("".join(rows), unsafe_allow_html=True)


def _ngs_line(p) -> None:
    """Next Gen Stats playmaking context for the selected player, if charted."""
    bits = []
    sep, yac, cpoe, ttt = p.get("sep"), p.get("yac_oe"), p.get("cpoe"), p.get("ttt")
    if pd.notna(sep):
        bits.append(f"**{float(sep):.1f} yd** separation")
    if pd.notna(yac):
        bits.append(f"**{float(yac):+.1f}** YAC over expected")
    if pd.notna(cpoe):
        bits.append(f"**{float(cpoe):+.1f}%** CPOE")
    if pd.notna(ttt):
        bits.append(f"**{float(ttt):.2f}s** time to throw")
    if bits:
        st.caption("📡 Next Gen tracking: " + " · ".join(bits) +
                   " — the projection is nudged (±4%) for genuine separation / YAC / CPOE.")


def _expected_line(p) -> None:
    """ff_opportunity expected production vs the player's box-score baseline."""
    pairs = [("exp_rec_yds", "receiving_yards", "rec yds"),
             ("exp_rush_yds", "rushing_yards", "rush yds"),
             ("exp_rec", "receptions", "rec")]
    bits, flags = [], []
    for exp_c, raw_c, label in pairs:
        exp = p.get(exp_c)
        act = p.get(raw_c)
        if pd.notna(exp) and pd.notna(act) and float(exp) > 0:
            bits.append(f"**{float(exp):.1f}** exp {label} (vs {float(act):.1f} actual)")
            gap = (float(act) - float(exp)) / float(exp)
            if gap >= 0.20:
                flags.append(f"{label} running **hot** (+{gap*100:.0f}% over expected) — regression risk, lean Under")
            elif gap <= -0.20:
                flags.append(f"{label} running **cold** ({gap*100:.0f}% under expected) — buy-low, lean Over")
    if bits:
        st.caption("📈 Expected production (ff_opportunity): " + " · ".join(bits))
        for f in flags:
            st.caption("↳ " + f)


def _usage(stats, teams) -> None:
    with st.expander("Full player usage explorer (per team)"):
        team = st.selectbox("Team", teams, key="pl_team")
        t = players.team_players(stats, team)
        if t.empty:
            st.info("No player data for this team yet.")
            return
        show = pd.DataFrame({
            "Player": t["name"], "Pos": t["pos"],
            "Role": t["role"] if "role" in t.columns else "",
            "G": t["games"].round(0),
            "Pass yds": t["passing_yards"].round(1), "Rush yds": t["rushing_yards"].round(1),
            "Car": t["carries"].round(1), "Tgt": t["targets"].round(1),
            "Rec": t["receptions"].round(1), "Rec yds": t["receiving_yards"].round(1),
        })
        st.dataframe(show, width="stretch", hide_index=True)
        st.caption("Per-game averages, recency-weighted (recent games count more).")


def _roster_moves(extras) -> None:
    """Show players the model re-assigned to their current team (trades/signings)."""
    moves = extras.get("roster_moves") or []
    skill = [m for m in moves if m.get("pos") in ("QB", "RB", "WR", "TE")]
    if not skill:
        return
    src = extras.get("rosters_current")
    fresh = "live roster feed" if src is not None and not getattr(src, "empty", True) else "committed roster snapshot"
    with st.expander(f"🔄 Roster moves applied — {len(skill)} skill players on a new team ({fresh})"):
        st.caption("The model assigns every player to his **current** team, not the team he last "
                   "played for — so trades, signings and cuts show up here before he logs a snap. "
                   "This feeds Players, Props, Touchdowns, and the projection on every tab.")
        df = pd.DataFrame([{"Player": m["name"], "Pos": m["pos"],
                            "From": m["from"], "Now": m["to"]} for m in skill])
        st.dataframe(df, width="stretch", hide_index=True)


def render(off, deff, schedule, extras) -> None:
    st.subheader("Players — prop edges by matchup")
    stats = extras.get("players")
    if stats is None or stats.empty:
        st.info("Player stats not available yet (they load once games are played).")
        return
    _roster_moves(extras)
    teams = sorted(stats["team"].dropna().unique())
    season = config.CURRENT_SEASON
    have = (schedule is not None and not schedule.empty and (schedule["season"] == season).any())
    if not have:
        st.info("Schedule not loaded — showing the whole-slate leans and usage.")
        _auto_picks(stats, off, deff, extras, pd.DataFrame())
        st.divider()
        _coverage_matchups(extras)
        st.divider()
        _usage(stats, teams)
        return

    s = schedule[schedule["season"] == season]
    weeks = sorted(int(w) for w in s["week"].unique())
    default_wk = loaders.current_week(schedule, season) or weeks[0]
    cwk, cgm = st.columns([1, 3])
    wk = cwk.selectbox(f"Week ({season})", weeks,
                       index=weeks.index(default_wk) if default_wk in weeks else 0, key="pl_wk")
    games = s[s["week"] == wk]
    labels = ["🔎 Whole slate"] + [f"{r.away_team} @ {r.home_team}" for r in games.itertuples()]
    pick = cgm.selectbox("Matchup", labels, key="pl_game")

    if pick == "🔎 Whole slate":
        _auto_picks(stats, off, deff, extras, games)
    else:
        row = games.iloc[labels.index(pick) - 1]
        _matchup_props(row, stats, off, deff, extras)
        st.divider()
        _usage_matchup(row, stats)
        st.divider()
        _coverage_matchup(row, extras)
    st.divider()
    with st.expander("Price a specific line (any player)"):
        _finder(stats, off, deff, extras, schedule)
    with st.expander("League coverage-by-position board"):
        _coverage_matchups(extras)
    _usage(stats, teams)
