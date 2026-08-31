"""Sharp Football profile panel — the charted data, made glanceable.

Renders the committed Sharp tables for one team as grouped metric rows with a
league-rank percentile bar and plain-English strength/weakness notes, so the
refined data is comparable at a glance instead of a wall of numbers.

Degrades to a clear "fills in after the Action runs" note when the Sharp data
isn't committed yet.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import sharp_value as sv

# (group, table_key, [(label, *keywords, direction, fmt)])
# direction: "high" = higher is better, "low" = lower is better, "flat" = tendency (no rank)
_SPEC = [
    ("Offense — overall", "off_metrics", [
        ("EPA / play", ("epa",), "high", "{:+.3f}"),
        ("Yards / play", ("yards per play",), "high", "{:.2f}"),
        ("Points / drive", ("points per drive",), "high", "{:.2f}"),
        ("Explosive rate", ("explosive",), "high", "{:.3g}"),
        ("Down-conv rate", ("down conversion",), "high", "{:.3g}"),
    ]),
    ("Defense — overall", "def_metrics", [
        ("EPA / play allowed", ("epa",), "low", "{:+.3f}"),
        ("Yards / play allowed", ("yards per play",), "low", "{:.2f}"),
        ("Points / drive allowed", ("points per drive",), "low", "{:.2f}"),
        ("Explosive rate allowed", ("explosive",), "low", "{:.3g}"),
        ("Down-conv allowed", ("down conversion",), "low", "{:.3g}"),
    ]),
    ("Pass protection (O-line)", "off_line", [
        ("Pressure rate allowed", ("pressure", "allowed"), "low", "{:.3g}"),
        ("No-blitz pressure allowed", ("no blitz", "allowed"), "low", "{:.3g}"),
        ("Time to throw", ("time to throw",), "high", "{:.2f}"),
        ("YBC / RB rush (run block)", ("yards before contact",), "high", "{:.2f}"),
    ]),
    ("Pass rush (D-line)", "def_line", [
        ("Pressure rate", ("pressure", "rate"), "high", "{:.3g}"),
        ("No-blitz pressure rate", ("no blitz",), "high", "{:.3g}"),
        ("YBC / RB rush allowed", ("yards before contact",), "low", "{:.2f}"),
        ("Rush-stuff rate", ("rush stuff",), "high", "{:.3g}"),
    ]),
    ("Coverage by position (YPT allowed)", "coverage_by_pos", [
        ("vs WR", ("ypt", "wr"), "low", "{:.2f}"),
        ("vs TE", ("ypt", "te"), "low", "{:.2f}"),
        ("vs RB", ("ypt", "rb"), "low", "{:.2f}"),
        ("vs Slot", ("ypt", "slot"), "low", "{:.2f}"),
        ("vs Outside", ("ypt", "outside"), "low", "{:.2f}"),
    ]),
    ("Coverage scheme", "coverage_schemes", [
        ("Man rate", ("man",), "flat", "{:.3g}"),
        ("Zone rate", ("zone",), "flat", "{:.3g}"),
        ("Middle-open rate", ("middle open",), "flat", "{:.3g}"),
    ]),
    ("Defensive tendencies", "def_tendencies", [
        ("Blitz rate", ("blitz",), "flat", "{:.3g}"),
        ("Light-box rate", ("light box",), "flat", "{:.3g}"),
        ("Heavy-box rate", ("heavy box",), "flat", "{:.3g}"),
    ]),
    ("Pace & style", "pace", [
        ("Neutral sec/play", ("neutral",), "flat", "{:.2f}"),
        ("Neutral pass rate", ("neutral", "pass"), "flat", "{:.3g}"),
        ("No-huddle rate", ("no huddle",), "flat", "{:.3g}"),
    ]),
    ("Personnel usage", "off_personnel", [
        ("11 personnel", ("11",), "flat", "{:.3g}"),
        ("12 personnel", ("12",), "flat", "{:.3g}"),
        ("2+ TE", ("2+ te",), "flat", "{:.3g}"),
        ("3+ WR", ("3+ wr",), "flat", "{:.3g}"),
    ]),
]


def _rank(series: pd.Series, direction: str) -> pd.Series:
    asc = (direction == "low")
    return series.rank(ascending=asc, method="min")


def _group_rows(df: pd.DataFrame, team: str, specs: list) -> tuple[list, list]:
    """Return (display rows, (label, rank) scorables) for one group/team."""
    rows, scor = [], []
    for label, keywords, direction, fmt in specs:
        s = sv._series(df, *keywords)  # noqa: SLF001 - shared accessor
        if s is None or team not in s.index or pd.isna(s.get(team)):
            continue
        val = float(s.loc[team])
        try:
            vtxt = fmt.format(val)
        except Exception:  # noqa: BLE001
            vtxt = f"{val:.2f}"
        if direction == "flat":
            rows.append({"Metric": label, "Value": vtxt, "Pctl": None, "_rank": None})
        else:
            r = int(_rank(s, direction).loc[team])
            rows.append({"Metric": label, "Value": vtxt, "Pctl": (33 - r) / 32.0, "_rank": r})
            scor.append((label, r))
    return rows, scor


def render_team(sharp: dict, team: str) -> None:
    st.markdown("##### Sharp Football profile")
    if not sv.available(sharp):
        st.info("Sharp Football data fills in after the weekly Action commits it "
                "(pace, personnel, trenches, coverage, and overall metrics). "
                "Run **Actions → Update model data → Run workflow** to populate it now.")
        return

    all_scor: list = []
    cols = st.columns(2)
    i = 0
    for group, key, specs in _SPEC:
        df = sharp.get(key)
        if df is None or df.empty:
            continue
        rows, scor = _group_rows(df, team, specs)
        if not rows:
            continue
        all_scor += scor
        with cols[i % 2]:
            st.caption(group)
            st.dataframe(pd.DataFrame(rows).drop(columns="_rank"),
                         width="stretch", hide_index=True, column_config={
                "Pctl": st.column_config.ProgressColumn(
                    "League", format=" ", min_value=0.0, max_value=1.0,
                    help="League percentile (full bar = 1st, empty = 32nd)."),
            })
        i += 1

    # auto notes: best and worst ranked charted metrics
    if all_scor:
        best = sorted(all_scor, key=lambda x: x[1])[:3]
        worst = sorted(all_scor, key=lambda x: -x[1])[:3]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sharp edges** 🟢")
            for lab, r in best:
                st.markdown(f"- {lab} — **{_ord(r)}**")
        with c2:
            st.markdown("**Sharp soft spots** 🔴")
            for lab, r in worst:
                st.markdown(f"- {lab} — **{_ord(r)}**")
    st.caption("Charted by Sharp Football Analysis, refreshed weekly by the Action. "
               "Bars are league percentile; edges/soft-spots read the extremes.")


def _ord(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
