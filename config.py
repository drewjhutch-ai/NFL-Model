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
