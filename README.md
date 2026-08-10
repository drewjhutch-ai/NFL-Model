# NFL Model

A Streamlit dashboard for NFL team tendencies, matchup edges, and weekly picks.

The data you actually use to make picks, in one place: offensive & defensive
rankings (pass / rush), play-style leans, blitz tendencies, and matchup
comparisons — with true zone/man coverage ready to plug in from a paid feed.

## Status

**Foundation (v1)** — built and working:

- **📊 Team Data** — per-team offense & defense profiles with 1–32 ranks
  (EPA/play, pass & rush EPA, success rates, explosive rate), play-style lean
  (neutral pass rate / PROE), **QB mobility**, **ground-game efficiency (RYOE)**,
  **pass-rush pressure & sack rates**, blitz tendency (FTN), and league tables.
- **⚔️ Matchups** — the week's games auto-load from the schedule; each game
  breaks down into **unit edges** (pass/rush/explosive/overall) *and*
  **positional edges** — does a team feature a weapon (e.g. pass-catching RBs)
  that the opponent struggles to cover (RB/WR/TE target share vs. EPA/target
  allowed)? Custom any-two-teams comparison still available.
- **🎯 Picks of the Week** — auto-surfaced model leans (the week's biggest unit
  + positional mismatches, ranked) plus a personal pick log you can export to CSV.

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
