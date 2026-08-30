"""Central configuration for the NFL model dashboard.

Everything the app needs to know about *which* seasons matter and *how much*
they matter lives here, so tuning behavior never means hunting through the app.
"""

# --- Seasons -----------------------------------------------------------------
# The season that should drive every ranking and tendency the moment real games
# exist for it. Update this each year (or automate it later).
CURRENT_SEASON = 2026

# The prior season acts only as a "phantom baseline": something to show during
# the offseason / early weeks before the current season has enough games.
PRIOR_SEASON = 2025

# How much a prior-season play counts relative to a current-season play.
#
# The NFL moves fast, so last year is basically old news. We keep it at a whisper
# so that:
#   * During the offseason (no current-season games yet) the dashboard still has
#     numbers to show -- they just come from the prior season.
#   * The instant 2026 games are played, current-season data overwhelms the
#     baseline and drives all selections/tendencies.
# Raise this if you want more early-season smoothing; lower it toward 0 to make
# the prior season vanish entirely.
PRIOR_SEASON_WEIGHT = 1e-6

# Every season the loaders will attempt to pull, newest last. The prior season
# is the smoothing baseline; the current season is the driver.
SEASONS = [PRIOR_SEASON, CURRENT_SEASON]

# Within the current season, weight recent games more than early ones (form,
# roster changes). Per-week multiplier applied by how many weeks back a play is.
RECENCY_DECAY = 0.96

# Empirical-Bayes shrinkage: regress a team's noisy rate stats toward the league
# mean by this many "pseudo-plays". Bigger = more regression (for less stable
# stats). Small samples (early season) get pulled to the mean; full samples don't.
SHRINK_SITUATIONAL = 45   # red zone / 3rd down are regression-prone
SHRINK_RATE = 20          # success / explosive rates


# --- "Neutral game script" filter --------------------------------------------
# Play-style leans (how pass-happy a team is) are only meaningful when a team
# isn't being forced to pass (trailing late) or run (protecting a big lead).
# These bounds define "normal" football situations.
NEUTRAL_WP_MIN = 0.20          # exclude near-certain losses
NEUTRAL_WP_MAX = 0.80          # exclude near-certain wins
NEUTRAL_MIN_HALF_SECONDS = 120  # exclude two-minute / hurry-up situations
NEUTRAL_DOWNS = (1, 2)          # early downs only


# --- Blitz definition --------------------------------------------------------
# FTN charting reports "n_blitzers" = defenders sent beyond the standard 4-man
# rush. Any blitzer means it was a blitz.
BLITZ_MIN_EXTRA_RUSHERS = 1


# --- Explosive plays ---------------------------------------------------------
EXPLOSIVE_PASS_YARDS = 15
EXPLOSIVE_RUSH_YARDS = 10


# --- Matchup edge weights ----------------------------------------------------
# Not all facets decide games equally. These multipliers weight each facet's
# edge by how much it actually drives NFL outcomes, grounded in public analytics:
#   * Passing/QB efficiency (EPA, CPOE) is by far the most predictive & stable
#     signal — QB play is the deciding factor.
#   * Pass rush / pressure is a sticky, high-value signal.
#   * Rushing EPA has "virtually negligible" year-over-year correlation → low.
#   * Red-zone TD% and (to a lesser extent) 3rd down are regression-prone → modest.
#   * RB receiving is a real but small slice of the game — far below WR value.
# Refs: SumerSports "sticky stats", nflfastR/EPA research, ESPN win-rate metrics.
# Tune freely; 1.0 = league-average importance.
# Retuned from the backtest's facet-predictiveness (scripts/backtest.py): 3rd-down
# and rushing tracked real margins far better than their old weights, WR receiving
# less so. Raised the underweighted-but-predictive facets, but *tempered* rushing
# and red zone (their correlation is inflated by winner's bias — winning teams run
# out the clock and finish drives — and both regress year to year).
EDGE_WEIGHTS = {
    "QB / Passing": 2.5,
    "Pass rush": 1.4,
    "3rd down": 1.4,          # was 0.9 — strongly predictive in backtest
    "Coverage scheme": 1.4,   # activates when PFF offense-vs-coverage data exists
    "Explosive": 1.3,
    "Rushing": 1.0,          # was 0.6 — raised, tempered for winner's bias
    "Red zone": 0.9,         # was 0.7 — raised modestly (regression-prone)
    "WR receiving": 0.9,     # was 1.1 — less predictive than assumed
    "TE receiving": 0.6,
    "RB receiving": 0.4,
}
DEFAULT_EDGE_WEIGHT = 1.0


# --- Betting model -----------------------------------------------------------
# Translate our efficiency data into a projected point spread, to compare with
# the market. These are sensible defaults meant to be *calibrated* by the
# results/learning loop over time — not gospel.
HOME_FIELD_ADVANTAGE = 1.8      # points; modern NFL home edge has shrunk to ~1.5-2
# Team-specific home field where it's known to differ (altitude, cold, noise);
# others fall back to HOME_FIELD_ADVANTAGE. Calibratable.
TEAM_HFA = {"DEN": 2.8, "SEA": 2.4, "GB": 2.3, "BUF": 2.3, "KC": 2.3,
            "BAL": 2.2, "NO": 2.2, "PIT": 2.2, "MIN": 2.1, "LAC": 1.4, "LA": 1.4}
PLAYS_PER_TEAM = 63             # to scale EPA/play into a game-level margin
WINPROB_SLOPE = 0.146          # logistic slope: margin (pts) -> win probability
VALUE_SPREAD_PTS = 2.0         # flag value when |our line - market| >= this
VALUE_PROB = 0.05              # flag moneyline value when our edge >= this
VALUE_TOTAL_PTS = 2.5          # flag total value when |our total - market| >= this
LEAGUE_TEAM_PPG = 22.5         # baseline points/team; EPA shifts it for the total
# The market (closing line) is the single most accurate NFL predictor, so we
# trust our *divergence* from it only partway — blend our number toward the line.
# 1.0 = pure model, 0.0 = pure market. Calibrate against results.
MODEL_TRUST = 0.5
# Blend a stable points-differential signal into the (noisier) pure-EPA margin.
# 0 = pure EPA efficiency, 1 = pure scoreboard. A modest points weight regresses
# EPA noise toward what teams have actually done — validated to cut margin error.
POINTS_WEIGHT = 0.55
MARGIN_STD = 13.2             # NFL final-margin std, for win prob & confidence
TOTAL_STD = 10.0             # NFL combined-points std, for the simulation
SIM_N = 20000                # Monte Carlo iterations per game
KEY_NUMBERS = (3, 7, 6, 10, 4, 14)  # margins cluster here; straddling one adds value
PACE_PTS_PER_PLAY = 0.32     # extra combined plays -> extra total points

# QB value: points a starter adds over a replacement QB, applied when the starter
# is ruled Out (the biggest week-to-week line mover).
QB_REPLACEMENT_EPA = -0.08     # EPA/dropback of a replacement-level passer
QB_DROPBACKS_PER_GAME = 34
QB_ADJUST_SCALE = 0.6          # damp raw EPA->points so elite QBs aren't overstated
QB_ADJUST_CAP = 9.0            # max points swing for a QB going out
SPECIAL_TEAMS_WEIGHT = 1.0     # multiplier on ST points/game in the power rating

# Weather: wind is the dominant factor on scoring; cold a smaller one.
WIND_THRESHOLD = 10            # mph before wind starts biting
WIND_PTS_PER_MPH = 0.30        # total points removed per mph over threshold
WIND_MAX_PTS = 6.0             # cap on wind's total reduction
COLD_THRESHOLD = 25            # °F before cold starts biting


# --- Injuries ----------------------------------------------------------------
# A player counts as a "major" injury if they play at least this share of their
# unit's snaps (offense or defense). Captures starters + heavy rotation pieces.
INJURY_SNAP_THRESHOLD = 0.25


# --- Coverage-scheme sources (zone/man) --------------------------------------
# We blend multiple sources into one consensus. Trust weights say how much each
# source counts toward the blend. PFF is the charting gold standard, so it leads;
# the free sources are excellent for tendency-level man/zone and back it up.
# Keys must match each provider's ``key`` attribute.
SCHEME_SOURCE_TRUST = {
    "pff": 1.0,          # PFF ELITE/+ CSV export (manual drop)
    "committed": 0.85,   # auto-fetched weekly blend (GitHub Action)
    "sumersports": 0.85,  # SumerSports (free)
    "statrankings": 0.75,  # StatRankings (free)
}

# Confidence buckets from how far apart the sources are on zone rate (in points).
SCHEME_AGREE_HIGH = 0.04   # within 4 pts across sources -> High confidence
SCHEME_AGREE_MED = 0.08    # within 8 pts -> Medium; wider -> Low
