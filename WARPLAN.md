# NFL Model — Status & War Plan

_Checkpoint before the Sharp Football data-expansion push. Read this first when resuming._

Branch: `claude/nfl-data-matchup-dashboard-hzoeir` · deploys on Streamlit Cloud.

---

## Where we are (all built, pushed, working)

**9 tabs**, one shared engine, self-tuning, coverage now auto-fetching.

- **📊 Team Data** — grade + thesis header, movement arrows, percentile charts, radar & compare
  (auto-brightens dark teams, distinct colors for same-family pairs), Overview/Advanced split,
  situational splits, NextGen tracking.
- **📋 League** — power rankings (movement + real area-chart Trend), logo quadrant with presets,
  filterable tables, distributions, sample-size confidence.
- **⚔️ Matchups** — model-vs-market header, tale of the tape, key-number leverage, sim, Angle Finder.
- **🧍 Players** — auto prop picks (data-aware confidence slider), prop-edge finder, usage.
- **🎰 Touchdowns** — anytime/2+ TD model from red-zone/goal-line usage + matchup + weather.
- **💰 Betting** — edge board (all markets incl. props), sharp-money tracker, CLV/ROI report card,
  self-tuning panel, live-odds status.
- **🎯 Picks** — Favorites (most likely), Most Edge, Parlay Builder (3–7 leg, correlation-priced),
  Confidence Straights, prop leans, pick log.

**Engines / accuracy:**
- Bet Engine (`data/betengine.py`) — one `Bet` object (edge, fair odds, Kelly, confidence); props via
  `data/props.py`; TD model `data/touchdowns.py`.
- Projection ensemble (`data/betting.py::project_margin`): EPA + **points differential** (POINTS_WEIGHT
  0.55) + **Elo** (`data/elo.py`, ELO_WEIGHT 0.15, season-start regression = early prior) + normal-CDF
  win prob + **injury point-values** (`data/injury_value.py`). Validated on 2025: MAE 10.62→10.47,
  ATS 44.8%→~52%.
- Evolution Engine (`data/history.py`) — weekly snapshots + trends + graded projections.
- Self-tuning (`data/tuning.py`, `scripts/tune.py`) — weekly grade → re-fit POINTS_WEIGHT + facet
  weights → `model_tuning.json` (overlaid by `config.py`). CLV/ROI in `data/clv.py`.

**Automation (GitHub Action `.github/workflows/update-coverage.yml`, weekly + manual):**
- **Coverage now auto-fetches** ✅ — `SharpFootballProvider` (free, public) is reachable from GitHub's
  runners and writes `scheme_data/coverage_2026.csv` (team, zone_rate, man_rate). The
  `CommittedCoverageProvider` reads it in the app. Other free scrapers (SumerSports/StatRankings)
  still blocked by datacenter-IP filtering; Sharp Football is the working source.
- Also runs weekly snapshot + self-tune; commits `history/`, `model_tuning.json`, `tuning_log.csv`.
- Live odds: wired to **The Odds API** (`ODDS_API_KEY` in Streamlit secrets); sidebar shows status.

---

## PHASE 3 BUILD — progress (updated)

Built, tested, pushed this session (branch `claude/nfl-data-matchup-dashboard-hzoeir`):

- **Sharp scraper framework** — `data/providers/sharp_tables.py` (config-driven, all 10 pages,
  discovery-first: captures every column), `scripts/fetch_sharp.py`, `data/sharp.py` (reads committed
  `sharp_data/*.csv`, graceful empty), wired into `data/pipeline.py` (`extras['sharp']`) + the Action.
- **Scheme-fit edge ACTIVATED** — `data/off_coverage.py` derives each offense's zone/man EPA
  (exposure-weighted, shrunk, z-scored affinity) from pbp × committed coverage rates; `edges._coverage_edge`
  rewritten to use it, orthogonal to QB quality. Validated (TB+ vs CAR, MIN− vs CAR).
- **Long Odds tab** (`ui/longodds.py`) — +200 with a hard EV guardrail, cross-facet reads, long parlays.
- **Injuries tab** (`ui/injuries.py`) — nflverse + practice signal (`loaders` now keeps `practice_status`)
  + ESPN feed (`data/providers/espn_injuries.py`) + manual intel. Point-values feed the projection.
- **CLV tab** (`ui/clv.py`) — live multi-book line-shopping, discrepancy board, book grid, de-vig value,
  single-bet lookup, `st.fragment` auto-refresh (pin bumped to streamlit>=1.37).
- **Matchup Advantage Grid** — `components.matchup_advantage_grid`, rendered in Matchups; inherits new
  facets automatically.
- **Automated review loop** — `data/review.py` (per-facet hit rates + `review_log.csv`), `scripts/review.py`,
  Action step, surfaced in the Betting report card. Validated on 2025 (QB 73% … RB rec 54%).

App is now **11 tabs**. All imports clean.

### Valuation + UI — DONE (real columns confirmed from the Action log)
- `data/sharp_value.py` — accessors keyed to the real columns: `sharp_margin` (charted-EPA ensemble),
  `pace_factor`/`neutral_pass_rate`, `coverage_by_position` (YPT allowed, ranked), pass-rush/pass-pro ranks.
- `data/betting.py` — Sharp charted-EPA margin blended into `project_margin` (`config.SHARP_WEIGHT=0.12`,
  gated). Validated on fixtures with real columns.
- `ui/sharp_panel.py` — Team Data → Advanced now shows the full Sharp profile (grouped, league-percentile
  bars, auto edges/soft-spots). Matchup Advantage Grid already renders in Matchups.

### Real Sharp columns (from run #4 log — build against these)
- pace: Rank, Play Clock Used, Neutral, Neutral Pass Rate, Gear Change, No Huddle
- off_personnel: 11, 12, 13, 21, 22, 2+ TE, 2+ RB, 3+ WR, Plays
- def_line: Pressure Rate, No Blitz Pressure Rate, Yards Before Contact Per RB Rush, Rush Stuff Rate
- def_tendencies: Blitz Rate, Light Box Rate, Heavy Box Rate, Sub Package Rate
- coverage_schemes: Man Rate, Zone Rate, Middle Closed Rate, Middle Open Rate
- def_metrics: EPA/Play, Yards Per Play Allowed, Y/PL Last 5, Points Per Drive Allowed, Explosive Play Rate Allowed, Down Conversion Rate Allowed
- off_line: Pressure Rate Allowed, No Blitz Pressure Rate Allowed, Time to Throw, Yards Before Contact Per RB Rush, Rush Stuff Rate
- coverage_by_pos: YPT Allowed WR/TE/RB/Outside/Slot
- off_metrics: EPA/Play, Yards Per Play, Y/PL Last 5, Points Per Drive, Explosive Play Rate, Down Conversion Rate

### ONLY REMAINING — operational
1. **Re-run the Action once** (Actions → "Update model data" → Run workflow). Run #4 scraped 9/10 tables but
   its push was rejected (branch moved mid-run); that's now fixed with a rebase-retry, so the next run commits
   `sharp_data/*.csv` and everything lights up. Then the ensemble + Sharp panel show live data.
2. **off_tendencies** (10th page) returned no parseable table — its URL/layout needs a look. Not blocking.
3. Optional follow-ups: coverage-by-position → player-prop matchups; add Sharp facets to `EDGE_WEIGHTS` once
   the review loop shows they add signal beyond the ensemble.

---

## ORIGINAL WAR PLAN — Sharp Football Analysis data expansion

Goal: pull **a lot more data** from sharpfootballanalysis.com and wire it into the model. It's free,
public, and proven reachable from the Action, so the same scrape→commit→read pipeline applies.

### Priority 1 — Offense vs coverage (activates the dormant scheme-fit edge)
- We have the **defense** side (zone/man rates). We need the **offense** side: each offense's
  performance **vs zone** and **vs man** (EPA/play, success rate, or YPA).
- This activates the **already-built** scheme-fit edge — the "Coverage scheme" facet
  (`config.EDGE_WEIGHTS["Coverage scheme"] = 1.4`) and the dormant hook in `data/edges.py`
  (`_coverage_edge`). Pairing a zone-beating offense vs a zone-heavy defense = the edge.
- Need from user: the **URL** of Sharp Football's offense-vs-coverage / passing-by-coverage page.

### Priority 2 — Broader Sharp Football tables (pick per what they publish)
Candidates to ingest and surface (each becomes a provider + data layer + UI hook):
- Pass rate / PROE by situation (down, distance, script) → totals & coaching tendencies.
- Pressure / blitz / pass-rush splits → sharpen trenches + QB-vs-pressure.
- Personnel & formation usage → Team Data Advanced + prop context.
- Pace / seconds-per-play → totals model.
- Red-zone / third-down efficiency → situational + TD model.
- Any defense-vs-position or explosive-play tables → matchup edges.

### Build approach (reusable)
- Generalize the provider pattern in `data/providers/` (Sharp Football has a consistent page layout;
  a shared `_sharp_table(url, matcher)` helper + one provider per table).
- Extend the Action's `scripts/fetch_coverage.py` (or a sibling `fetch_sharp.py`) to pull the new
  tables and commit them under `scheme_data/` (or a new `sharp_data/`), read by new providers.
- Wire each into the relevant tab/edge; test via the Action's "Run workflow" (GitHub network).

### How to resume
1. Get the **page URLs** from the user for each Sharp Football table we want.
2. For each: add a provider (mirror `data/providers/sharpfootball.py`), a data layer, and a UI/edge hook.
3. Add to the fetch script + Action; run the workflow to confirm it scrapes + commits.
4. Refresh the app to verify it surfaces.

**Open dependency:** need the specific Sharp Football page URLs (offense-vs-coverage first).
