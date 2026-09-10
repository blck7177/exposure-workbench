"""V28 — giving the work back to its role (offline).

Each test pins a boundary from IMPLEMENTATION_PLAN_V28: the tool executes the
intent it accepted (A1), an unwritable shape costs nothing (A2), comparability
is the identity's not the label's (B1), a run has one door (C1), a producer
declares its counts (C2), and the model is told validation's own rule (D1).
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

import pytest

from exposure_workbench.analytics.units import COUNT, MONEY, RATIO
from exposure_workbench.services import compute_service as cmp
from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.analytics import skill
from exposure_workbench.services import gate, series_service
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.faces import FACE_META_AGENT as FACE_META, FACE_RESEARCH
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

SRC = Path(__file__).parent.parent / "src" / "exposure_workbench"


# ── A1: a series statistic runs over the resolved series, whatever id the model wrote ──

def _q(v, sid, quantity="revenue", unit=MONEY, issuer="MSFT", **kw):
    return tc.Typed(value=v, unit_class=unit, quantity=quantity, source_id=sid, issuers=(issuer,), **kw)


async def test_a_statistic_over_a_series_fact_id_is_computed_not_refused(monkeypatch):
    series = tc.TypedSeries(points=((date(2024, 12, 31), _q(10.0, "f_p1")), (date(2025, 12, 31), _q(14.0, "f_p2"))),
                            unit_class=MONEY, kind="flow", quantity="revenue", source_id="f_series")
    recorded = {}

    async def resolve(_db, ref):
        assert ref == "f_series"
        return series

    async def record(_db, _c, operation, params, result, inputs, flags, invoked_by):
        recorded.update(operation=operation, params=params, result=result, inputs=inputs)
        return "calc_new"
    monkeypatch.setattr(tc, "_resolve", resolve)
    monkeypatch.setattr(series_service.cs, "_record", record)
    out = await cmp._stat(None, "max", ["f_series"], None, "agent")
    assert out["calc_id"] == "calc_new" and out["value"] == 14.0 and out["unit_class"] == MONEY
    assert recorded["inputs"] == ["f_series"]
    out = await cmp._stat(None, "yoy", ["f_series"], None, "agent")
    assert out["calc_id"] == "calc_new" and out["points"][-1]["value"] == pytest.approx(0.4)


def test_compute_never_hands_a_series_op_an_id_to_reload():
    src = inspect.getsource(cmp)
    assert "series_service.series_stat(" not in src
    assert "series_service.stat_over(" in src


# ── A2: two shapes of one call are unwritable together, before any spend ──

async def test_op_and_method_together_are_refused_before_any_spend(monkeypatch):
    """The refusal happens in the registry, before budget — and the tool DECLARES
    its two shapes rather than encoding them as a schema `not`, which the
    provider rejects outright (see the provider-legality test below)."""
    reg = build_meta_registry()
    assert reg.tools["compute"].shapes.fields == ("op", "method")
    assert reg.tools["read_filings"].shapes.fields == ("query", "item")

    spent = []
    from exposure_workbench.services import agent_session_service as sess
    from exposure_workbench.tools import registry as R

    async def reserve(*a, **k):
        spent.append(1)
    monkeypatch.setattr(sess, "reserve", reserve)

    async def record_step(*a, **k):
        return None
    monkeypatch.setattr(R.trace_service, "record_step", record_step)

    out = await R.invoke(reg, None, "sess_x", "compute",
                         {"op": "avg", "method": "price.beta", "subject": ["MSFT", "AAPL"]})
    assert out["error"] == "invalid_arguments" and not spent
    assert "two shapes" in out["problems"][0]["problem"] and "two calls" in out["problems"][0]["problem"]
    assert {p["field"] for p in out["problems"]} == {"op", "method"}

    out = await R.invoke(reg, None, "sess_x", "read_filings",
                         {"ticker": "MSFT", "query": "risk", "item": "1A"})
    assert out["error"] == "invalid_arguments" and "not both" in out["problems"][0]["problem"] and not spent

    # One shape, or the other, passes validation untouched.
    compute = reg.tools["compute"].json_schema
    assert validate_args(compute, {"op": "avg", "method": None, "operands": ["f_a", "f_b"]}) == []
    assert validate_args(compute, {"method": "price.beta", "subject": "MSFT", "op": None}) == []
    filings = reg.tools["read_filings"].json_schema
    assert validate_args(filings, {"ticker": "MSFT", "item": "1A", "query": None}) == []


# The provider's own words, 2026-09-08: "schema must have type 'object' and not
# have 'oneOf'/'anyOf'/'allOf'/'enum'/'const'/'not' at the top level". A V28
# schema carried a top-level `not`; jsonschema accepted it, 2,191 offline tests
# passed, and every LLM call in the battery returned 400 — the whole desk was
# down until this was found. The schema is part of the contract with the model,
# so a constraint the provider will not accept is not a constraint.
_FORBIDDEN_AT_TOP = ("oneOf", "anyOf", "allOf", "enum", "const", "not")


@pytest.mark.parametrize("name", sorted(set(FACE_META + FACE_RESEARCH)))
def test_every_schema_is_one_the_provider_accepts(name):
    for reg, face in ((build_meta_registry(), FACE_META), (build_research_registry(), FACE_RESEARCH)):
        if name not in face:
            continue
        schema = reg.tools[name].json_schema
        assert schema.get("type") == "object", f"{name}: parameters must be an object"
        present = [k for k in _FORBIDDEN_AT_TOP if k in schema]
        assert present == [], f"{name}: {present} at the top level; the provider rejects the function"


# ── B1: what is comparable is the identity's, and the row is named by what varies ──

class _Desk:
    def __init__(self, monkeypatch, operands):
        async def resolve(_db, ref):
            return operands[ref]

        async def record(_db, _c, operation, params, result, inputs, flags, invoked_by):
            self.recorded = {"operation": operation, "params": params, "result": result}
            return "calc_rank"
        monkeypatch.setattr(tc, "_resolve", resolve)
        monkeypatch.setattr(tc.cs, "_record", record)

    async def rank(self, refs, **kw):
        return await tc.rank(None, refs, **kw)

    async def aggregate(self, op, refs, **kw):
        return await tc.aggregate(None, op, refs, **kw)


_YEAR = (date(2025, 1, 1), date(2025, 12, 31))


async def test_several_measures_of_one_holder_over_one_window_are_ordered_by_measure(monkeypatch):
    desk = _Desk(monkeypatch, {
        "capex": _q(30.0, "f_capex", "capex", interval=_YEAR),
        "buybacks": _q(45.0, "f_bb", "buybacks", interval=_YEAR),
        "dividends": _q(20.0, "f_div", "dividends_paid", interval=_YEAR),
    })
    out = await desk.rank(["capex", "buybacks", "dividends"], direction="highest")
    assert out["leader"] == "buybacks"
    assert [e["label"] for e in out["ordering"]] == ["buybacks", "capex", "dividends_paid"]
    assert out["type"]["axis"] == "quantity" and out["quantity"] == "MSFT.rank"
    out = await desk.aggregate("max", ["capex", "buybacks", "dividends"])
    assert out["value"] == 45.0


async def test_one_measure_across_holders_still_keeps_each_ones_own_window(monkeypatch):
    desk = _Desk(monkeypatch, {
        "m": _q(0.4, "f_m", "gross_margin", RATIO, "MSFT", interval=(date(2025, 7, 1), date(2026, 6, 30))),
        "a": _q(0.45, "f_a", "gross_margin", RATIO, "AAPL", interval=(date(2024, 9, 29), date(2025, 9, 27))),
    })
    out = await desk.rank(["m", "a"], direction="highest")
    assert out["leader"] == "AAPL" and out["type"]["axis"] == "issuer" and out["quantity"] == "gross_margin"


async def test_several_measures_over_different_windows_or_holders_are_refused(monkeypatch):
    desk = _Desk(monkeypatch, {
        "capex": _q(30.0, "f_capex", "capex", interval=_YEAR),
        "bb_prior": _q(45.0, "f_bb", "buybacks", interval=(date(2024, 1, 1), date(2024, 12, 31))),
        "aapl_bb": _q(50.0, "f_ab", "buybacks", issuer="AAPL", interval=_YEAR),
    })
    out = await desk.rank(["capex", "bb_prior"], direction="highest")
    assert out["error"] == "incomparable_quantities" and "window" in out["detail"]
    out = await desk.rank(["capex", "aapl_bb"], direction="highest")
    assert out["error"] == "incomparable_quantities"


# ── C1: a run has one door, and every reader uses it ──

_RUN_LOADER_ALLOWLIST = {
    "services/run_reads_service.py": "the loader itself",
    "services/exposure_run_service.py": "the writer: it creates and advances runs",
    "services/job_status_service.py": "the task door: it reports a run's status, which is the point",
    "services/evidence_resolver_service.py": "the drawer: renders evidence the gate already accepted from completed runs",
}


def _loads_run_by_id(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "where"):
            continue
        sel = node.func.value
        if not (isinstance(sel, ast.Call) and isinstance(sel.func, ast.Name) and sel.func.id == "select"
                and sel.args and isinstance(sel.args[0], ast.Name) and sel.args[0].id == "ExposureRun"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Compare) and isinstance(arg.left, ast.Attribute) and arg.left.attr == "id" \
                    and isinstance(arg.left.value, ast.Name) and arg.left.value.id == "ExposureRun":
                return True
    return False


def test_every_reader_of_a_run_goes_through_the_one_door():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC))
        if rel in _RUN_LOADER_ALLOWLIST:
            continue
        if _loads_run_by_id(ast.parse(path.read_text())):
            offenders.append(rel)
    assert offenders == [], f"load a run through run_reads_service.completed_run, not by id: {offenders}"


async def test_an_incomplete_run_is_task_state_not_figures(monkeypatch):
    from exposure_workbench.services import run_reads_service as rr

    class Run:
        id = "run_x"; status = "running"; task_id = "task_9"; portfolio_id = "port_001"

    async def loaded(_db, _rid):
        return Run()
    monkeypatch.setattr(rr, "_run_or_error", loaded)
    out = await rr.completed_run(None, "run_x")
    assert out["error"] == "run_not_completed" and out["status"] == "running"
    assert out["read"] == "read_book('task_9', names=['state'])"


# ── C2: a producer declares the unit of its counts; the adapter mints them ──

def test_a_container_that_declares_its_numeric_unit_is_minted_not_crashed():
    payload = {"subject": "MSFT", "kind": "issuer", "catalogue_as_of": "2026-09-08",
               "filings": {"items_detail": {"numeric_unit": "count", "Item 1A": 3, "Item 7": 2}}}
    facts, note = fa.describe({"subject": "MSFT", "expand": "filings"}, payload)
    minted = {f.measure.rsplit(".", 1)[-1]: f for f in facts}
    assert minted["Item 1A"].unit == COUNT.upper() and minted["Item 1A"].value == 3.0
    assert minted["Item 1A"].measure == "filings.items_detail.Item 1A"
    assert note["filings"]["items_detail"]["Item 7"] == minted["Item 7"].id
    # Undeclared is still never guessed — but since V31 §4.3 it costs the leaf,
    # not the call: no fact, no number, and the key named in the note.
    bare, note2 = fa.describe({"subject": "MSFT"}, {"subject": "MSFT", "kind": "issuer",
                                                    "catalogue_as_of": "2026-09-08",
                                                    "filings": {"items_detail": {"Item 1A": 3}}})
    assert bare == [] and note2["filings"]["items_detail"]["Item 1A"] == "untyped:Item 1A"


def test_a_methods_declared_unit_is_what_its_leaves_carry():
    """V28 C2, second instance: `book.explain_episode` returns
    `portfolio_window_return`, a name no key list declared. The METHOD declares
    its unit (skill.Method.unit_class) and the adapter reads it, so a method
    whose payload the adapter has never seen cannot die on an undeclared leaf.
    A specific key still wins: a ratio method that also counts sessions."""
    payload = {"method": "book.explain_episode", "subject": "port_001", "portfolio_id": "port_001",
               "window": {"from": "2026-01-08", "to": "2026-03-27"}, "sessions": 55,
               "portfolio_window_return": -0.1195, "calc_id": "calc_x",
               "holdings": [{"ticker": "MSFT", "window_return": -0.26, "calc_id": "calc_m"}]}
    facts, note = fa.compute({"method": "book.explain_episode"}, payload)
    by = {f.measure.rsplit(".", 1)[-1]: f for f in facts}
    assert by["portfolio_window_return"].unit == RATIO.upper()
    assert by["window_return"].unit == RATIO.upper() and by["window_return"].subject == "MSFT"
    assert by["sessions"].unit == COUNT.upper(), "a declared key beats the method's default"
    # A method with no declared unit still does not TYPE an undeclared leaf: the
    # rule is a declaration, not a fallback. Since V31 §4.3 the leaf is marked
    # rather than the call discarded.
    none, n = fa.compute({"method": "nonesuch"}, {"method": "nonesuch", "subject": "MSFT", "whatsit": 3})
    assert none == [] and n["whatsit"] == "untyped:whatsit"


def test_a_key_whose_unit_depends_on_what_was_computed_reads_the_declaration():
    """V29. `rank`'s spread is max − min OF THE RANKED MEASURE, so its unit is
    MONEY when market values are ranked. A key list said RATIO, and a
    $1,135,470 spread reached the reader as "113547000.0%". The unit of such a
    key is not a property of its name: the producer declares it in
    `type.unit_class` and the adapter reads that."""
    money = {"op": "rank", "calc_id": "calc_x", "as_of": "2026-09-04", "spread": 1135470.0,
             "type": {"unit_class": "money", "kind": "ranking", "quantity": "market_value"}}
    facts, _ = fa.compute({"op": "rank"}, money)
    assert next(f for f in facts if f.measure == "spread").unit == MONEY.upper()

    ratio = {**money, "spread": 0.117, "type": {**money["type"], "unit_class": "ratio"}}
    facts, _ = fa.compute({"op": "rank"}, ratio)
    assert next(f for f in facts if f.measure == "spread").unit == RATIO.upper()

    # No declaration is still not a default — the guess is what put
    # "113547000.0%" in front of a reader. V31 §4.3: the undeclared leaf is
    # marked and unciteable instead of taking the whole result with it.
    facts, note = fa.compute({"op": "rank"}, {"op": "rank", "calc_id": "calc_x", "as_of": "2026-09-04",
                                              "spread": 1135470.0})
    assert note["spread"] == "untyped:spread" and facts == []
    assert fa.numeric_leaves(note) == [], "no bare number reaches the reader either way"
    assert "spread" not in fa.UNIT_BY_KEY and "spread" in fa.POLYMORPHIC_KEYS


@pytest.mark.live
async def test_every_registry_method_survives_its_own_adapter():
    """The class this batch found twice (X3 filings, explain_episode): a payload
    the adapter has never seen. Call every method once and adapt the result —
    a method nobody has asked for is exactly where an undeclared leaf hides."""
    import os

    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from exposure_workbench.services import compute_service as cmp_service
    load_dotenv(".env", override=True)
    url = os.getenv("DATABASE_URL_RLS", "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
    subj = {"issuer": "MSFT", "price": "MSFT", "run": None, "portfolio": "port_001"}
    params = {"book.explain_episode": {"peak": "2026-01-07", "trough": "2026-03-27"},
              "book.sell": {"sales": [{"ticker": "MSFT", "fraction": 0.5}]},
              "book.buy": {"buys": [{"ticker": "KO", "weight": 0.05}]}}
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    crashed = []
    try:
        async with mk() as db:
            from exposure_workbench.services import run_reads_service as rr
            fresh = await rr.get_run_freshness(db, "port_001")
            subj["run"] = fresh["latest_completed_run"]
            for name, m in skill.METHODS.items():
                out = await cmp_service.compute(db, method=name, subject=subj[m.subject_kind],
                                                params=params.get(name, {}))
                try:
                    fa.adapt("compute", {"method": name}, out)
                except Exception as e:                    # UnknownUnit, or any adapter fault
                    crashed.append((name, f"{type(e).__name__}: {e}"))

            # The SHAPES a compute result comes in, not only the methods: a list
            # of methods, a refused list, and every op. Each of the three adapter
            # crashes this batch found lived in a shape nobody had exercised —
            # expand='filings', explain_episode, and `entries` from a set
            # statistic V25 measured at zero uses.
            two = ["price.volatility", "price.drawdown"]
            shapes = [({"method": two, "subject": "MSFT"}, {}),
                      ({"method": two, "subject": "MSFT"}, {"window": "3m"}),    # refused: mixed params
                      ({"method": ["book.drawdown_episodes", "book.reconcile"], "subject": "port_001"}, {})]
            for call, params in shapes:
                out = await cmp_service.compute(db, params=params, **call)
                try:
                    fa.adapt("compute", dict(call, params=params), out)
                except Exception as e:
                    crashed.append((str(call.get("method")), f"{type(e).__name__}: {e}"))

            one = await cmp_service.compute(db, method="price.distance_from_52w_high", subject="HYG")
            two_ = await cmp_service.compute(db, method="price.volatility", subject="HYG", params={"window_days": 30})
            a, b = one.get("calc_id"), two_.get("calc_id")
            ops = [("abs", [a]), ("add", [a, b]), ("subtract", [a, b]), ("multiply", [a, b]),
                   ("divide", [a, b]), ("scale", [a]), ("rank", [a, b]), ("avg", [a, b]),
                   ("min", [a, b]), ("max", [a, b]), ("std", [a, b]), ("sum", [a, b])]
            for op, operands in ops:
                kw = {"params": {"factor": 2}} if op == "scale" else ({"direction": "highest"} if op == "rank" else {})
                out = await cmp_service.compute(db, op=op, operands=operands, **kw)
                try:
                    fa.adapt("compute", {"op": op, "operands": operands}, out)
                except Exception as e:
                    crashed.append((f"op:{op}", f"{type(e).__name__}: {e}"))
    finally:
        await engine.dispose()
    assert crashed == [], crashed


# ── D1: the model is told validation's own sentence ──

def test_the_prose_rule_is_one_sentence_given_verbatim_to_the_model():
    from exposure_workbench.agents import meta_agent
    from exposure_workbench.tools import mcp_server
    # V30: the chat exit's rule is services/claims.PROSE_RULE (digits allowed when
    # the ledger accounts for them); gate.PROSE_RULE stays the brief path's until D5.
    from exposure_workbench.services import claims
    assert claims.PROSE_RULE in meta_agent._SYSTEM
    assert claims.PROSE_RULE in mcp_server.INSTRUCTIONS
    assert claims.PROSE_RULE in build_meta_registry().tools["respond"].description
    assert gate._FIX.startswith(gate.PROSE_RULE)
    assert "never write a number" not in meta_agent._SYSTEM


@pytest.mark.live
async def test_the_provider_accepts_every_face_as_written():
    """The structural test above encodes the provider's rule; this one asks the
    provider. Cheap (16 output tokens) and the only check that cannot go stale
    if the rule changes."""
    import os

    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    load_dotenv(".env", override=True)
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for reg, face in ((build_meta_registry(), FACE_META), (build_research_registry(), FACE_RESEARCH)):
        await client.chat.completions.create(
            model=os.environ["OPENAI_MODEL"], max_completion_tokens=16,
            messages=[{"role": "user", "content": "say ok"}], tools=reg.schemas(face))


@pytest.mark.live
async def test_every_method_the_desk_can_run_survives_its_own_adapter():
    """X3's class, closed by audit rather than by fixture.

    `describe(expand='filings')` was dead on every issuer for two versions
    because no fixture covered that payload shape. On 2026-09-08 the same class
    reappeared the moment V27 routed a live turn to `book.explain_episode` —
    a method called ZERO times in the 244-turn battery, whose payload had
    therefore never met the adapter. A fixture per shape cannot cover what
    nobody has called; this asks every method the desk can run.
    """
    import os

    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from exposure_workbench.analytics import skill
    from exposure_workbench.services import compute_service as cmp
    load_dotenv(".env", override=True)
    url = os.getenv("DATABASE_URL_RLS", "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    subjects = {"issuer": "MSFT", "price": "MSFT", "run": "run_72e6617afeb7", "portfolio": "port_001"}
    params = {"book.explain_episode": {"peak": "2026-01-07", "trough": "2026-03-27"},
              "book.sell": {"sales": [{"ticker": "MSFT", "fraction": 0.25}]},
              "book.buy": {"buys": [{"ticker": "KO", "weight": 0.03}]}}
    crashes, adapted = [], 0
    try:
        async with mk() as db:
            for name, m in skill.METHODS.items():
                subject = subjects.get(m.subject_kind)
                if subject is None:
                    continue
                out = await cmp.compute(db, method=name, subject=subject, params=params.get(name, {}))
                if out.get("error"):
                    continue                      # a data-cover refusal is not an adapter defect
                try:
                    fa.adapt("compute", {"method": name, "subject": subject}, out)
                    adapted += 1
                except Exception as exc:          # noqa: BLE001 — the point is to name it
                    crashes.append(f"{name}: {type(exc).__name__}: {exc}")
    finally:
        await engine.dispose()
    assert crashes == [], crashes
    assert adapted >= 30, f"only {adapted} methods resolved; the audit proves nothing on an empty desk"
