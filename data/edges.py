"""Unified matchup edge engine.

One function computes every facet edge for a direction (one team's offense vs the
other's defense) on a single consistent scale: positive = offense edge, negative
= defense edge, roughly -31..+31. Everything else — the matchup chart, the
headline verdict, the Picks leans — is built on top of it, so the numbers always
agree.
"""
from __future__ import annotations

import pandas as pd

import config


def _ord(n) -> str:
    if n is None or pd.isna(n):
        return "—"
    n = int(n)
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _mag(off_rank, def_rank):
    """Offense strong (low rank) vs defense weak (high rank) => positive edge.

    Both ranks are 1 (best) .. 32 (worst). A weak defense (high def_rank) facing
    a strong offense (low off_rank) yields a large positive edge; range -31..+31.
    """
    if pd.isna(off_rank) or pd.isna(def_rank):
        return None
    return int(def_rank) - int(off_rank)


def _get(df, team, col):
    if df is None or getattr(df, "empty", True) or team not in df.index or col not in df.columns:
        return None
    return df.loc[team, col]


def _weight(label: str) -> float:
    return float(config.EDGE_WEIGHTS.get(label, config.DEFAULT_EDGE_WEIGHT))


def _coverage_edge(o_team: str, d_team: str, extras: dict) -> dict | None:
    """Scheme-fit edge: does the offense's scheme strength match what the D over-plays?

    Needs defensive zone/man rates (``extras['coverage']``) and derived
    offense-vs-coverage (``extras['off_vs_cov']`` — see ``data/off_coverage.py``,
    built from pbp cross-referenced with those same defensive rates).

    The signal is the offense's *scheme affinity* (how much better it throws vs
    zone than vs man, baseline-removed and z-scored) multiplied by how hard the
    defense leans on one scheme. A zone-friendly offense facing a zone-heavy
    defense earns a positive (offense) edge; facing a man-heavy defense, a
    negative one. Baseline removal keeps this orthogonal to the QB/passing facet
    (overall passing quality lives there, not here).
    """
    cov = extras.get("coverage")           # defense zone/man rates (blended)
    ovc = extras.get("off_vs_cov")         # offense affinity vs zone/man (derived)
    if cov is None or ovc is None:
        return None
    if getattr(cov, "empty", True) or getattr(ovc, "empty", True):
        return None
    if d_team not in cov.index or o_team not in ovc.index:
        return None
    zone = cov.loc[d_team].get("zone_rate")
    az = ovc.loc[o_team].get("affinity_z")   # + = offense better vs zone than man
    if pd.isna(zone) or pd.isna(az):
        return None
    reliance = (float(zone) - 0.5) * 2.0     # signed: + zone-heavy, − man-heavy
    # ~±8 keeps the magnitude comparable to the rank-diff facets (-31..+31).
    m = float(az) * reliance * 8.0
    off_pref = "zone" if az >= 0 else "man"
    d_scheme = "zone" if reliance >= 0 else "man"
    w = _weight("Coverage scheme")
    return {"label": "Coverage scheme", "mag": m, "weight": w, "impact": m * w,
            "detail": f"{o_team} {off_pref}-friendly vs {d_team} "
                      f"{float(zone)*100:.0f}% {d_scheme}"}


def facet_edges(o_team: str, d_team: str, off: pd.DataFrame, deff: pd.DataFrame,
                extras: dict) -> list[dict]:
    """All weighted facet edges for o_team's offense attacking d_team's defense.

    Each edge carries ``mag`` (raw rank differential, +offense), ``weight`` (how
    much the facet matters in the modern NFL), and ``impact`` = mag × weight.
    """
    if o_team not in off.index or d_team not in deff.index:
        return []
    o, d = off.loc[o_team], deff.loc[d_team]
    dvp = extras.get("dvp") or {}
    usage = extras.get("usage")
    off_sit, def_sit = extras.get("off_sit"), extras.get("def_sit")
    prot, prs = extras.get("protection"), extras.get("pressure")

    edges: list[dict] = []

    def add(label, orank, drank, detail):
        m = _mag(orank, drank)
        if m is None:
            return
        w = _weight(label)
        edges.append({"label": label, "mag": float(m), "weight": w,
                      "impact": float(m) * w, "detail": detail})

    add("QB / Passing", o.get("qb_rank"), d.get("pass_epa_rank"),
        f"{o_team} QB/pass {_ord(o.get('qb_rank'))} vs {d_team} pass D {_ord(d.get('pass_epa_rank'))}")
    add("Pass rush", _get(prot, o_team, "protection_rank"), _get(prs, d_team, "pressure_rate_rank"),
        f"{o_team} pass-pro {_ord(_get(prot, o_team, 'protection_rank'))} vs "
        f"{d_team} rush {_ord(_get(prs, d_team, 'pressure_rate_rank'))}")
    add("Explosive", o.get("explosive_rate_rank"), d.get("explosive_rate_rank"),
        f"{o_team} {_ord(o.get('explosive_rate_rank'))} big plays vs {d_team} D {_ord(d.get('explosive_rate_rank'))}")
    add("Rushing", o.get("rush_epa_rank"), d.get("rush_epa_rank"),
        f"{o_team} {_ord(o.get('rush_epa_rank'))} rush vs {d_team} run D {_ord(d.get('rush_epa_rank'))}")
    add("3rd down", _get(off_sit, o_team, "third_rank"), _get(def_sit, d_team, "third_rank"),
        f"{o_team} {_ord(_get(off_sit, o_team, 'third_rank'))} vs {d_team} {_ord(_get(def_sit, d_team, 'third_rank'))}")
    add("Red zone", _get(off_sit, o_team, "rz_rank"), _get(def_sit, d_team, "rz_rank"),
        f"{o_team} {_ord(_get(off_sit, o_team, 'rz_rank'))} vs {d_team} {_ord(_get(def_sit, d_team, 'rz_rank'))}")

    if usage is not None and not usage.empty and o_team in usage.index:
        for pos in ("WR", "TE", "RB"):
            share_rank = usage.loc[o_team].get(f"{pos}_share_rank")
            def_rank = _get(dvp.get(pos), d_team, "def_rank")
            m = _mag(share_rank, def_rank)
            if m is None:
                continue
            share = usage.loc[o_team].get(f"{pos}_tgt_share")
            share_txt = f"{share * 100:.0f}% tgts" if pd.notna(share) else ""
            label = f"{pos} receiving"
            w = _weight(label)
            edges.append({"label": label, "mag": float(m), "weight": w, "impact": float(m) * w,
                          "detail": f"{o_team} {pos} {share_txt} vs {d_team} allows "
                                    f"{_ord(33 - int(def_rank))}-most"})

    cov = _coverage_edge(o_team, d_team, extras)
    if cov:
        edges.append(cov)
    return edges


def direction_net(edges: list[dict]) -> float:
    """Weighted attack score: how big is this offense's edge, importance-weighted."""
    if not edges:
        return 0.0
    wsum = sum(e["weight"] for e in edges)
    return sum(e["impact"] for e in edges) / wsum if wsum else 0.0


def collect_game_edges(away: str, home: str, off: pd.DataFrame, deff: pd.DataFrame,
                       extras: dict) -> list[dict]:
    out = []
    for o_team, d_team in ((away, home), (home, away)):
        for e in facet_edges(o_team, d_team, off, deff, extras):
            out.append({"Game": f"{away} @ {home}", "Edge": f"{o_team} {e['label']}",
                        "Detail": e["detail"], "mag": e["mag"], "impact": e["impact"]})
    return out


def week_leans(games: pd.DataFrame, off: pd.DataFrame, deff: pd.DataFrame,
               extras: dict, top_n: int = 20) -> pd.DataFrame:
    rows = []
    for r in games.itertuples():
        rows += collect_game_edges(r.away_team, r.home_team, off, deff, extras)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("impact", ascending=False)
    df = df[df["impact"] >= 12]
    return df.head(top_n).reset_index(drop=True)
