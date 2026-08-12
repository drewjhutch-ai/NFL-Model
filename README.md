# NFL Model

A Streamlit dashboard for NFL team tendencies, matchup edges, and weekly picks.

The data you actually use to make picks, in one place: offensive & defensive
rankings (pass / rush), play-style leans, blitz tendencies, and matchup
comparisons — with true zone/man coverage ready to plug in from a paid feed.

## Status

**Foundation (v1)** — built and working:

- **📊 Team Data** — a visual per-team scouting profile: **percentile charts**
  for offense & defense, an analytical **Run/Pass identity** (neutral rate +
  PROE + percentile), split **Strengths vs Struggles** (broad headline + the
  ultra-specific chink), plus notes for QB mobility, ground-game RYOE, pass rush,
  blitz %, coverage (zone/man), and **blitz vulnerability**.
- **📋 League** — sortable league-wide tables (offense / defense / blitz-scheme),
  percent-formatted with plain-language columns and tooltips.
- **⚔️ Matchups** — layered pro head-to-head: projected **lean + confidence
  stars**, a **Monte Carlo simulation** (win % / cover % / over % / projected
  score / margin distribution), the weighted **"where's the edge" chart**, and
  drill-downs for **trenches** (O-line vs D-line), WR1/2/3, situational, and
  environment (weather/rest/**bye & short-week spots**), with layered scouting notes.
- **🧍 Players** — per-game usage and **matchup-adjusted prop projections**
  (pass/rush/rec) vs the opponent's defense-by-position.
- **💰 Betting** — our model vs. the market. Projects each game to a spread +
  win probability from our efficiency data (power ratings), compares it to the
  book's spread/total/moneyline, and flags **value** and **favorite
  disagreements**. When we differ it explains **why** (our weighted drivers) and
  **what the book may price that we don't** (injuries, rest, weather, division).
  Line-movement / sharp-money signals plug in via a live odds feed when connected.
- **🎯 Picks of the Week** — simulation-based **value plays with Kelly stake
  sizing**, auto-surfaced model leans, and a personal pick log you can export.

## Edges are weighted by what actually decides NFL games

Matchup facets are **not** treated as equal. Each is weighted by its real
predictive value in the modern NFL (grounded in public analytics — passing/QB
EPA and pressure are the sticky, predictive signals; rushing EPA and red-zone
TD% are weak/regression-prone; RB receiving is a small slice):

| Facet | Weight | Facet | Weight |
|-------|:------:|-------|:------:|
| QB / Passing | 2.4 | 3rd down | 0.9 |
| Pass rush | 1.4 | Red zone | 0.7 |
| Coverage scheme* | 1.3 | Rushing | 0.6 |
| Explosive | 1.3 | TE receiving | 0.6 |
| WR receiving | 1.1 | RB receiving | 0.35 |

\* activates when PFF offense-vs-coverage data is uploaded (a zone-beating
offense vs a zone-heavy defense then earns a weighted edge). Weights live in
`config.EDGE_WEIGHTS`. On the matchup chart, bar **length** = raw edge, bar
**thickness** = weight, ordered by **impact** (edge × weight) — so QB/passing
dominates and RB receiving stays small even on a big raw edge.

## Live odds (optional, free) — unlocks line shopping + sharp signal

The Betting tab works off the free schedule consensus line out of the box. To add
multi-book line shopping, a sharp-book-vs-consensus signal, and line movement,
connect **The Odds API** (free tier ~500 requests/mo):

1. Get a key at [the-odds-api.com](https://the-odds-api.com).
2. Add it as `ODDS_API_KEY` — in `.streamlit/secrets.toml` locally / the Streamlit
   Cloud **Secrets** box when hosted, or as an environment variable.
3. The tab auto-detects it and lights up the live-odds section.

True bet%/handle% "sharp splits" are paid; as a free proxy we compare a sharp
book (Pinnacle, etc.) to the market consensus. Line movement is built from
snapshots the app stores as it runs.

## Accuracy & methodology

The ratings and betting projection are built the way modern models are:

- **Opponent-adjusted EPA** (strength of schedule) — `data/adjust.py` solves
  offense/defense fixed-effect ratings so numbers reflect *who* you played.
- **Recency + shrinkage** — recent games weigh more within a season; noisy
  small-sample stats (red zone, 3rd down) are shrunk toward the mean.
- **QB value, special teams, team home field** fold into the projected line; the
  number actually drops when a starting QB is ruled Out.
- **Weather** — wind/cold move the total and compress the margin (domes exempt).
- **Market-aware** — we blend toward the closing line (the best predictor) and
  size value off the blended edge, with confidence + key-number (3/7) awareness.
- **Backtest + learning loop** — `python scripts/backtest.py [season]` produces
  honest out-of-sample accuracy and measures which facets actually predicted real
  margins (surfaced in the Betting tab). Tunable knobs live in `config.py`.

## The data philosophy: current season drives everything

The NFL moves fast, so last season is basically old news. Every ranking and
tendency is computed from **recency-weighted** play-by-play:

- The **current season** (`config.CURRENT_SEASON`) drives all numbers.
- The **prior season** is a *phantom baseline* with a near-zero weight
  (`config.PRIOR_SEASON_WEIGHT`, default `1e-6`). It only shows through during
  the offseason / first weeks before enough current-season games exist. The
  instant real games are played, current-season data overwhelms it.

Tune both in `config.py`.

## Data sources

| Data | Source | Cost |
|------|--------|------|
| Play-by-play, EPA, success, pass/rush splits, PROE | nflverse (`nfl_data_py`) | Free |
| Blitz rate, box count, play-action | FTN charting (`nfl_data_py`, 2022+) | Free |
| **Zone/man coverage scheme** | **Blended: PFF + SumerSports + StatRankings** | Free + optional PFF |

### Coverage scheme is *blended*, not single-source

True coverage-scheme splits aren't in the free play-by-play data, so instead of
trusting one feed the app pulls from several and fuses them:

| Source | Access | Trust weight |
|--------|--------|-------------|
| **PFF** (ELITE/+) | Manual CSV export → `scheme_data/pff_coverage_<season>.csv` | 1.0 |
| **SumerSports** | Free web scrape | 0.85 |
| **StatRankings** | Free web scrape | 0.75 |

The `CompositeSchemeProvider` (`data/providers/composite.py`):

1. Pulls every source that's available (a source failing never breaks the rest).
2. Normalizes teams to canonical abbreviations (`data/teams.py`).
3. Blends per team with a **trust-weighted average** — PFF leads, the free
   sources back it up, so no single source can skew a number.
4. Scores **agreement**: if the sources cluster tightly → *High* confidence; if
   they diverge → *Low*. Shown in the UI, with a per-team source breakdown, so
   the blend is transparent rather than a black box.

Tune trust weights and confidence thresholds in `config.py`
(`SCHEME_SOURCE_TRUST`, `SCHEME_AGREE_*`).

**PFF is free-ish and optional:** you don't need it to start (the two free
scrapers cover zone/man on their own). Add a PFF export when you want its
gold-standard charting to anchor the blend.

**The scrapers self-heal for JavaScript pages.** Each free scraper first tries a
fast HTTP fetch; if a site builds its tables with JavaScript (SumerSports likely
does), it automatically falls back to driving a real headless browser
(Playwright/Chromium) and reads the rendered page. You don't configure anything —
just make sure Playwright is set up (below) so the fallback is available.

**Verify the scrapers locally** (the build sandbox can't reach the stats sites,
so this is the real test):

```bash
python scripts/test_providers.py
```

It prints what each source returned and the blended consensus.

## Host it (no terminal) — recommended

Deploy free to Streamlit Community Cloud and just visit a URL. Step-by-step:
**[DEPLOY.md](DEPLOY.md)**. The repo is already configured for it
(`requirements.txt`, `packages.txt` for Chromium, in-app PFF upload).

## Run it locally instead

```bash
pip install -r requirements.txt
playwright install chromium   # one-time; enables the JS-page scraper fallback
streamlit run app.py
```

First load pulls data from nflverse over the network and caches it for an hour.
Use the sidebar **Refresh data** button to force a re-pull (e.g. after a new
week during the season).

> The `playwright install chromium` step downloads a headless browser (~150 MB)
> used only when a free stats site renders its tables with JavaScript. If you
> skip it, everything else still works and the scrapers simply fall back to
> "unavailable" for any JS-only site.

## Layout

```
app.py                     # Streamlit entry point, tabs
config.py                  # seasons, recency weights, thresholds
data/
  loaders.py               # nflverse / FTN pulls (cached, season-tolerant)
  tendencies.py            # weighted aggregation -> ranks & tendencies
  providers/               # pluggable scheme-data (zone/man) providers
ui/
  team_tendencies.py       # 📊 Team Data tab
  matchups.py              # ⚔️ Matchups tab
  picks.py                 # 🎯 Picks tab (stub)
  components.py            # shared rendering helpers
```

## Next milestones

- Connect the chosen paid scheme feed (zone/man).
- Build out **Picks of the Week**: auto-surfaced edges + a pick log with a
  season-long track record.
