"""V10-S2 — the series axis of the primitives, and one operator over it (offline).

Live behaviour is proved in test_v10_series_parity_live and test_v10_tools_live.
Here: the shapes that must hold whatever the data says, and the absences.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from exposure_workbench.analytics import interval_algebra as ia, series_ops as so
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services import series_service as ss
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def _flows(spec):
    """(start, end, value) triples -> FlowFacts."""
    return [ia.FlowFact(fact_id=f"fact_{i}", period_start=date.fromisoformat(a),
                        period_end=date.fromisoformat(b), value=float(v))
            for i, (a, b, v) in enumerate(spec)]


# ── the engine ────────────────────────────────────────────────────────────────

def test_a_cumulative_filer_yields_every_quarter_the_ladder_could_not():
    """AAPL's shape: Q1, H1, 9M, FY. The ladder kept Q1 and derived Q4; H1 and
    9M were "other" and thrown away, so Q2 and Q3 did not exist. Here they are
    paths — H1 − Q1 and 9M − H1 — and the series has four slots."""
    facts = _flows([("2025-01-01", "2025-03-31", 10), ("2025-01-01", "2025-06-30", 25),
                    ("2025-01-01", "2025-09-30", 45), ("2025-01-01", "2025-12-31", 70)])
    s = ia.consecutive_windows(facts, months=3, last_n=4)
    assert [w.value for w in s] == [10, 15, 20, 25]
    assert [w.end.isoformat() for w in s] == ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def test_an_annual_series_ends_where_the_issuer_ends_its_year():
    """The correction the whole-corpus parity forced. latest_window(12) ends at
    the latest boundary a year can be derived TO — the June quarter, on a
    September filer with cumulative facts — and a series stepped back from
    there is a series of Junes. The phase is the issuer's."""
    facts = _flows([
        ("2024-10-01", "2024-12-31", 30), ("2024-10-01", "2025-03-31", 60),
        ("2024-10-01", "2025-06-30", 90), ("2024-10-01", "2025-09-30", 120),   # FY2025
        ("2023-10-01", "2024-09-30", 100),                                       # FY2024
        ("2025-10-01", "2025-12-31", 35), ("2025-10-01", "2026-03-31", 70),
        ("2025-10-01", "2026-06-30", 105),                                       # 9M FY2026
    ])
    ttm = ia.latest_window(facts, months=12)
    assert isinstance(ttm, ia.Derived) and ttm.end == date(2026, 6, 30)
    s = ia.consecutive_windows(facts, months=12, last_n=2)
    assert [w.end for w in s] == [date(2024, 9, 30), date(2025, 9, 30)]
    assert [w.value for w in s] == [100, 120]


def test_a_gap_is_kept_in_place_and_the_walk_continues():
    """DP2, and the NVDA case: a year filed as 9M + FY has no boundary a
    quarter before the 9M end. The slot is unreachable where it is; the walk
    steps over it and re-locks to the grid on the far side."""
    facts = _flows([("2024-01-01", "2024-03-31", 10), ("2024-04-01", "2024-06-30", 11),
                    ("2024-07-01", "2024-09-30", 12), ("2024-10-01", "2024-12-31", 13),
                    ("2025-01-01", "2025-09-30", 40), ("2025-01-01", "2025-12-31", 55),
                    ("2026-01-01", "2026-03-31", 20)])
    s = ia.consecutive_windows(facts, months=3, last_n=9)
    ends = [w.end.isoformat() for w in s]
    assert ends[-1] == "2026-03-31" and ends[0] == "2024-03-31", ends
    kinds = ["U" if isinstance(w.window, ia.Unreachable) else "D" for w in s]
    # 2024: four quarters; 2025: Q1..Q3 unreachable (9M only), Q4 = FY − 9M; 2026 Q1.
    assert kinds == ["D", "D", "D", "D", "U", "U", "U", "D", "D"], kinds
    assert s[7].value == 15


def test_leading_gaps_are_trimmed_and_interior_ones_are_not():
    facts = _flows([("2025-04-01", "2025-06-30", 5), ("2025-10-01", "2025-12-31", 7)])
    s = ia.consecutive_windows(facts, months=3, last_n=8)
    assert not isinstance(s[0].window, ia.Unreachable)
    assert any(isinstance(w.window, ia.Unreachable) for w in s[1:-1])


def test_a_series_never_serves_a_shorter_window_under_a_longer_name():
    """No fallback. Only a 9M fact: a twelve-month series has nothing to say."""
    facts = _flows([("2025-01-01", "2025-09-30", 40)])
    assert ia.consecutive_windows(facts, months=12, last_n=3) == []


def test_restatement_rule_has_one_home():
    """Most recently filed wins; filing_date first, accession as the tiebreak
    that sorts chronologically within an issuer. Lived in the ladder; the
    ladder is a frozen test fixture now and imports it from the engine."""
    from tests import legacy_ladder as pl
    assert pl.restatement_key is ia.restatement_key
    k = ia.restatement_key
    assert k(date(2026, 2, 1), "a") > k(date(2025, 2, 1), "z")
    assert k(None, "0001-25") < k(None, "0001-26")
    assert k(None, "z") < k(date(2000, 1, 1), "a")


# ── the tools ─────────────────────────────────────────────────────────────────

def test_last_n_has_a_floor():
    """0 asked for none and got all forty; -20 on a twelve-point series returned
    an empty series with a citable id. Inherited from get_fact_series, and kept."""
    reg = build_meta_registry()
    for name in ("get_flow", "get_balance_series"):
        ln = reg.tools[name].json_schema["properties"]["last_n"]
        assert ln["minimum"] == 1 and ln["maximum"] == 40, name


def test_series_stat_is_the_union_of_both_old_operators_and_nothing_else():
    """Real use: yoy 74, latest 4, qoq 2, abs 1. None of the eleven can go, and
    an op that neither old tool had would be new capability, which this batch
    does not add."""
    assert set(ss.OPS) == set(so.CHANGE_MODES) | set(so.STAT_OPS)
    reg = build_meta_registry()
    assert set(reg.tools["series_stat"].json_schema["properties"]["op"]["enum"]) == set(ss.OPS)


def test_series_stat_takes_an_id_not_a_fetch_spec():
    """The whole point. compute_change took (ticker, metric, period_type,
    last_n, mode): the fetch and the operator in one breath, re-spelled on
    every operator. series_stat takes what the fetch produced."""
    props = set(build_meta_registry().tools["series_stat"].json_schema["properties"])
    assert props == {"series_id", "op"}


def test_the_new_tools_are_on_both_faces():
    meta = set(faces.resolve(build_meta_registry(), faces.FACE_META_AGENT))
    research = set(faces.resolve(build_research_registry(), faces.FACE_RESEARCH))
    for name in ("get_balance_series", "series_stat", "describe_issuer"):
        assert name in meta and name in research, name


def test_describe_issuer_names_the_missing_input_not_a_hole():
    src = inspect.getsource(build_meta_registry().tools["describe_issuer"].fn)
    assert '"computable"' in src and '"missing_inputs"' in src


# ── the calculator over series ───────────────────────────────────────────────

def test_the_resolver_believes_a_recorded_type_over_the_op_table():
    """A `stat.latest` over a margin series is a ratio; the operation name says
    nothing about what it was taken over. Rows that recorded their type are
    believed; the table stays for the rows that did not."""
    src = inspect.getsource(qn._calc_unit)
    assert 'result_type' in src
    assert src.index("result_type") < src.index("_CALC_RATIO_OPS")


def test_a_refused_pair_refuses_the_whole_series_and_names_the_slot():
    """A series with one silently dropped point lies about its length."""
    src = inspect.getsource(tc._calculate_series)
    assert '"at": end.isoformat()' in src


def test_alignment_tolerance_is_the_engines_not_a_new_number():
    assert tc._ALIGN_DAYS == ia.BOUNDARY_TOLERANCE_DAYS


def test_an_untyped_series_is_refused_with_the_tool_that_makes_a_typed_one():
    out = tc._resolve_series("calc_old", "series", {}, [{"end": "2025-01-01", "value": 1.0}])
    assert out["error"] == "untyped_operand" and "get_flow" in out["detail"]
