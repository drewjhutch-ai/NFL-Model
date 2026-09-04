"""The data pipeline: load, weight, and aggregate everything the tabs need.

Extracted from the app so it can run *outside* Streamlit too — the weekly
snapshot Action calls :func:`build_frames` with no cache to freeze the model's
state. ``app.py`` wraps this in an ``@st.cache_data`` shim.
"""
from __future__ import annotations

import config
from data import (adjust, coaching, drives, elo, form, injuries, injury_value,
                  loaders, ngs, off_coverage, players, positional, pressure,
                  qbvalue, rushing, sharp, situational, tendencies, touchdowns,
                  turnovers)
from data import betting as betmodel


def _injury_feed() -> dict:
    """Year-round injury feed for the engine: Sleeper first, ESPN fallback.

    Reachable from both the Streamlit Cloud host and the GitHub Action. Any
    failure degrades to an empty dict so the projection falls back to the weekly
    game report without breaking.
    """
    try:
        from data.providers import sleeper
        feed = sleeper.injuries_by_team()
        if feed:
            return feed
    except Exception:  # noqa: BLE001
        pass
    try:
        from data.providers import espn_injuries
        return espn_injuries.by_team()
    except Exception:  # noqa: BLE001
        return {}


def _roster_feed():
    """Current rosters for team-assignment correction: live Sleeper, else committed.

    Shares the one Sleeper player pull with the injury feed via the provider's
    memo. Falls back to the latest committed roster snapshot (from the weekly
    Action) if the live pull fails, so team assignments survive a feed outage.
    """
    import pandas as pd
    try:
        from data.providers import sleeper
        live = sleeper.current_rosters()
        if live is not None and not live.empty:
            return live
    except Exception:  # noqa: BLE001
        pass
    try:
        from data import roster_history
        return roster_history.load_latest(config.CURRENT_SEASON)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def build_frames():
    """Load, weight, and aggregate everything the tabs need. Returns a tuple of
    ``(off, deff, blitz, live, schedule, extras)``."""
    pbp = loaders.load_pbp()
    ftn = loaders.load_ftn()
    pbp_w = loaders.add_recency_weight(pbp)

    off = tendencies.compute_offense(pbp_w)
    deff = tendencies.compute_defense(pbp_w)
    # opponent-adjust EPA (strength of schedule) — flows into ranks, edges, betting
    off, deff = adjust.apply_epa_adjustment(off, deff, pbp_w)
    tendencies.compute_qb_rank(off)
    blitz = tendencies.compute_blitz(pbp_w, ftn)
    live = loaders.has_current_season_data(pbp_w)

    schedule = loaders.load_schedule()
    posmap = loaders.position_map()
    # pace: offensive plays per game (feeds pace-aware totals)
    _pace = pbp_w.groupby("posteam").agg(n=("epa", "size"), g=("game_id", "nunique"))
    extras_pace = (_pace["n"] / _pace["g"]).rename("pace")
    wr_off, wr_def = positional.wr_tiers(pbp_w, posmap)
    extras = {
        "dvp": positional.defense_vs_position(pbp_w, posmap),
        "usage": positional.offense_usage(pbp_w, posmap),
        "wr_off": wr_off,
        "wr_def": wr_def,
        "qb": pressure.qb_profiles(pbp_w, posmap),
        "pressure": pressure.defense_pressure(pbp_w),
        "protection": pressure.offense_protection(pbp_w),
        "ovb": pressure.offense_vs_blitz(pbp_w, ftn),
        "rush": rushing.team_rushing_profile(loaders.load_ngs_rushing()),
        "off_sit": situational.offense_situational(pbp_w),
        "def_sit": situational.defense_situational(pbp_w),
        "pace": extras_pace,
        "coaching": coaching.coaching_tendencies(pbp_w, ftn),
        "turnovers": turnovers.turnover_margin(pbp_w),
        "pbp": pbp,  # raw pbp for on-the-fly weekly trends + situational splits
        "ngs_pass": ngs.team_passing(loaders.load_ngs_passing()),
        "ngs_rec": ngs.team_receiving(loaders.load_ngs_receiving()),
    }
    extras["drives_off"], extras["drives_def"] = drives.drive_efficiency(pbp_w)
    _weekly = players.player_stats(loaders.add_recency_weight(loaders.load_weekly_player()))
    if _weekly is None or _weekly.empty:
        # weekly endpoint unavailable — derive from pbp, which always loads
        _rost = loaders.load_rosters()
        _names = (dict(zip(_rost["player_id"], _rost["player_name"]))
                  if not _rost.empty and "player_name" in _rost.columns else {})
        _weekly = players.player_stats_from_pbp(pbp_w, posmap, _names)
    # Current-roster override: put every player on the team he's on TODAY, not the
    # team he last played for. Trades/signings/cuts are invisible to stats until a
    # snap is logged, so we correct team assignment from the live roster feed. This
    # frame is read by Players, Props, Touchdowns, and the mismatch finder, so the
    # fix propagates everywhere. Degrades to stats-derived teams if the feed is down.
    from data import rosters as roster_mod, depth as depth_mod
    _roster = _roster_feed()
    _weekly, _moves = roster_mod.apply_current_teams(_weekly, _roster)
    # Depth-chart roles (WR1/RB1/TE1) — authoritative starter picture, attached
    # after the team correction so a role always matches the current team.
    _depth = loaders.load_depth_charts()
    _weekly = depth_mod.apply_roles(_weekly, _depth)
    # Per-player NGS tracking (separation / YAC-over-expected for receivers, CPOE
    # for passers) joined onto the frame so the prop projection can nudge for
    # genuine playmaking a raw stat line misses.
    _pr = ngs.player_receiving(loaders.load_ngs_receiving())
    _pp = ngs.player_passing(loaders.load_ngs_passing())
    for _ngs in (_pr, _pp):
        if _ngs is not None and not _ngs.empty:
            _weekly = _weekly.join(_ngs, how="left")
    extras["players"] = _weekly
    extras["depth"] = _depth
    extras["rosters_current"] = _roster
    extras["roster_moves"] = _moves
    extras["form"] = form.team_form(pbp)
    extras["schedule"] = schedule  # for situational home/away splits
    extras["sos"] = betmodel.strength_of_schedule(schedule, betmodel.power_ratings(off, deff))
    rosters = loaders.load_rosters()
    inj_map, inj_week = injuries.build(
        loaders.load_injuries(), loaders.load_snaps(), rosters, config.CURRENT_SEASON)
    # Fold in the year-round feed (Sleeper primary, ESPN fallback): IR / PUP /
    # suspensions the weekly report never carries, valued by role from usage, so
    # a difference-maker on IR docks the team across every betting tab — not just
    # the in-season game report. Degrades to the weekly map if the feed is down.
    feed = _injury_feed()
    inj_map = injuries.merge_feed(inj_map, feed, extras.get("players"))
    # Persistence: how many weeks each player has been on the report (from the
    # committed injury snapshots). Chronic/lingering knocks get weighted harder.
    from data import injury_history
    persist = injury_history.persistence(config.CURRENT_SEASON)
    if persist:
        for team, items in inj_map.items():
            for p in items:
                info = persist.get((team, (p.get("name") or "").lower()))
                if info:
                    p["weeks_lingering"] = info["weeks"]
                    if info["weeks"] >= 3 and injury_value._is_lingering(
                            p.get("status", ""), p.get("practice", "")):
                        p["lingering"] = True
    extras["injuries"] = inj_map
    extras["injury_week"] = inj_week
    extras["injury_feed_source"] = "Sleeper/ESPN" if feed else ""
    extras["injury_pts"] = injury_value.team_injury_points(inj_map)  # non-QB spread impact

    # special teams + QB value (feed the betting projection)
    st_w = loaders.add_recency_weight(loaders.load_special_teams())
    extras["st_ppg"] = betmodel.team_st_points(st_w)
    out_gsis = {t: {p["gsis"] for p in items if p["status"] == "Out"}
                for t, items in inj_map.items()}
    name_map = (dict(zip(rosters["player_id"], rosters["player_name"]))
                if not rosters.empty and "player_name" in rosters.columns else {})
    extras["qb_value"] = qbvalue.qb_values(pbp_w, out_gsis, name_map)
    _rz = touchdowns.redzone_usage(pbp_w, posmap, name_map)
    _rz, _ = roster_mod.apply_current_teams(_rz, _roster)   # goal-line usage on the current team
    extras["rz_usage"] = _rz
    # accuracy layer: stable points-differential signal + Elo ensemble/prior
    extras["points_rtg"] = betmodel.points_ratings(schedule, config.CURRENT_SEASON)
    extras["elo"] = elo.elo_ratings(schedule)
    # Sharp Football lifeblood: charted team tables (pace, personnel, trenches,
    # tendencies, coverage, metrics). Empty dict until the Action commits them;
    # every consumer degrades gracefully. Season falls back to the prior year's
    # committed file during the offseason (data.sharp._resolve handles this).
    extras["sharp"] = sharp.load_all(config.CURRENT_SEASON)

    # Scheme-fit: read the committed defensive coverage rates (no network — the
    # GitHub Action does the scraping) and derive each offense's zone/man
    # performance from pbp. Together they activate the coverage-scheme edge.
    from data.providers.committed import CommittedCoverageProvider
    from data.providers.base import SchemeUnavailable
    try:
        _cov = CommittedCoverageProvider().coverage_tendencies(config.CURRENT_SEASON)
    except (SchemeUnavailable, Exception):  # noqa: BLE001 - never break the build
        _cov = None
    extras["coverage"] = _cov
    extras["off_vs_cov"] = off_coverage.offense_vs_coverage(pbp_w, _cov)
    return off, deff, blitz, live, schedule, extras
