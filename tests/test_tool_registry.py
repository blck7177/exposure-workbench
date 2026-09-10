"""M10 registry — the wrapper's side of the facts (V24), schema generation, redaction (offline).

What `invoke` hands the model and records on the step for each class of tool
and result: a read's figures as facts, a gate's verdict as nothing, a refusal's
absence as a fact, an adapter that cannot name a unit as the tool's own error.
The trace and the budget are stubbed; the adapters are real.
"""

from __future__ import annotations

import pytest

from exposure_workbench.tools import faces
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, READ, REFLECTION, Tool, ToolRegistry,
)
from exposure_workbench.services.trace_service import redact_args


# ── the pure declaration ──────────────────────────────────────────────────────

# ── the wrapper: what it hands build(), what it records ───────────────────────

class _Db:
    def __init__(self):
        self.added = []

    async def rollback(self):
        pass

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass


def _wire(monkeypatch):
    """Stub what invoke() reaches for besides the tool itself: the trace and the
    budget. Returns the log: `recorded` is every evidence_refs list handed to
    the trace (V24: a step's facts as `{facts: [...]}`), `step_ids` the ids."""
    log = {"recorded": []}

    async def _record(db, session_id, **kw):
        log["recorded"].append(kw["evidence_refs"])
        return "step_stub"

    async def _reserve(db, session_id, is_external_search=False, message_id=None):
        pass

    monkeypatch.setattr(R.trace_service, "record_step", _record)
    monkeypatch.setattr(R.sess, "reserve", _reserve)
    return log


def _registry(tool: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool)
    return reg


def _returning(payload):
    async def fn(db, **args):
        return dict(payload) if isinstance(payload, dict) else payload
    return fn


def _facts_recorded(log):
    from exposure_workbench.services import ledger as L
    return [L.facts_in(refs) for refs in log["recorded"]]


async def test_a_read_tools_figures_reach_the_model_as_facts_and_the_step_records_them(monkeypatch):
    """V24. The payload's figures become Facts; the model reads `facts` + `note`
    (the payload with each figure replaced by its fact id); the step records the
    same facts; the facts table gets one row each."""
    log = _wire(monkeypatch)
    payload = {"calc_id": "calc_abc", "ticker": "MSFT", "metric": "revenue", "value": 2.8e11, "unit_class": "MONEY",
               "period": {"start": "2025-04-01", "end": "2026-03-31"}, "terms": [{"fact_id": "fact_a", "sign": 1}],
               "derivation": "sum of quarters", "basis": "2025-04-01..2026-03-31"}
    tool = Tool(name="read_fundamentals", description="", json_schema={"type": "object"},
                fn=_returning(payload), tool_class=READ)
    db = _Db()
    out = await R.invoke(_registry(tool), db, "sess_1", "read_fundamentals", {"ticker": "MSFT", "metric": "revenue"})

    assert "table" not in out and "value" not in out, "the figure is not in the payload twice"
    rows = out["facts"]["rows"]
    assert len(rows) == 1 and rows[0][3] == "revenue" and rows[0][4] == "MONEY" and rows[0][6] == "2026-03-31"
    fid = rows[0][0]
    assert out["fact"] == fid, "the note points at the fact where the value stood"
    assert out["derivation"] == "sum of quarters"
    [(recorded,)] = _facts_recorded(log)
    assert recorded["id"] == fid and recorded["sources"] == ["calc_abc", "fact_a"]
    assert [r.id for r in db.added] == [fid] and db.added[0].step_id == "step_stub"


async def test_a_tool_with_no_adapter_passes_its_payload_through_and_records_nothing(monkeypatch):
    log = _wire(monkeypatch)
    tool = Tool(name="get_task_status", description="", json_schema={"type": "object"},
                fn=_returning({"job_id": "run_real", "state": "completed"}),
                tool_class=READ)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_task_status", {})
    assert out == {"job_id": "run_real", "state": "completed"}
    assert log["recorded"] == [[]]


async def test_a_gates_refusal_echoing_ids_records_nothing(monkeypatch):
    """The fabricated-id loop, closed by construction: a gate's verdict is not a
    tool result with facts in it, so the ids a refusal echoes are never on the
    ledger for the retry to point at."""
    log = _wire(monkeypatch)
    refusal = {"error": "not_on_ledger",
               "problems": [{"id": "f_fabricated", "reason": "not_on_ledger"}]}
    gate = Tool(name="respond", description="", json_schema={"type": "object"},
                fn=_returning(refusal), tool_class=GATE)
    out = await R.invoke(_registry(gate), _Db(), "sess_1", "respond", {})
    assert out["error"] == "not_on_ledger" and out["problems"][0]["id"] == "f_fabricated"
    assert log["recorded"] == [[]]


async def test_a_reflection_echoing_an_id_records_nothing(monkeypatch):
    from exposure_workbench.tools.definitions import _think
    log = _wire(monkeypatch)
    think = Tool(name="think", description="", json_schema={"type": "object"},
                 fn=_think, tool_class=REFLECTION)
    out = await R.invoke(_registry(think), _Db(), "sess_1", "think", {"thought": "calc_deadbeefcafe"})
    assert out["noted"] is True and log["recorded"] == [[]]


async def test_a_refused_read_still_records_the_absence_it_minted(monkeypatch):
    """A refusal that minted an absence row is a FACT of kind absence — the one
    thing an honest sentence about a missing figure can point at."""
    log = _wire(monkeypatch)
    tool = Tool(name="read_fundamentals", description="", json_schema={"type": "object"},
                fn=_returning({"error": "window_not_derivable", "absence_id": "calc_absent1", "ticker": "MSFT",
                               "metric": "revenue", "statement": "No 12-month window of MSFT's revenue can be derived."}),
                tool_class=READ)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "read_fundamentals", {"ticker": "MSFT", "metric": "revenue"})
    assert out["error"] == "window_not_derivable"
    rows = out["facts"]["rows"]
    assert len(rows) == 1 and rows[0][1] == "absence" and rows[0][3] == "revenue"
    assert out["fact"] == rows[0][0] and "statement" not in out
    [(rec,)] = _facts_recorded(log)
    assert rec["kind"] == "absence" and rec["sources"] == ["calc_absent1"]


async def test_a_tool_that_raised_records_nothing(monkeypatch):
    log = _wire(monkeypatch)

    async def _boom(db, **args):
        raise RuntimeError("calc_should_not_matter")

    tool = Tool(name="read_fundamentals", description="", json_schema={"type": "object"},
                fn=_boom, tool_class=READ)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "read_fundamentals", {"ticker": "MSFT"})
    assert out["error"] == "tool_error" and "facts" not in out
    assert log["recorded"] == [[]]


async def test_a_delegation_records_the_work_it_started_as_a_task_fact(monkeypatch):
    log = _wire(monkeypatch)
    tool = Tool(name="start", description="", json_schema={"type": "object"},
                fn=_returning({"enqueued": True, "run_id": "rrun_2", "kind": "issuer_research", "ticker": "NVDA"}),
                tool_class=DELEGATION)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "start", {"kind": "research", "subject": "NVDA"})
    rows = out["facts"]["rows"]
    assert len(rows) == 1 and rows[0][1] == "task" and rows[0][2] == "rrun_2"
    [(rec,)] = _facts_recorded(log)
    assert rec["kind"] == "task" and rec["text"] == "enqueued"


async def test_an_adapter_that_cannot_name_a_unit_is_the_tools_own_structured_failure(monkeypatch):
    """I3, at run time: a numeric key with no declared unit is never shown as a
    bare number. The tool answers with a structured error naming the key, and
    nothing is recorded — loud, not a guess."""
    log = _wire(monkeypatch)
    tool = Tool(name="read_prices", description="", json_schema={"type": "object"},
                fn=_returning({"ticker": "MSFT", "as_of": "2026-09-03", "frobnication": 3.2,
                               "close": {"value": 417.2, "unit_class": "MONEY"}}),
                tool_class=READ)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "read_prices", {"ticker": "MSFT"})
    assert "error" not in out, "V31 §4.3: one key the adapter cannot name no longer costs the call"
    assert out["frobnication"] == "untyped:frobnication"
    assert "frobnication" in out["untyped"], "and the model is told which number it cannot point at"
    assert [f["value"] for f in log["recorded"][0][0]["facts"]] == [417.2], "the figure that typed was recorded"


async def test_a_result_over_the_cap_says_what_was_held_back_and_how_to_read_it(monkeypatch):
    from exposure_workbench.services import facts as F
    log = _wire(monkeypatch)
    payload = {"run_id": "run_1", "as_of": "2026-09-03",
               "figures": {f"issuer_exposures.T{i:03d}.weight": {"value": i / 1000, "unit_class": "RATIO"} for i in range(F.FACTS_PER_RESULT + 40)}}
    tool = Tool(name="read_book", description="", json_schema={"type": "object"},
                fn=_returning(payload), tool_class=READ)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "read_book", {"ref": "run_1", "names": ["x"]})
    shown = len(out["facts"]["rows"])
    total = F.FACTS_PER_RESULT + 40
    assert 0 < shown <= F.FACTS_PER_RESULT < total, "whole facts came off the tail until the result fit"
    assert out["held_back"]["count"] == total - shown and "read_book(" in out["held_back"]["how"]
    assert sum(1 for v in out["figures"].values() if v == "held_back") == total - shown
    [(recorded)] = _facts_recorded(log)
    assert len(recorded) == shown, "what is recorded is what was shown"


def test_every_tool_on_a_face_has_a_fact_adapter():
    """V24: a tool's figures reach the model only through its adapter, so a
    read or delegation tool with none would show bare numbers. Pinned on the
    real faces; the reflection and the two gates are the deliberate no-fact
    adapters."""
    from exposure_workbench.services import fact_adapters as fa
    from exposure_workbench.tools.registries import build_meta_registry, build_research_registry
    for reg in (build_meta_registry(), build_research_registry()):
        missing = sorted(n for n in reg.tools if n not in fa.ADAPTERS)
        assert missing == [], f"tools with no fact adapter: {missing}"
    assert fa.ADAPTERS["think"] is fa.no_facts and fa.ADAPTERS["respond"] is fa.no_facts


# ── schemas, faces, redaction ─────────────────────────────────────────────────

def test_schemas_are_valid_function_defs():
    reg = build_read_registry()
    schemas = reg.schemas()
    assert len(schemas) == len(reg.tools)
    for s in schemas:
        assert s["type"] == "function"
        assert s["function"]["name"] in reg.tools
        assert "parameters" in s["function"]


def test_required_judgment_fields_are_in_schema():
    """schema-as-interface: read_fundamentals can't be called without a ticker."""
    reg = build_read_registry()
    gfs = reg.get("read_fundamentals")
    assert set(gfs.json_schema["required"]) == {"ticker"}


def test_a_face_the_registry_cannot_satisfy_is_a_build_error():
    """Was test_face_available_filters_to_registered, and asserted the opposite.

    Filtering to what happened to be registered was the P5 mechanism; the read
    registry genuinely lacks the delegation/gate tools, and the old assertion
    read that as a smaller face rather than as the wrong registry for this face.
    """
    reg = build_read_registry()
    assert "read_fundamentals" in faces.resolve(reg, faces.READ_CORE)

    with pytest.raises(faces.FaceNotRegistered) as exc:
        faces.resolve(reg, faces.FACE_META_AGENT)
    assert "start" in str(exc.value)   # tools/registries.build_meta_registry


def test_redact_args_masks_key_class_fields_only():
    red = redact_args({"ticker": "NVDA", "api_key": "sk-secret", "edgar_identity": "x", "metric": "revenue"})
    assert red["ticker"] == "NVDA" and red["metric"] == "revenue"
    assert red["api_key"] == "[REDACTED]"
    assert red["edgar_identity"] == "[REDACTED]"


def test_only_the_classes_that_retrieve_nothing_are_free_of_budget():
    """V7-Q2. The budget bounds how much EVIDENCE a turn gathers, so the classes
    exempt from it are exactly the ones that gather none.

    GATE belongs here for a reason stronger than symmetry with REFLECTION: it is
    the only way a turn ENDS. Charged against a counter that can run out, it
    produced a turn that could not finish — respond refused for lacking budget it
    needed in order to spend nothing, then every remaining round trip burned at
    ~12k prompt tokens on a state with no possible outcome. Exempting it costs
    nothing, because after a gate runs there is nothing left for the turn to do.

    The other half is what must not regress: READ and DELEGATION are the calls
    the budget exists to bound, and a tuple that quietly grew to include them
    would turn the whole limit off with every test still green."""
    from exposure_workbench.tools.registry import BUDGET_FREE_CLASSES

    assert set(BUDGET_FREE_CLASSES) == {REFLECTION, GATE}
    assert READ not in BUDGET_FREE_CLASSES and DELEGATION not in BUDGET_FREE_CLASSES


def test_both_faces_reach_their_exit_through_the_gate_class():
    """The exemption is derived from the class, so an exit that is not declared
    one is an exit that can be refused into a turn with no way out. Asserted for
    both faces because research's exit is on the session budget, not the turn's,
    and 25-32 tool calls against a limit of 40 is not a wide margin."""
    from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

    for build, exit_name in ((build_meta_registry, "respond"), (build_research_registry, "submit_brief")):
        reg = build()
        assert reg.get(exit_name).tool_class == GATE, f"{exit_name} is not declared a gate"
        gates = {n for n, t in reg.tools.items() if t.tool_class == GATE}
        assert gates == {exit_name}, f"more than one exit on this face: {sorted(gates)}"
