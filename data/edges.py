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
    """Scheme-fit edge: does the offense exploit the coverage the D plays most?

    Dormant until PFF offense-vs-coverage data is present (extras['off_vs_cov'])
    alongside defensive zone/man rates (extras['coverage']). Then a zone-beating
    offense facing a zone-heavy defense earns a weighted edge, and vice versa.
    """
    cov = extras.get("coverage")           # defense zone/man rates (blended)
    ovc = extras.get("off_vs_cov")         # offense EPA vs zone / vs man (PFF)
    if cov is None or ovc is None:
        return None
    if getattr(cov, "empty", True) or d_team not in cov.index or o_team not in ovc.index:
        return None
    zone = cov.loc[d_team].get("zone_rate")
    if pd.isna(zone):
        return None
    # offense's edge = how well it does against the scheme the D leans on
    z_edge = ovc.loc[o_team].get("vs_zone_rank")   # 1 = best vs zone
    m_edge = ovc.loc[o_team].get("vs_man_rank")
    lean_rank = z_edge if zone >= 0.5 else m_edge
    scheme = "zone" if zone >= 0.5 else "man"
    if pd.isna(lean_rank):
        return None
    # more extreme scheme reliance => bigger swing; offense skill vs that scheme
    reliance = abs(zone - 0.5) * 2  # 0..1
    m = (16.5 - int(lean_rank)) * (0.5 + reliance)  # + = offense exploits it
    w = _weight("Coverage scheme")
    return {"label": "Coverage scheme", "mag": float(m), "weight": w, "impact": float(m) * w,
            "detail": f"{o_team} vs {scheme} ({_ord(lean_rank)}) · {d_team} {zone*100:.0f}% zone"}


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
