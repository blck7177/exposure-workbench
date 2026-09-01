"""V15-S2a — one table, three exits, and nothing citable that is not on it.

What the model saw and what the gate allowed used to be two mechanisms: the
context held a capped dump of the result, the trail held whatever a walker
found id-shaped in the UNcapped result provided it did not look like an error.
A refused read's `absence_id` sat under an `error` key and never reached the
trail; 189 of 191 "unknown" ids in one battery were real rows the gate's set
did not hold. These tests pin the replacement: a tool DECLARES what it put on
the table, the same declaration is what the model reads and what the gate
resolves against, and the resolver is a set of lookups over that table.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import resources as rs
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import resolver
from exposure_workbench.services import table as tb

MONEY, RATIO, COUNT = qn.MONEY, qn.RATIO, qn.COUNT


# ── declare ───────────────────────────────────────────────────────────────────

def test_every_id_shaped_string_in_a_result_is_declared_with_its_type():
    out = tb.declare({"calc_id": "calc_1", "chunks": [{"id": "chunk_2"}], "fact": "fact_3",
                      "alerts": ["alert_4"], "source": {"id": "src_5"}, "position": "pos_6"})
    assert out["evidence"] == [
        {"type": "calc", "id": "calc_1"}, {"type": "chunk", "id": "chunk_2"},
        {"type": "fact", "id": "fact_3"}, {"type": "alert", "id": "alert_4"},
        {"type": "source", "id": "src_5"}, {"type": "position", "id": "pos_6"},
    ]


def test_a_run_id_without_scope_or_names_is_not_declared():
    """A run is not evidence until a child of it has been read: get_task_status
    echoing a run id must not put 235 quantities on the table."""
    assert tb.declare({"run_id": "run_1", "status": "completed"})["evidence"] == []


def test_a_run_id_with_scope_carries_the_scope():
    out = tb.declare({"run_id": "run_1"}, scope=("issuer_exposures", "count"))
    assert out["evidence"] == [{"type": "run", "id": "run_1", "scope": ["issuer_exposures", "count"]}]


def test_a_run_id_with_names_carries_the_names_and_names_win_over_scope():
    """An exact read is narrower than a table read; when a tool did both, the
    record says what it read, not what it could have."""
    out = tb.declare({"run_id": "run_1"}, scope=("issuer_exposures",),
                     names=["issuer_exposures.MSFT.weight"])
    assert out["evidence"] == [{"type": "run", "id": "run_1", "names": ["issuer_exposures.MSFT.weight"]}]


def test_delegated_work_goes_on_the_table_as_a_task_row():
    out = tb.declare({"enqueued": True, "task_id": "task_1"}, tasks=["task_1", "rrun_2", "co_msft"])
    assert out["evidence"] == [
        {"type": "task", "id": "task_1", "kind": "task"},
        {"type": "task", "id": "rrun_2", "kind": "task"},
    ], "co_msft is not delegated work and is dropped"


def test_ids_are_deduped_in_first_seen_order():
    out = tb.declare({"a": "calc_1", "b": ["calc_2", "calc_1"], "c": {"d": "calc_2", "e": "chunk_3"}})
    assert [e["id"] for e in out["evidence"]] == ["calc_1", "calc_2", "chunk_3"]


def test_an_id_under_an_error_key_is_declared_all_the_same():
    """THE defect V15 fixes. A refusal that minted an absence row is a
    retrieval; the old harvester skipped anything that looked like an error,
    so the one id the model was told to cite was the one it could not."""
    out = tb.declare({"error": "not_reported", "absence_id": "calc_9",
                      "detail": "MSFT reports no depreciation_amortization"})
    assert out["evidence"] == [{"type": "calc", "id": "calc_9"}]


# ── Table ─────────────────────────────────────────────────────────────────────

def _q(value, unit, label, ref, table=None, not_alone=None, group="other"):
    return qn.Quantity(value, unit, label, ref, not_alone, table, group)


def _table() -> tb.Table:
    t = tb.Table()
    t.refs = {"run_1", "chunk_1", "calc_s", "calc_a", "task_1", "calc_x"}
    t.rows = {"run_1": "run", "chunk_1": "passage", "calc_s": qn.KIND_SERIES,
              "calc_a": qn.KIND_ABSENCE, "task_1": tb.KIND_TASK, "calc_x": qn.KIND_SCALAR}
    t.quantities = {"run_1": {
        "issuer_exposures.MSFT.weight": _q(0.1633512, RATIO, "issuer_exposures.MSFT.weight", "run_1", "issuer_exposures", group="concentration"),
        "exposure_metrics.portfolio_market_value": _q(10869311, MONEY, "exposure_metrics.portfolio_market_value", "run_1", "exposure_metrics", group="book"),
        "count.positions": _q(27, COUNT, "count.positions", "run_1", "count", group="counts"),
    }}
    t.passages = {"chunk_1": "We expect capital expenditures to increase in fiscal 2026 to support cloud demand."}
    return t


def test_table_answers_holds_names_quantity_and_kind_by_lookup():
    t = _table()
    assert t.holds("run_1") and not t.holds("run_2")
    assert t.names("run_1") == ["count.positions", "exposure_metrics.portfolio_market_value",
                                "issuer_exposures.MSFT.weight"]
    assert t.names("chunk_1") == [], "a passage holds no figures"
    assert t.quantity("run_1", "issuer_exposures.MSFT.weight").value == 0.1633512
    assert t.quantity("run_1", "weight") is None, "a short name is not a name"
    assert t.kind("calc_a") == "absence" and t.kind("task_1") == "task" and t.kind("nope") is None


# ── _filter_run ───────────────────────────────────────────────────────────────

_RUN_QS = [
    _q(0.16, RATIO, "issuer_exposures.MSFT.weight", "run_1", "issuer_exposures"),
    _q(0.31, RATIO, "sector_exposures.Technology.weight", "run_1", "sector_exposures"),
    _q(27, COUNT, "count.positions", "run_1", "count"),
]


def test_filter_run_honours_scope():
    got = tb._filter_run(_RUN_QS, {"type": "run", "id": "run_1", "scope": ["issuer_exposures", "count"]})
    assert [q.label for q in got] == ["issuer_exposures.MSFT.weight", "count.positions"]


def test_filter_run_honours_names_exactly():
    got = tb._filter_run(_RUN_QS, {"type": "run", "id": "run_1", "names": ["count.positions", "not.a.name"]})
    assert [q.label for q in got] == ["count.positions"]


def test_a_legacy_entry_without_scope_is_the_whole_run():
    """Steps written before declarations carried scope: the old trail let them
    cite the whole run, and a stored record does not get narrower after the fact."""
    got = tb._filter_run(_RUN_QS, {"type": "run", "id": "run_1"})
    assert len(got) == 3


# ── _payload ──────────────────────────────────────────────────────────────────

def test_payload_shows_reader_precision_values_passages_as_ids_and_only_assertable_rows():
    t = _table()
    out = tb._payload(t, ["run_1", "chunk_1", "calc_s", "calc_a", "task_1", "calc_x"])
    # V16 (M2): a name arrives with its meaning — [value, group] — and the
    # legend states each used group's question once, first, per payload.
    assert out["groups"] == {k: rs.GROUP_QUESTIONS[k] for k in ("book", "concentration", "counts")}
    assert out["quantities"] == {"run_1": {
        "issuer_exposures.MSFT.weight": [0.1634, "concentration"],
        "exposure_metrics.portfolio_market_value": [10869311, "book"],
        "count.positions": [27, "counts"],
    }}
    assert out["passages"] == ["chunk_1"], "the text stays in the tool result; the table lists the id"
    assert out["rows"] == {"calc_s": "series", "calc_a": "absence", "task_1": "task"}, (
        "a scalar, a run and a passage are not kinds an assertion block can point at")


def test_payload_follows_declaration_order_and_omits_what_is_absent():
    t = _table()
    out = tb._payload(t, ["calc_x"])
    assert out == {}


# ── resolve_against ───────────────────────────────────────────────────────────

def test_a_clean_answer_resolves_and_accepted_carries_text_citations_and_verified():
    t = _table()
    blocks = [
        {"type": "paragraph", "runs": ["MSFT weighs ", {"ref": "run_1", "name": "issuer_exposures.MSFT.weight"},
                                       " of the book."], "cites": ["chunk_1"]},
        {"type": "absence", "text": "the issuer files no such line", "absence_ref": "calc_a"},
        {"type": "action", "text": "a research run was started", "task_ref": "task_1"},
    ]
    v = resolver.resolve_against(blocks, t)
    assert v.ok, v.as_refusal()
    out = resolver.accepted(blocks, v)
    assert out["text"].startswith("MSFT weighs 16.3% of the book.")
    assert out["citations"] == ["run_1", "chunk_1", "calc_a"], "a task is followed, not cited"
    assert out["verified"]["figures"] == 1 and out["verified"]["sources"] == 3
    assert out["verified"]["matches"][0] == {"label": "issuer_exposures.MSFT.weight", "value": 0.1633512,
                                             "unit_class": "RATIO", "source_id": "run_1"}
    assert out["blocks"][0]["runs"][1]["slot"]["value"] == 0.1633512


def test_an_id_not_on_the_table_is_refused_by_membership():
    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["x ", {"ref": "run_2", "name": "issuer_exposures.MSFT.weight"}]}], _table())
    assert v.error == "not_on_table"
    assert v.problems == [{"id": "run_2", "reason": "not_on_table"}]


def test_an_unknown_name_is_refused_with_the_names_the_ref_does_hold():
    """The refusal IS the way forward: 123 of 196 refusals on the old gate were
    a name the model had never been handed."""
    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["x ", {"ref": "run_1", "name": "weight"}]}], _table())
    assert v.error == "unknown_name"
    [p] = v.problems
    assert p["at"] == "blocks[0].runs[1]" and p["name"] == "weight"
    assert p["available"] == ["count.positions", "exposure_metrics.portfolio_market_value",
                              "issuer_exposures.MSFT.weight"]
    assert p["truncated"] is False


def test_a_verbatim_quote_from_a_cited_chunk_passes_and_a_changed_one_is_refused():
    t = _table()
    ok = [{"type": "paragraph", "cites": ["chunk_1"],
           "runs": ["Management says it expects “capital expenditures to increase in fiscal” terms."]}]
    assert resolver.resolve_against(ok, t).ok
    changed = [{"type": "paragraph", "cites": ["chunk_1"],
                "runs": ["Management says it expects “capital expenditures to decrease in fiscal” terms."]}]
    v = resolver.resolve_against(changed, t)
    assert v.error == "unverified_quote"
    assert v.problems[0]["reason"] == "not_in_cited_passages"
    uncited = [{"type": "paragraph",
                "runs": ["Management says it expects “capital expenditures to increase in fiscal” terms."]}]
    assert resolver.resolve_against(uncited, t).error == "unverified_quote", (
        "the words exist on the table, but this block did not cite the passage")


def test_a_trend_on_a_non_series_ref_is_refused():
    v = resolver.resolve_against([{"type": "trend", "text": "rose", "series_ref": "calc_x"}], _table())
    assert v.error == "unsupported_assertion"
    assert v.problems == [{"at": "blocks[0]", "ref": "calc_x", "reason": "not_a_series", "kind": "scalar"}]


def test_an_action_on_a_non_task_ref_is_refused():
    v = resolver.resolve_against([{"type": "action", "text": "started", "task_ref": "calc_a"}], _table())
    assert v.error == "unsupported_assertion"
    assert v.problems == [{"at": "blocks[0]", "ref": "calc_a", "reason": "not_a_task", "kind": "absence"}]


async def test_a_collinear_coefficient_is_not_on_the_table_so_its_name_is_unknown(monkeypatch):
    """Projection, not verification: `not_alone` is decided when the table is
    built, and the resolver never sees the coefficient. Its name is then
    unknown like any other name that was never shown — and the sum the
    regression does determine is there under its own name."""
    async def fake_of_ref(db, ref):
        assert ref == "run_1"
        return qn.Resolved((
            _q(0.42, RATIO, "factor_attributions.market.beta", "run_1", "factor_attributions",
               not_alone="these factors are collinear"),
            _q(0.0031, RATIO, "factor_attributions.sum_of_contributions", "run_1", "factor_attributions"),
        ), frozenset(), "run")
    monkeypatch.setattr(qn, "of_ref", fake_of_ref)

    t = tb.Table()
    await tb._place(None, t, {"type": "run", "id": "run_1", "scope": ["factor_attributions"]})
    assert t.names("run_1") == ["factor_attributions.sum_of_contributions"]

    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["beta ", {"ref": "run_1", "name": "factor_attributions.market.beta"}]}], t)
    assert v.error == "unknown_name"
    assert v.problems[0]["available"] == ["factor_attributions.sum_of_contributions"]


# ── build: the second narrowing phase (V16) ───────────────────────────────────

async def test_when_no_run_scope_is_left_series_entries_drop_before_everything_dies(monkeypatch):
    """Found live: get_beta declares two ~250-point returns series beside three
    scalars; the series alone overflow the limit, and the old dead-end declared
    EVERYTHING empty — the beta itself died for the size of its inputs. Whole
    entries now come off, series first, and the drop is recorded on the payload
    so the model is told what is not on the table (the NameError in this path's
    first draft survived a full green suite — which is why this test exists)."""
    async def fake_of_ref(db, ref):
        if ref == "calc_fat":
            pts = tuple(_q(0.001 * i, RATIO, f"XOM.returns@2025-{i:02d}-01", "calc_fat")
                        for i in range(1, 60))
            return qn.Resolved(pts, frozenset(), qn.KIND_SERIES)
        return qn.Resolved((_q(-0.54, RATIO, "XOM.beta.SPY", ref),), frozenset(), qn.KIND_SCALAR)
    monkeypatch.setattr(qn, "of_ref", fake_of_ref)

    refs, payload = await tb.build(None, [{"type": "calc", "id": "calc_thin"},
                                          {"type": "calc", "id": "calc_fat"}], limit=600)
    assert [e["id"] for e in refs] == ["calc_thin"]
    assert payload["truncated"]["dropped"] == ["calc_fat"]
    assert "XOM.beta.SPY" in payload["quantities"]["calc_thin"]


async def test_a_single_entry_too_big_to_fit_is_still_declared_empty(monkeypatch):
    """The dead-end survives for the case it is true of: ONE entry that cannot
    fit alone has nothing to keep, and pretending otherwise would put a partial
    series on the table under a whole series' id."""
    async def fake_of_ref(db, ref):
        pts = tuple(_q(0.001 * i, RATIO, f"XOM.returns@2025-{i:02d}-01", "calc_fat")
                    for i in range(1, 60))
        return qn.Resolved(pts, frozenset(), qn.KIND_SERIES)
    monkeypatch.setattr(qn, "of_ref", fake_of_ref)
    refs, payload = await tb.build(None, [{"type": "calc", "id": "calc_fat"}], limit=400)
    assert refs == []
    assert "dropped" not in payload["truncated"]
