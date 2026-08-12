#!/usr/bin/env python3
"""Generate model-performance results the app can display.

    python scripts/backtest.py [season]     # default: 2024

Runs an out-of-sample walk-forward backtest + facet-predictiveness analysis for
the season and writes backtest_results.json at the repo root. The Betting tab's
"Model performance" panel reads that file.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data import backtest, loaders  # noqa: E402


def main(season: int) -> None:
    print(f"Loading {season} play-by-play + schedule…")
    pbp = loaders.load_pbp.__wrapped__((season,))
    sched = loaders.load_schedule.__wrapped__((season,))

    print("Walk-forward backtest (out-of-sample)…")
    res = backtest.walk_forward(pbp, sched, season)
    summary = backtest.summary(res)

    print("Facet predictiveness…")
    fp = backtest.facet_predictiveness(pbp, sched, season)

    payload = {
        "season": season,
        "summary": summary,
        "facets": fp.reset_index().rename(columns={"index": "facet"}).round(3).to_dict("records")
        if not fp.empty else [],
    }
    out = Path(__file__).resolve().parents[1] / "backtest_results.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved → {out}")
    print(f"Games {summary.get('games')} · model MAE {summary.get('model_mae'):.2f} "
          f"vs market {summary.get('market_mae'):.2f} · ATS {summary.get('ats_pct'):.1f}% "
          f"· SU {summary.get('su_pct'):.1f}%")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2024)
