"""M10 registry — declaration onto the table, schema generation, redaction (offline).

V15-S2a. Evidence is DECLARED by a tool's registration, not harvested by a walker
that guesses whether a result was a retrieval. These tests pin the wrapper's side
of that: what `invoke` hands `table.build` for each class of tool and result,
and what it records as the step's evidence — with `table.build` stubbed, because
building a slice needs rows and the question here is what was declared.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import table as tbl
from exposure_workbench.tools import faces
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, READ, REFLECTION, Evidence, Tool, ToolRegistry,
)
from exposure_workbench.services.trace_service import redact_args


# ── the pure declaration ──────────────────────────────────────────────────────

def test_every_id_shaped_string_in_a_result_is_declared():
    out = tbl.declare({"calc_id": "calc_abc123", "value": 0.75,
                       "points": [{"fact_ids": ["fact_a", "fact_b"]}],
                       "passages": [{"chunk_id": "chunk_x"}],
                       "source": "src_99", "alert": "alert_c0nc"})
    kinds = {(e["type"], e["id"]) for e in out["evidence"]}
    assert kinds == {("calc", "calc_abc123"), ("fact", "fact_a"), ("fact", "fact_b"),
                     ("chunk", "chunk_x"), ("source", "src_99"), ("alert", "alert_c0nc")}


def test_a_key_named_like_an_id_does_not_make_its_value_one():
    out = tbl.declare({"calc_id": "not-an-id", "fact_id": "fact_abc123"})
    assert [e["id"] for e in out["evidence"]] == ["fact_abc123"]


def test_a_prefix_the_table_cannot_place_is_not_declared():
    """co_/rrun_/filing_ are minted and never citable; declaring them would hand
    the model an id it can retrieve, quote, and be refused for quoting."""
    out = tbl.declare({"company": "co_nvda", "run": "rrun_2", "filing": "filing_x"})
    assert out["evidence"] == []


def test_declaration_dedupes():
    out = tbl.declare({"a": {"calc_id": "calc_1"}, "b": {"calc_id": "calc_1"}})
    assert [e["id"] for e in out["evidence"]] == ["calc_1"]


def test_a_run_is_on_the_table_only_with_a_scope_or_names():
    """A run is not evidence for anything until a child of it has been read, so
    a bare run id — get_task_status echoing one, say — declares nothing."""
    assert tbl.declare({"run_id": "run_1"})["evidence"] == []
    scoped = tbl.declare({"run_id": "run_1"}, scope=("exposure_metrics", "count"))["evidence"]
    assert scoped == [{"type": "run", "id": "run_1", "scope": ["exposure_metrics", "count"]}]
    named = tbl.declare({"run_id": "run_1"}, scope=("exposure_metrics",),
                        names=["issuer_exposures.MSFT.weight"])["evidence"]
    assert named == [{"type": "run", "id": "run_1", "names": ["issuer_exposures.MSFT.weight"]}]


def test_delegated_work_is_declared_as_a_task_row():
    out = tbl.declare({"enqueued": True, "run_id": "rrun_2"}, tasks=["rrun_2"])
    assert out["evidence"] == [{"type": "task", "id": "rrun_2", "kind": tbl.KIND_TASK}]


# ── the wrapper: what it hands build(), what it records ───────────────────────

class _Db:
    async def rollback(self):
        pass


def _wire(monkeypatch, *, built=None):
    """Stub the three things invoke() reaches for besides the tool itself.

    Returns the log: `built` is every declaration handed to table.build,
    `recorded` every evidence_refs list handed to the trace.
    """
    log = {"built": [], "recorded": []}

    async def _build(db, declared, limit=tbl.TABLE_CHAR_LIMIT):
        log["built"].append(declared)
        return built if built is not None else (declared, {"quantities": {"stub": {}}})

    async def _record(db, session_id, **kw):
        log["recorded"].append(kw["evidence_refs"])

    async def _reserve(db, session_id, is_external_search=False):
        pass

    monkeypatch.setattr(R.tbl, "build", _build)
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


async def test_a_read_tool_registered_with_evidence_puts_its_ids_on_the_table(monkeypatch):
    log = _wire(monkeypatch)
    tool = Tool(name="get_flow", description="", json_schema={"type": "object"},
                fn=_returning({"calc_id": "calc_abc", "points": [{"fact_ids": ["fact_a"]}]}),
                tool_class=READ, evidence=Evidence())
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_flow", {})

    assert log["built"] == [[{"type": "calc", "id": "calc_abc"}, {"type": "fact", "id": "fact_a"}]]
    assert log["recorded"] == [[{"type": "calc", "id": "calc_abc"}, {"type": "fact", "id": "fact_a"}]]
    assert out["table"] == {"quantities": {"stub": {}}}, "the slice the model reads rides on the result"


async def test_a_tool_registered_without_a_declaration_puts_nothing_on_the_table(monkeypatch):
    """get_task_status reads state, list_risk_limits reads policy: their results
    hold ids and are not evidence. Nothing is built and nothing is recorded."""
    log = _wire(monkeypatch)
    tool = Tool(name="get_task_status", description="", json_schema={"type": "object"},
                fn=_returning({"job_id": "run_real", "state": "completed"}),
                tool_class=READ, evidence=None)
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_task_status", {})

    assert log["built"] == []
    assert log["recorded"] == [[]]
    assert "table" not in out


async def test_a_gates_refusal_echoing_ids_puts_nothing_on_the_table(monkeypatch):
    """The fabricated-id loop, closed by construction. respond's refusal echoes
    the ids it just refused under problems[].id, and the call itself COMPLETES —
    a walker over that payload wrote them into the trail, and on the retry they
    passed. A gate declares nothing, so there is nothing for the retry to find."""
    log = _wire(monkeypatch)
    refusal = {"error": "not_on_table",
               "problems": [{"id": "calc_fabricated", "reason": "not_on_table"},
                            {"id": "fact_nope", "reason": "not_on_table"}]}
    assert {e["id"] for e in tbl.declare(dict(refusal))["evidence"]} == {"calc_fabricated", "fact_nope"}, (
        "the ids are there to be found — which is why the decision is made above declare()")
    gate = Tool(name="respond", description="", json_schema={"type": "object"},
                fn=_returning(refusal), tool_class=GATE)
    out = await R.invoke(_registry(gate), _Db(), "sess_1", "respond", {})

    assert out["error"] == "not_on_table"
    assert log["built"] == []
    assert log["recorded"] == [[]]


async def test_a_reflection_echoing_an_id_declares_nothing(monkeypatch):
    """V3-R2: think hands the thought straight back, so a one-token thought that
    IS an id would have been harvested. A reflection is the model talking to
    itself and is registered without a declaration."""
    from exposure_workbench.tools.definitions import _think

    log = _wire(monkeypatch)
    echoed = await _think(None, thought="calc_deadbeefcafe")
    assert tbl.declare(dict(echoed))["evidence"], "the walker still finds it — hence the registration"
    assert build_read_registry().get("think").evidence is None

    think = Tool(name="think", description="", json_schema={"type": "object"},
                 fn=_think, tool_class=REFLECTION)
    await R.invoke(_registry(think), _Db(), "sess_1", "think", {"thought": "calc_deadbeefcafe"})
    assert log["built"] == [] and log["recorded"] == [[]]


async def test_a_refused_read_still_declares_the_absence_it_minted(monkeypatch):
    """The first red test of V15-S2a. get_flow refuses a series it cannot derive
    and mints an absence row for the refusal; the old harvester skipped any
    payload with an `error` key, so the one id an `absence` block needs was the
    one id that never reached the trail. A result with an error key AND an
    absence_id declares it like any other id the tool returned."""
    log = _wire(monkeypatch)
    tool = Tool(name="get_flow", description="", json_schema={"type": "object"},
                fn=_returning({"error": "series_not_derivable", "absence_id": "calc_absent1"}),
                tool_class=READ, evidence=Evidence())
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_flow", {})

    assert out["error"] == "series_not_derivable"
    assert log["built"] == [[{"type": "calc", "id": "calc_absent1"}]]
    assert log["recorded"] == [[{"type": "calc", "id": "calc_absent1"}]]


async def test_a_tool_that_raised_declares_nothing(monkeypatch):
    """An exception is not a retrieval: the wrapper's structured tool_error
    carries no ids and builds no table, whatever the tool's registration says."""
    log = _wire(monkeypatch)

    async def _boom(db, **args):
        raise RuntimeError("calc_should_not_matter")

    tool = Tool(name="get_flow", description="", json_schema={"type": "object"},
                fn=_boom, tool_class=READ, evidence=Evidence())
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_flow", {})

    assert out["error"] == "tool_error"
    assert log["built"] == [] and log["recorded"] == [[]]


async def test_a_delegation_declares_the_work_it_started_as_a_task(monkeypatch):
    log = _wire(monkeypatch)
    tool = Tool(name="start_issuer_research", description="", json_schema={"type": "object"},
                fn=_returning({"enqueued": True, "run_id": "rrun_2", "ticker": "NVDA"}),
                tool_class=DELEGATION, evidence=Evidence(tasks_from=("run_id",)))
    await R.invoke(_registry(tool), _Db(), "sess_1", "start_issuer_research", {})
    assert log["built"] == [[{"type": "task", "id": "rrun_2", "kind": tbl.KIND_TASK}]]


async def test_a_run_read_declares_its_scope_and_a_read_by_name_declares_its_names(monkeypatch):
    log = _wire(monkeypatch)
    scoped = Tool(name="get_risk_state", description="", json_schema={"type": "object"},
                  fn=_returning({"run_id": "run_1", "metrics": {}}), tool_class=READ,
                  evidence=Evidence(scope=("exposure_metrics", "count")))
    named = Tool(name="read_quantities", description="", json_schema={"type": "object"},
                 fn=_returning({"run_id": "run_1",
                                "names": {"run_1": {"issuer_exposures.MSFT.weight": 0.1}}}),
                 tool_class=READ, evidence=Evidence(names_from="names"))
    reg = ToolRegistry()
    reg.register(scoped)
    reg.register(named)
    await R.invoke(reg, _Db(), "sess_1", "get_risk_state", {})
    await R.invoke(reg, _Db(), "sess_1", "read_quantities", {})
    assert log["built"] == [
        [{"type": "run", "id": "run_1", "scope": ["exposure_metrics", "count"]}],
        [{"type": "run", "id": "run_1", "names": ["issuer_exposures.MSFT.weight"]}],
    ]


async def test_what_is_recorded_is_what_build_narrowed_to(monkeypatch):
    """Three outlets, one set: the declaration stored is the one build() returned
    after fitting the slice, not the one the tool declared — so the record and
    the payload cannot say different things about a run whose tail was cut."""
    narrowed = [{"type": "run", "id": "run_1", "scope": ["exposure_metrics"],
                 "truncated": ["count"]}]
    log = _wire(monkeypatch, built=(narrowed, {"quantities": {"run_1": {}}}))
    tool = Tool(name="get_risk_state", description="", json_schema={"type": "object"},
                fn=_returning({"run_id": "run_1"}), tool_class=READ,
                evidence=Evidence(scope=("exposure_metrics", "count")))
    await R.invoke(_registry(tool), _Db(), "sess_1", "get_risk_state", {})
    assert log["recorded"] == [narrowed]


async def test_a_table_that_cannot_be_built_is_a_result_with_nothing_citable(monkeypatch):
    log = _wire(monkeypatch)

    async def _broken(db, declared, limit=tbl.TABLE_CHAR_LIMIT):
        raise RuntimeError("db gone")

    monkeypatch.setattr(R.tbl, "build", _broken)
    tool = Tool(name="get_flow", description="", json_schema={"type": "object"},
                fn=_returning({"calc_id": "calc_abc"}), tool_class=READ, evidence=Evidence())
    out = await R.invoke(_registry(tool), _Db(), "sess_1", "get_flow", {})
    assert "table" not in out and log["recorded"] == [[]]


def test_every_read_tool_that_returns_evidence_says_so():
    """The registration is the only place a tool's results become citable, so
    the ones whose results ARE evidence must carry a declaration. The tools
    listed here are the deliberate exceptions: state and policy readers, and
    the reflection."""
    reg = build_read_registry()
    NOT_EVIDENCE = {"get_task_status", "list_risk_limits", "get_run_freshness", "think"}
    undeclared = sorted(n for n, t in reg.tools.items()
                        if t.evidence is None and n not in NOT_EVIDENCE)
    assert undeclared == [], f"read tools with no declaration: {undeclared}"


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
    """schema-as-interface: get_flow can't be called without ticker+metric."""
    reg = build_read_registry()
    gfs = reg.get("get_flow")
    assert set(gfs.json_schema["required"]) == {"ticker", "metric"}


def test_a_face_the_registry_cannot_satisfy_is_a_build_error():
    """Was test_face_available_filters_to_registered, and asserted the opposite.

    Filtering to what happened to be registered was the P5 mechanism; the read
    registry genuinely lacks the delegation/gate tools, and the old assertion
    read that as a smaller face rather than as the wrong registry for this face.
    """
    reg = build_read_registry()
    assert "get_flow" in faces.resolve(reg, faces.READ_CORE)

    with pytest.raises(faces.FaceNotRegistered) as exc:
        faces.resolve(reg, faces.FACE_META_AGENT)
    assert "start_issuer_research" in str(exc.value)   # tools/registries.build_meta_registry, P7


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
