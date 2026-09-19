"""V1, after steps 2–5: what the first read of a REAL database found (2026-09-19).

The offline suite was green over fixtures shaped like the services' payloads; the
smoke ran every verb of every face against a clone of the battery database and
read the rows a model would read. Each test here is one thing that read wrong:
a row that named nothing, a figure at a date it was never reported for, a beta
written as a percentage, a refusal that named a door nobody has. Offline, like
tests/test_v1_primitives.py: services are replaced by the payloads they returned.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from exposure_workbench.analytics import registry as desk
from exposure_workbench.analytics import resources as rs
from exposure_workbench.services import compute_service
from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.services import facts as F
from exposure_workbench.tools import primitives as P

WHY = "line 1 asks where the book is concentrated"


# ── a balance sheet's missing lines are absences, not figures at a wrong date ─

_SHEET = {"ticker": "MSFT", "as_of": "2026-03-31",
          "balances": {"inventory": {"value": 1.219e9, "fact_id": "fact_0e2914c9eae9", "as_of": "2026-03-31", "unit_class": "MONEY"}},
          "not_reported_at_this_date": {"commercial_paper": {"last_reported": "2025-06-30", "value_then": 0.0,
                                                             "unit_class": "MONEY", "note": "reported at another date"}},
          "basis": "balance sheet as of 2026-03-31; one instant, no substitution"}


def test_a_line_the_sheet_does_not_carry_is_an_absence_with_the_date_it_has():
    facts, _ = fa.read_fundamentals({"ticker": "MSFT"}, _SHEET)
    figures = [f for f in facts if f.kind == F.SCALAR]
    assert [f.measure for f in figures] == ["inventory"]                  # and nothing called "… value then"
    gone = [f for f in facts if f.kind == F.ABSENCE]
    assert len(gone) == 1 and gone[0].measure == "commercial_paper"
    assert gone[0].means["reason"] == "not_held" and "at=2025-06-30" in gone[0].means["way_out"]
    assert "as of 2026-03-31" in gone[0].text and "2025-06-30" in gone[0].text


# ── a list's head counts what the reader is given ────────────────────────────

def test_a_lists_head_counts_its_names():
    out = fa.present("list", {"what": "fundamentals", "subject": "MSFT", "why": WHY}, [],
                     {"catalogue": ["revenue — …", "net_income — …", "inventory — …"]}, None, "r_1")
    assert out["head"].endswith("→ 3 names") and out["rows"] == []
    none = fa.present("metric", {"name": "roic", "subject": "MSFT", "why": WHY}, [], {}, None, "r_2")
    assert none["head"].endswith("→ 0 rows")


# ── a book is named one way on every verb ────────────────────────────────────

async def test_a_measure_over_a_run_takes_the_books_own_id(monkeypatch):
    asked = {}

    async def _resolve(db, book, which):
        return ("run_latest", "2026-09-10") if book == "port_001" else {"error": "no_completed_run", "detail": f"{book} has no completed run"}

    async def _compute(db, **kw):
        asked.update(kw)
        return {"method": kw["method"], "subject": kw["subject"]}
    monkeypatch.setattr(P, "_resolve_book", _resolve)
    monkeypatch.setattr(P.compute_service, "compute", _compute)
    metric = P.build_analyst_registry("risk").get("metric").fn

    await metric(None, name="book.analysis", subject="port_001", why=WHY)
    assert asked["subject"] == "run_latest"
    refused = await metric(None, name="book.analysis", subject="port_new", why=WHY)
    assert refused["error"] == "no_completed_run"                          # the resolver's reason, not "unknown run"
    await metric(None, name="book.analysis", subject=["port_001", "port_new", "run_x"], why=WHY)
    assert asked["subject"] == ["run_latest", "port_new", "run_x"]         # one refusal is one row, not the call
    # a measure over a PORTFOLIO keeps the id it was given
    await metric(None, name="book.drawdown_episodes", subject="port_001", why=WHY)
    assert asked["subject"] == "port_001"


# ── an ordering's entries say what was ordered ───────────────────────────────

_RANKING = {"calc_id": "calc_238606c844ed", "op": "rank", "quantity": "issuer_exposures.weight", "direction": "highest",
            "as_of": "2026-09-10", "leader": "MSFT",
            "ordering": [{"label": "MSFT", "ref": "f_a", "value": 0.1604, "as_of": "2026-09-10", "rank": 1},
                         {"label": "AAPL", "ref": "f_b", "value": 0.1520, "as_of": "2026-09-10", "rank": 2}],
            "spread": 0.035, "operands": ["f_a", "f_b", "f_c", "f_d"],
            "type": {"unit_class": "ratio", "kind": "ranking", "quantity": "issuer_exposures.weight"}}


def test_a_ranked_row_is_named_for_what_was_ranked_with_its_place_among_how_many():
    facts, _ = fa.compute({"op": "rank"}, _RANKING)
    first = next(f for f in facts if f.subject == "MSFT")
    assert first.measure == "issuer_exposures.weight"
    assert first.params["place"] == 1 and first.params["of"] == 4 and first.params["direction"] == "highest"
    line = F.line(first)
    assert "issuer exposures: weight, MSFT" in line and "1st highest of 4" in line and "ordering value" not in line
    spread = next(f for f in facts if f.measure.endswith(".spread"))
    assert "highest to lowest of the 4 ranked" in F.line(spread)

    lowest, _ = fa.compute({"op": "rank"}, {**_RANKING, "direction": "lowest"})
    assert "1st lowest of 4" in F.line(next(f for f in lowest if f.subject == "MSFT"))


async def test_top_does_not_carry_the_spread_of_everything_it_cut(monkeypatch):
    async def _compute(db, **kw):
        return {**_RANKING}
    monkeypatch.setattr(P.compute_service, "compute", _compute)
    out = await P._calc(None, "top", ["f_a", "f_b", "f_c", "f_d"], direction="highest", n=1, why=WHY)
    assert len(out["ordering"]) == 1 and "spread" not in out


# ── a filter's count carries no bare number beside it ────────────────────────

def test_a_filters_payload_is_typed_to_the_last_leaf():
    payload = {"calc_id": "calc_n", "value": 5.0, "unit_class": "count", "op": "filter",
               "quantity": "figures > 8%, of the 10 given", "kept": ["f_a", "f_b"]}
    facts, note = fa.adapt("calc", {"op": "filter"}, payload)[:2]
    assert "untyped" not in note                                            # "of": 10 was one, and the adapter said so
    assert "of the 10 given" in F.line(facts[0])
    assert fa.present("calc", {"op": "filter", "why": WHY}, facts, note, None, "r_3")["kept"] == ["f_a", "f_b"]


# ── a sum is called a sum ────────────────────────────────────────────────────

async def test_a_fold_names_its_last_step_for_what_it_is(monkeypatch):
    named = []

    async def _calculate(db, op, a, b, **kw):
        named.append(kw.get("default_quantity"))
        return {"calc_id": f"calc_{len(named)}", "value": 1.0}
    monkeypatch.setattr(compute_service.tc, "calculate", _calculate)
    await compute_service._fold(None, "add", ["w1", "w2", "w3", "w4", "w5"], None, "sess")
    assert named == [None, None, None, "sum of 5 figures"]                  # only the step a reader is shown
    named.clear()
    await compute_service._fold(None, "add", ["w1", "w2"], None, "sess")
    assert named == [None]                                                  # two figures keep their own lineage name


# ── what stood in for what is said in words ──────────────────────────────────

def test_a_substitution_inside_a_composed_total_is_a_sentence():
    words = desk.composition_words({"made_of": {"total_debt": {
        "formula": "long_term_debt_and_leases_noncurrent + debt_current_total",
        "substituted": {"long_term_debt_noncurrent": "long_term_debt_and_leases_noncurrent"}}}})
    said = "; ".join(words)
    assert "total debt is built on long term debt and leases noncurrent in place of long term debt noncurrent" in said
    assert "{" not in said and "'" not in said


# ── a beta is a multiple wherever it sits ────────────────────────────────────

def test_every_beta_is_typed_as_a_multiple_from_one_declaration():
    assert rs.column_unit("factor_attributions", "beta") == rs.MULTIPLE
    assert rs.column_unit("factor_attributions", "contribution") == rs.RATIO      # beta × a return is still a share
    for key in ("beta", "net_beta", "gross_beta", "signed_for_this_risk"):
        assert fa.UNIT_BY_KEY[key] == fa.MULTIPLE, key
    assert fa.UNIT_BY_KEY["net_beta"] == rs.CALC_RESULTS["portfolio.integration"]["net_beta"]
    f = F.fact(F.SCALAR, "portfolio.integration.net_beta.credit_spreads_widen", subject="run_x", unit=fa.MULTIPLE,
               value=-0.239, as_of="2026-09-10", means={"direction": "loses"})
    assert "-0.24×" in F.line(f) and "%" not in F.line(f).split(" — ")[0]


# ── one instant, one wording; one subject, said once ─────────────────────────

def test_an_instant_reads_as_of_whichever_field_holds_it():
    a = F.fact(F.SCALAR, "total_debt", subject="XOM", unit="MONEY", value=1.0, as_of="2026-03-31")
    b = F.fact(F.SCALAR, "total_debt", subject="XOM", unit="MONEY", value=1.0, window={"instant": "2026-03-31"})
    assert F.when_of(F.for_record(a)) == F.when_of(F.for_record(b)) == "as of 2026-03-31"


def test_a_row_names_its_subject_once():
    f = F.fact(F.SCALAR, "AAPL_beta_TLT", subject="AAPL", unit="MULTIPLE", value=0.2, as_of="2026-09-10")
    row = F.model_row(f)
    assert row["what"] == "beta TLT" and row["of"] == "AAPL"
    alone = F.fact(F.SCALAR, "AAPL", subject="AAPL", unit="MONEY", value=1.0, as_of="2026-09-10")
    assert F.model_row(alone)["what"] == "AAPL"                             # never stripped to nothing


# ── a measure of another family is not a misspelling ─────────────────────────

def test_the_refusal_for_another_familys_measure_says_whose_it_is_and_nothing_else():
    f = fa.refusal_fact("metric", {"name": "price.beta", "subject": "MSFT"},
                        {"error": "invalid_arguments", "problems": [
                            {"field": "name", "value": "price.beta",
                             "problem": "'price.beta' is not one of the 34 names this argument takes; nearest: ebitda, roic, ebit"}]})
    assert f.means["reason"] == "not_on_this_face"
    assert "nearest" not in f.text and "nearest" not in f.means["way_out"]
    assert "the market analyst" in f.means["way_out"]


# ── a scenario builds a book; reading it is book_read ────────────────────────

_SCENARIO = {"method": "book.sell", "subject": "run_x", "calc_id": "calc_f3375b0f4a77", "made": "calc_f3375b0f4a77",
             "from_run": "run_x", "as_of": "2026-09-10", "sales": [{"ticker": "AAPL", "fraction": 0.5}],
             "sold": [{"ticker": "AAPL", "fraction": 0.5, "market_value_sold": 816425.0}],
             "proceeds": 816425.0, "market_value": 9929505.0,
             "positions": [{"ticker": "MSFT", "market_value": 1.72e6, "weight": 0.174}],
             "sectors": [{"sector": "Technology", "market_value": 3.1e6, "weight": 0.31}],
             "limit_checks": [], "alerts": [], "checks_not_run": ["daily_loss", "rolling_volatility_30d"],
             "factor_exposure": {"measured": False, "reason": "betas are a regression over the book's return history"},
             "not_a_forecast": True, "cite": "calc_f3375b0f4a77"}


def test_a_scenario_shows_the_trade_and_what_it_does_not_carry_and_records_the_rest():
    shown, note, held, made = fa.adapt_all("scenario", {"book": "port_001"}, _SCENARIO)
    shown_measures = {f.measure for f in shown if f.kind != F.ABSENCE}
    assert not any(m.split(".")[0] in ("issuer_exposures", "sector_exposures", "limit_checks") for m in shown_measures)
    assert any("proceeds" in m for m in shown_measures)
    assert not any(m.startswith("sales") for m in {f.measure for f in made})        # the caller's list is not echoed as figures
    absent = [f for f in shown if f.kind == F.ABSENCE]
    assert {f.measure for f in absent} == {"limit_checks.daily_loss", "limit_checks.rolling_volatility_30d", "factor_attributions"}
    assert all(f.means["reason"] == "meaningless" for f in absent)
    # the new book's tables are on the ledger, where a sentence can point at them
    assert any(f.measure.startswith("issuer_exposures") for f in made) and len(made) > len(shown)
    out = fa.present("scenario", {"book": "port_001", "why": WHY}, shown, note, held, "r_9")
    assert out["made"] == "calc_f3375b0f4a77" and 'book_read(book="calc_f3375b0f4a77")' in out["held_back"]


# ── a check is listed by what it is a check on ───────────────────────────────

async def test_a_check_is_listed_by_what_it_checks(monkeypatch):
    async def _limits(db, portfolio_id):
        return {"limits": [{"limit_type": "issuer_concentration", "entity_type": "issuer", "entity_id": "AAPL"},
                           {"limit_type": "daily_loss", "entity_type": None, "entity_id": None}]}
    monkeypatch.setattr(P.run_reads_service, "list_risk_limits", _limits)
    lines = await P._checks_lines(None, "port_001")
    assert lines[0].startswith("issuer_concentration:AAPL — a check on one issuer")
    assert lines[1].startswith("daily_loss — a check on the whole book")
    assert not any(" a issuer" in l for l in lines)


# ── a service names no door ──────────────────────────────────────────────────
# A service does not know which analyst is reading its refusal, and two of the
# three do not hold any given read. It says what is needed in the desk's words;
# the verb's own description is where a verb is named. The retired names are the
# hard part of this: `read_fundamentals`, `describe`, `compute(…)`, `run(…)` and
# the program language's nodes were all still being recommended by refusals on
# the day their verbs were deleted.

_RETIRED = re.compile(
    r"\b(read_fundamentals|read_prices|read_book|read_filings|search_web|run_program|submit_report|describe_issuer)\b"
    r"|\b(compute|describe|run|delegate)\((?!\))"
    r"|\bfundamentals\(|\bmethod\(name|\ba [a-z_]+\(…[^)]*\) node\b|\{'fn':"
    r"|\bparams\.(by|factor)\b|\bcall describe\b|\bdescribe lists\b")
# dead modules kept only until the boss rules on deleting them (docs/IMPLEMENTATION_PLAN_V1.md §5)
_EXEMPT = {"tools/meta_tools.py", "analytics/semantics.py", "services/claims.py"}


def _sentences(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings \
                and " " in node.value:
            yield node.lineno, node.value


def test_no_sentence_the_desk_can_say_names_a_retired_verb_or_a_program_node():
    root = pathlib.Path(P.__file__).resolve().parents[1]
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in _EXEMPT:
            continue
        for lineno, text in _sentences(path):
            hit = _RETIRED.search(text)
            if hit:
                found.append(f"{rel}:{lineno}: {hit.group(0)!r} in {text[:90]!r}")
    assert found == [], "\n".join(found)


# ── a word sits on the figure it is about ────────────────────────────────────

_ANALYSIS = {"method": "book.analysis", "subject": "run_x", "run_id": "run_x", "as_of": "2026-09-10", "calc_id": "calc_a",
             "net_exposures": {"credit_spreads_widen": {
                 "measured": True, "direction": "loses", "net_beta": -0.239, "gross_beta": 0.239,
                 "quotable_individually": False, "basis": ["book_return"],
                 "legs": [{"factor_name": "credit", "beta": 0.239, "signed_for_this_risk": -0.239, "cite": "run_x"}]}},
             "headroom": [{"check": "issuer_concentration:AAPL", "current": 0.152, "warning_level": 0.15,
                           "breach_level": 0.20, "room_to_warning": -0.002, "room_to_breach": 0.048, "status": "warning"}],
             "positions": [{"ticker": "MSFT", "weight": 0.16, "market_value": 1.72e6}]}


def test_book_analysis_yields_what_it_derived_under_the_names_the_registry_declares():
    facts, _ = fa.compute({"name": "book.analysis", "subject": "run_x"}, {
        **_ANALYSIS, "stress_withheld": "stress results are withheld pending validation",
        "net_exposures": {**_ANALYSIS["net_exposures"],
                          "rates_up": {"measured": False, "reason": "no factor in this run's regression measures this risk"}}})
    net = next(f for f in facts if f.measure == "portfolio.integration.net_beta.credit_spreads_widen")
    gross = next(f for f in facts if f.measure == "portfolio.integration.gross_beta.credit_spreads_widen")
    room = next(f for f in facts if f.measure == "portfolio.integration.room_to_breach")
    assert net.means.get("direction") == "loses" and "direction" not in gross.means      # a size has no direction
    for f in (net, gross):
        assert f.means.get("basis") == ["book_return"] and f.unit == fa.MULTIPLE and f.standalone
        assert f.means.get("flags") == ["collinear_legs_not_quotable"]
    assert room.subject == "issuer_concentration:AAPL" and room.means == {"status": "warning"}
    line = F.line(net)
    assert "net beta to credit spreads widen, run_x" in line and "-0.24×" in line and "method book.analysis" in line
    assert "room to the breach tier, issuer_concentration:AAPL" in F.line(room)
    # a risk nothing measures is SAID, as the absence it is — never a missing row
    unmeasured = next(f for f in facts if f.measure == "portfolio.integration.net_beta.rates_up")
    assert unmeasured.kind == F.ABSENCE and "not measured" in unmeasured.text
    withheld = next(f for f in facts if f.measure == "stress_results")
    assert withheld.means == {"reason": "policy", "flags": ["withheld_pending_validation"]}
    # and nothing it only READ: no position, no tier, no leg
    assert not any(f.measure.split(".")[0] in ("issuer_exposures", "limit_checks", "legs", "positions") for f in facts)


def test_a_walked_payload_puts_the_nets_word_on_the_net_only():
    """The generic walker, for any payload shaped like a net with its parts."""
    facts, _ = fa.compute({"op": "x"}, {"calc_id": "calc_w", "as_of": "2026-09-10", "numeric_unit": "multiple",
                                        "direction": "loses", "net_beta": -0.2, "gross_beta": 0.2})
    by = {f.measure: f for f in facts}
    assert by["net_beta"].means.get("direction") == "loses" and "direction" not in by["gross_beta"].means


def test_a_basis_is_a_registry_word_only_when_the_producer_wrote_a_list_of_them():
    assert desk.words_beside({"basis": ["book_return"]}) == {"basis": ["book_return"]}
    assert desk.words_beside({"basis": "balance sheet as of 2026-03-31"}) == {}
    assert desk.words_beside({"basis": ["not a registry word"]}) == {}
    assert desk.METHODS["book.analysis"].basis == ()


# ── the row states the period it has — both, when it has two ────────────────

def test_a_figure_over_two_windows_says_both():
    ratio = {"calc_id": "calc_r", "op": "divide", "value": 1.238,
             "type": {"unit_class": "ratio", "quantity": "short over long volatility", "issuers": ["AAPL"],
                      "basis": {"mixed": "…", "leaves": {"instants": [], "intervals": [["2025-09-10", "2026-09-10"],
                                                                                      ["2026-07-30", "2026-09-10"]]}}}}
    facts, _ = fa.compute({"op": "divide"}, ratio)
    line = F.line(facts[0])
    assert "over two periods, 2025-09-10 to 2026-09-10 and 2026-07-30 to 2026-09-10" in line

    same = {**ratio, "type": {**ratio["type"], "basis": {"leaves": {"instants": [], "intervals": [
        ["2025-04-01", "2026-03-31"], ["2025-04-01", "2026-03-31"]]}}}}
    assert "2025-04-01 to 2026-03-31" in F.line(fa.compute({"op": "divide"}, same)[0][0])
    assert "two periods" not in F.line(fa.compute({"op": "divide"}, same)[0][0])


def test_a_change_between_two_dates_runs_from_one_to_the_other():
    delta = {"calc_id": "calc_d", "op": "subtract", "value": 2.0e9,
             "type": {"unit_class": "money", "quantity": "change in total debt", "issuers": ["XOM"],
                      "basis": {"leaves": {"instants": ["2026-03-31", "2025-06-30"], "intervals": []}}}}
    facts, _ = fa.compute({"op": "subtract"}, delta)
    assert "2025-06-30 to 2026-03-31" in F.line(facts[0])
