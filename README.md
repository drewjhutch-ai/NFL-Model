# NFL Model

A Streamlit dashboard for NFL team tendencies, matchup edges, and weekly picks.

The data you actually use to make picks, in one place: offensive & defensive
rankings (pass / rush), play-style leans, blitz tendencies, and matchup
comparisons — with true zone/man coverage ready to plug in from a paid feed.

## Status

**Foundation (v1)** — built and working:

- **📊 Team Data** — per-team offense & defense profiles with 1–32 ranks
  (EPA/play, pass & rush EPA, success rates, explosive rate), play-style lean
  (neutral pass rate / PROE), blitz tendency (from FTN charting), and league
  tables you can sort.
- **⚔️ Matchups** — pick any two teams and see where the edges are
  (offense unit rank vs. the defense unit it faces), both directions.
- **🎯 Picks of the Week** — placeholder; next milestone.

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
| **Zone/man coverage scheme** | **Paid feed (pluggable)** | Paid |

True coverage-scheme splits aren't available for free. The app talks to a single
`SchemeDataProvider` interface (`data/providers/`), so a paid feed drops in
without touching the rest of the app. Until then:

- Drop a CSV at `scheme_data/coverage_<season>.csv` (columns:
  `team, zone_rate, man_rate, snaps`) — e.g. a manual export from a paid tool —
  and coverage lights up immediately.
- Or implement a new provider (copy `data/providers/manual_csv.py`) against your
  chosen API and point `data/providers/get_provider()` at it.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

First load pulls data from nflverse over the network and caches it for an hour.
Use the sidebar **Refresh data** button to force a re-pull (e.g. after a new
week during the season).

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
