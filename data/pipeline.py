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
        from data.providers import sleeper_injuries
        feed = sleeper_injuries.by_team()
        if feed:
            return feed
    except Exception:  # noqa: BLE001
        pass
    try:
        from data.providers import espn_injuries
        return espn_injuries.by_team()
    except Exception:  # noqa: BLE001
        return {}


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
    extras["players"] = _weekly
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
    extras["rz_usage"] = touchdowns.redzone_usage(pbp_w, posmap, name_map)
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
