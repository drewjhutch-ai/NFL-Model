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
EDGE_WEIGHTS = {
    "QB / Passing": 2.4,
    "Pass rush": 1.4,
    "Explosive": 1.3,
    "WR receiving": 1.1,
    "3rd down": 0.9,
    "Coverage scheme": 1.3,   # activates when PFF offense-vs-coverage data exists
    "Red zone": 0.7,
    "Rushing": 0.6,
    "TE receiving": 0.6,
    "RB receiving": 0.35,
}
DEFAULT_EDGE_WEIGHT = 1.0


# --- Betting model -----------------------------------------------------------
# Translate our efficiency data into a projected point spread, to compare with
# the market. These are sensible defaults meant to be *calibrated* by the
# results/learning loop over time — not gospel.
HOME_FIELD_ADVANTAGE = 1.8      # points; modern NFL home edge has shrunk to ~1.5-2
PLAYS_PER_TEAM = 63             # to scale EPA/play into a game-level margin
WINPROB_SLOPE = 0.146          # logistic slope: margin (pts) -> win probability
VALUE_SPREAD_PTS = 2.0         # flag value when |our line - market| >= this
VALUE_PROB = 0.05              # flag moneyline value when our edge >= this
VALUE_TOTAL_PTS = 2.5          # flag total value when |our total - market| >= this
LEAGUE_TEAM_PPG = 22.5         # baseline points/team; EPA shifts it for the total


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
    "sumersports": 0.85,  # SumerSports (free)
    "statrankings": 0.75,  # StatRankings (free)
}

# Confidence buckets from how far apart the sources are on zone rate (in points).
SCHEME_AGREE_HIGH = 0.04   # within 4 pts across sources -> High confidence
SCHEME_AGREE_MED = 0.08    # within 8 pts -> Medium; wider -> Low
