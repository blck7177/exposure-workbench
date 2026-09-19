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
    r"|\bparams\.(by|factor)\b|\bcall describe\b|\bdescribe lists\b|\bcompare: rank\b"
    r"|\bprogram node\b|\brun a program\b|\bto the program\b|\bdescribe not_held\b|\b(rank|yoy|qoq|subtract) node\b")
# No module is exempt. Three were, on the claim that they were dead: two were (the chat exit
# in tools/meta_tools.py and analytics/semantics.py, deleted 2026-09-19) and one was not —
# services/claims.py is the research brief's exit, and its refusals were still sending a
# research agent that holds verbs to "a refused program node" and "a describe entry".
_EXEMPT: set[str] = set()


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


# ── the first live turns (2026-09-19) ────────────────────────────────────────
# Four questions through the whole chain — lead, ask, analyst, verbs, submit,
# handoff, answer check — against the smoke database.

def test_metric_says_what_each_measure_takes_where_the_argument_is_filled_in():
    """The market analyst asked price.volatility for `window: "21d"`: it had to
    guess the key, because `params` was described as an object and nothing more.
    All three calls were refused, and it filed both lines unsettled."""
    said = P.build_analyst_registry("market").get("metric").json_schema["properties"]["params"]["description"]
    assert "price.volatility — window_days = 21 | 30 | 63 | 126 | 252" in said
    assert "price.momentum_12_1, price.distance_from_52w_high — takes no params" in said
    issuer = P.build_analyst_registry("issuer").get("metric").json_schema["properties"]["params"]["description"]
    assert "every other measure — months = 3 | 6 | 9 | 12" in issuer and issuer.count("months = ") == 1   # thirty formulas, said once
    risk = P.build_analyst_registry("risk").get("metric").json_schema["properties"]["params"]["description"]
    assert "book.explain_episode — peak (required): YYYY-MM-DD; trough (required): YYYY-MM-DD" in risk


def test_params_that_do_not_fit_are_refused_with_the_params_the_measure_takes():
    spec = desk.METHODS["price.volatility"]
    f = fa.refusal_fact("metric", {"name": "price.volatility", "subject": "AAPL", "params": {"window": "21d"}},
                        {"error": "invalid_params", "detail": "price.volatility: params do not fit the method's schema",
                         "problems": [{"field": "window", "problem": "Additional properties are not allowed ('window' was unexpected)"}],
                         "params_schema": spec.params_schema})
    assert f.means["reason"] == "param_out_of_range"
    assert f.means["way_out"].startswith("price.volatility takes: window_days = 21 | 30 | 63 | 126 | 252")


# ── the checks, where they were false to what the reader was shown ──────────

def _ledger_with(*facts):
    from exposure_workbench.services import ledger as L
    return L.Ledger.of_facts(list(facts))


def test_a_calculation_records_what_it_was_made_of_and_the_row_says_so():
    facts, _ = fa.compute({"op": "divide", "inputs": ["f_aaaa11112222", "f_bbbb33334444"], "why": WHY},
                          {"calc_id": "calc_q", "op": "divide", "value": 0.394,
                           "type": {"unit_class": "ratio", "quantity": "fcf_to_debt_xom", "issuers": ["XOM"],
                                    "basis": {"leaves": {"instants": ["2026-03-31"], "intervals": [["2025-04-01", "2026-03-31"]]}}}})
    assert facts[0].params["inputs"] == ["f_aaaa11112222", "f_bbbb33334444"]
    assert "op divide of f_aaaa11112222 and f_bbbb33334444" in F.line(facts[0])
    # a measure is made by its method, not by inputs the caller typed
    own, _ = fa.compute({"name": "roe", "subject": "XOM", "inputs": ["f_x"]},
                        {"method": "roe", "subject": "XOM", "calc_id": "calc_r", "value": 0.1, "unit_class": "ratio", "as_of": "2026-03-31"})
    assert "inputs" not in own[0].params


def test_each_entry_of_a_list_combined_with_one_figure_is_made_of_that_entry_and_that_figure():
    facts, _ = fa.compute({"op": "divide", "inputs": ["f_a1a1a1a1a1a1", "f_b2b2b2b2b2b2"], "by": "f_c3c3c3c3c3c3"},
                          {"op": "divide", "by": "f_c3c3c3c3c3c3", "count": 2, "results": [
                              {"operand": "f_a1a1a1a1a1a1", "calc_id": "calc_1", "op": "divide", "value": 0.2, "type": {"unit_class": "ratio", "quantity": "x"}},
                              {"operand": "f_b2b2b2b2b2b2", "calc_id": "calc_2", "op": "divide", "value": 0.3, "type": {"unit_class": "ratio", "quantity": "x"}}]})
    assert [f.params["inputs"] for f in facts] == [["f_a1a1a1a1a1a1", "f_c3c3c3c3c3c3"], ["f_b2b2b2b2b2b2", "f_c3c3c3c3c3c3"]]


def test_a_named_quotient_still_answers_to_the_measures_it_was_made_of():
    """Refused live: "free cash flow to debt is 39.4% [f_…]" beside the analyst's own
    `fcf_to_debt_xom` = divide(free_cash_flow, total_debt) — the sentence named a
    measure the ledger held, and nothing on the quotient said it was built from it."""
    from exposure_workbench.services import answer_check as AC
    fcf = F.fact(F.SCALAR, "free_cash_flow", subject="XOM", unit="MONEY", value=18.79e9, window={"start": "2025-04-01", "end": "2026-03-31"})
    debt = F.fact(F.SCALAR, "total_debt", subject="XOM", unit="MONEY", value=47.66e9, as_of="2026-03-31")
    q = F.fact(F.SCALAR, "fcf_to_debt_xom", subject="XOM", unit="RATIO", value=0.394, as_of="2026-03-31",
               params={"op": "divide", "inputs": [fcf.id, debt.id]})
    led = _ledger_with(fcf, debt, q)
    ok = AC.check(f"XOM's free cash flow to debt is 39.4% [{q.id}].", led)
    assert not [p for p in ok.problems if p["reason"] == "measure_mismatch"], ok.problems
    bare = F.fact(F.SCALAR, "fcf_to_debt_xom", subject="XOM", unit="RATIO", value=0.394, as_of="2026-03-31", params={"op": "divide"})
    led2 = _ledger_with(fcf, debt, bare)
    assert [p for p in AC.check(f"XOM's free cash flow to debt is 39.4% [{bare.id}].", led2).problems if p["reason"] == "measure_mismatch"]


_MDA = ("On December 31, 2025, the Corporation had total unused short-term committed lines of credit of $7.3 billion. "
        "The table below shows the Corporation's consolidated debt to capital ratios.\\n (percent)202520242023\\n"
        "Debt to capital14.0 13.4 16.4 \\nNet debt to capital (1)\\n11.0 6.5 4.5")


def test_a_short_bare_number_the_passage_holds_is_refused_with_a_way_out_that_is_true():
    """Live: the lead wrote "debt to capital was 14.0 [f_passage]", was told the
    passage "does not state this figure", sent the same sentence again and lost
    the answer. The passage reads "Debt to capital14.0". The rule stands — a short
    number written bare is not matched against a filing — and the refusal now says
    that, and what to write instead."""
    from exposure_workbench.services import answer_check as AC
    p = F.fact(F.PASSAGE, "10-K Item 7", subject="XOM", text=_MDA, as_of="2026-02-18")
    led = _ledger_with(p)
    refused = AC.check(f"XOM's debt to capital was 14.0 [{p.id}].", led)
    (problem,) = [x for x in refused.problems if x["reason"] == "mark_mismatch"]
    assert "WITH THE UNIT THE PASSAGE GIVES IT" in problem["fix"] and "does not state" not in problem["fix"]
    assert not AC.check(f"XOM's debt to capital was 14.0 percent [{p.id}].", led).problems
    # a number the passage does NOT hold keeps the old sentence
    (other,) = [x for x in AC.check(f"XOM's debt to capital was 19.5 [{p.id}].", led).problems if x["reason"] == "mark_mismatch"]
    assert "does not state this figure" in other["fix"]


def test_a_date_a_cited_passage_spells_out_is_the_same_date_written_iso():
    from exposure_workbench.services import answer as A, answer_check as AC
    assert A.dates_stated(_MDA) == {"2025-12-31"}
    p = F.fact(F.PASSAGE, "10-K Item 7", subject="XOM", text=_MDA, as_of="2026-02-18")
    led = _ledger_with(p)
    v = AC.check(f"At 2025-12-31 the Corporation had unused short-term committed lines of $7.3 billion [{p.id}].", led)
    assert not [x for x in v.problems if x.get("figure") == "2025-12-31"], v.problems
    wrong = AC.check(f"At 2024-12-31 the Corporation had unused short-term committed lines of $7.3 billion [{p.id}].", led)
    assert [x for x in wrong.problems if x.get("figure") == "2024-12-31"]


def test_the_same_reading_on_two_books_is_a_comparison_not_a_reading_written_twice():
    """Live: "gross exposure would stay at 100.0% [after] versus 100.0% [before]" —
    the scenario's book against the run it started from — refused as one reading
    written twice. The book a row was read off is part of which reading it is."""
    from exposure_workbench.services import answer_check as AC
    before = F.fact(F.SCALAR, "limit_checks.current_value", subject="gross_exposure", unit="RATIO", value=1.0,
                    as_of="2026-09-10", params={"of": "run_e2945c5ebd5a"})
    after = F.fact(F.SCALAR, "limit_checks.current_value", subject="gross_exposure", unit="RATIO", value=1.0,
                   as_of="2026-09-10", params={"of": "calc_50d834000e6f"})
    led = _ledger_with(before, after)
    v = AC.check(f"Gross exposure would stay at 100.0% [{after.id}] after the sale, versus 100.0% [{before.id}] in the latest book.", led)
    assert not [p for p in v.problems if p["reason"] == "change_conflict"], v.problems
    twice = F.fact(F.SCALAR, "issuer_exposures.weight", subject="gross_exposure", unit="RATIO", value=1.0,
                   as_of="2026-09-10", params={"of": "run_e2945c5ebd5a"})
    led2 = _ledger_with(before, twice)
    v2 = AC.check(f"Gross exposure went from 100.0% [{before.id}] to 100.0% [{twice.id}].", led2)
    assert [p for p in v2.problems if p["reason"] == "change_conflict"]


def test_the_metric_verb_says_each_name_in_the_handbooks_words():
    said = P.build_analyst_registry("risk").get("metric").json_schema["properties"]["name"]["description"]
    assert "book.analysis = the book's net exposures and room to its tiers" in said


def test_a_span_of_time_a_cited_passage_states_is_the_passages_phrase():
    from exposure_workbench.services import answer_check as AC
    p = F.fact(F.PASSAGE, "10-K Item 7", subject="AAPL", as_of="2025-10-31",
               text="The Company had fixed-rate notes for an aggregate principal amount of $91.3 billion, with $12.4 billion "
                    "payable within 12 months. Cash is expected to be sufficient over the next 12 months and beyond.")
    led = _ledger_with(p)
    v = AC.check(f"The filing says $12.4 billion of its notes is payable within 12 months [{p.id}].", led)
    assert not [x for x in v.problems if x.get("figure") == "12"], v.problems
    other = AC.check(f"The filing says $12.4 billion of its notes is payable within 18 months [{p.id}].", led)
    assert [x for x in other.problems if x.get("figure") == "18"]


def test_a_list_of_brackets_leaves_no_commas_behind():
    from exposure_workbench.services import answer_check as AC
    a, b, c = (F.fact(F.SCALAR, "limit_checks.current_value", subject=f"issuer_concentration:{t}", unit="RATIO", value=v,
                      as_of="2026-09-10", means={"status": "warning"}) for t, v in (("JPM", 0.16), ("LLY", 0.136), ("MSFT", 0.174)))
    led = _ledger_with(a, b, c)
    text = f"The checks that would still warn are JPM, LLY, and MSFT issuer concentration [{a.id}], [{b.id}], [{c.id}]. Nothing else moves."
    v = AC.check(text, led)
    out = AC.accepted(text, v, led)
    assert out["text"].startswith("The checks that would still warn are JPM, LLY, and MSFT issuer concentration. Nothing else moves.")
    assert ",," not in out["text"] and set(out["citations"]) == {a.id, b.id, c.id}


# ── the broader live pass (seven questions) ─────────────────────────────────

async def test_one_filed_line_is_read_over_several_issuers_in_one_call(monkeypatch):
    async def _read(db, ticker, metric=None, **kw):
        if ticker == "JPM":
            return {"error": "metric_not_filed", "ticker": "JPM", "metric": metric, "detail": "JPM has no filed facts under 'inventory'"}
        return {"ticker": ticker, "metric": metric, "value": 1.0e9, "unit_class": "money", "calc_id": f"calc_{ticker.lower()}aaaa",
                "period": {"start": "2025-04-01", "end": "2026-03-31"}}
    monkeypatch.setattr(P.D, "_read_fundamentals", _read)
    out = await P._filings_read(None, ["MSFT", "JPM", "MSFT"], line="inventory", months=12, why=WHY)
    assert [r["asked"] for r in out["results"]] == ["MSFT", "JPM"]                 # a name asked twice is read once
    facts, _ = fa.read_fundamentals({"ticker": ["MSFT", "JPM"], "line": "inventory"}, out)
    assert [(f.kind, f.subject) for f in facts] == [(F.SCALAR, "MSFT"), (F.ABSENCE, "JPM")]
    assert facts[1].means["reason"] == "not_held"
    whole = await P._filings_read(None, ["MSFT", "JPM"], why=WHY)
    assert whole["error"] == "invalid_params"                                        # a whole sheet is one issuer's
    schema = P.build_analyst_registry("issuer").get("filings_read").json_schema["properties"]["ticker"]
    assert schema["type"] == ["string", "array"] and schema["maxItems"] == P.FILINGS_READ_TICKERS


def test_dated_rows_of_a_list_are_one_measure_and_say_their_own_dates():
    payload = {"method": "book.drawdown_episodes", "subject": "port_001", "calc_id": "calc_ep", "sessions": 252,
               "from": "2025-09-10", "to": "2026-09-10",
               "episodes": [{"peak_date": "2026-01-07", "trough_date": "2026-03-27", "recovery_date": "2026-05-01",
                             "depth": 0.12, "trough_days": 55, "recovery_days": 24},
                            {"peak_date": "2026-05-29", "trough_date": "2026-06-25", "recovery_date": None,
                             "depth": 0.0624, "trough_days": 18}]}
    facts, _ = fa.compute({"name": "book.drawdown_episodes", "subject": "port_001"}, payload)
    depths = [f for f in facts if f.measure.endswith("depth")]
    assert len(depths) == 2 and len({f.measure for f in depths}) == 1              # one measure, two episodes
    first, second = (F.line(f) for f in depths)
    assert "peak 2026-01-07 to trough 2026-03-27, recovered 2026-05-01" in first
    assert "peak 2026-05-29 to trough 2026-06-25" in second and "recovered" not in second
    assert all(f.means.get("basis") == ["todays_holdings"] for f in depths)


def test_a_list_argument_reads_as_names_in_the_progress_line():
    from exposure_workbench.tools import display
    said = display.render("Measuring {name} for {subject}", {"name": "price.beta", "subject": ["AAPL", "XOM"]})
    assert "AAPL, XOM" in said and "[" not in said


async def test_a_price_measure_asked_of_a_book_says_whose_the_question_is(monkeypatch):
    async def _compute(db, **kw):
        raise AssertionError("a book is never sent to a price measure")
    monkeypatch.setattr(P.compute_service, "compute", _compute)
    out = await P.build_analyst_registry("market").get("metric").fn(None, name="price.drawdown", subject="port_001", why=WHY)
    assert out["error"] == "not_on_this_face" and "the risk analyst's" in out["hint"]
    f = fa.refusal_fact("metric", {"name": "price.drawdown", "subject": "port_001"}, out)
    assert f.means["reason"] == "not_on_this_face" and "risk analyst" in f.means["way_out"]
    assert "holds" not in f.text                       # never "the desk holds no prices for this book"



# ── after the dead code went (2026-09-19) ────────────────────────────────────

def test_a_row_the_desk_ranked_is_a_rank_claim_in_the_brief_too():
    """`_ranked` renamed a ranked row's `rank` to `place` (among `of`), and the claims
    gate — the research brief's exit, which was thought dead and is not — still looked
    for `rank` only: every rank claim over a V1 ranked row would have been refused."""
    from exposure_workbench.services import claims as C
    ranked = F.fact(F.SCALAR, "gross_margin", subject="MSFT", unit="RATIO", value=0.69, as_of="2026-03-31",
                    params={"op": "rank", "place": 1, "of": 4, "direction": "highest"})
    plain = F.fact(F.SCALAR, "gross_margin", subject="AAPL", unit="RATIO", value=0.46, as_of="2026-03-28")
    led = _ledger_with(ranked, plain)
    assert C._check_relation({"relation": "rank", "of": ranked.id}, led) is None
    refused = C._check_relation({"relation": "rank", "of": plain.id}, led)
    assert refused["reason"] == "no_ordering" and "ranked" in refused["detail"] and "node" not in refused["detail"]
    assert C._runs_for({"relation": "rank", "of": ranked.id}, led)[1] == " (#1)"


def test_a_place_in_a_lowest_first_ordering_is_counted_from_the_other_end():
    from exposure_workbench.services import answer_check as AC
    low = F.fact(F.SCALAR, "price.volatility", subject="KO", unit="RATIO", value=0.14, as_of="2026-09-10",
                 params={"op": "rank", "place": 1, "of": 9, "direction": "lowest"})
    led = _ledger_with(low)
    assert not [p for p in AC.check(f"KO has the lowest volatility of the nine at 14.0% [{low.id}].", led).problems
                if p["reason"] == "superlative_without_rank"]
    assert [p for p in AC.check(f"KO has the highest volatility of the nine at 14.0% [{low.id}].", led).problems
            if p["reason"] == "superlative_without_rank"]


# ── back to the plan's signatures (2026-09-19, after the deviation review) ───

def test_calc_takes_no_name_and_the_desk_says_what_the_result_is():
    """Plan V1 §0: the model does not name a measure. `calc` carried a `name`
    (the old compute's `as_quantity`) and 45 of 46 live calls used it."""
    schema = P.build_analyst_registry("risk").get("calc").json_schema
    assert "name" not in schema["properties"]
    assert desk.reads_as("free_cash_flow.divide.total_debt") == "free cash flow ÷ total debt"
    assert (desk.reads_as("limit_checks.breach_level.subtract.limit_checks.current_value")
            == "limit checks: breach tier − limit checks: measured")
    assert desk.reads_as("issuer_exposures.weight.max") == "highest of issuer exposures: weight"
    assert desk.reads_as("revenue.yoy") == "year-on-year change in Revenue"
    # a registry name that merely contains an operation's word is still itself
    assert desk.reads_as("net_margin") == "net margin" and desk.reads_as("price.beta") == "beta to a benchmark"
    room = F.fact(F.SCALAR, "limit_checks.breach_level.subtract.limit_checks.current_value",
                  subject="issuer_concentration:AAPL", unit="RATIO", value=0.048, as_of="2026-09-10",
                  params={"op": "subtract", "inputs": ["f_aaaa11112222", "f_bbbb33334444"]})
    assert F.line(room).startswith(f"[{room.id}] limit checks: breach tier − limit checks: measured, issuer_concentration:AAPL")
    ratio = F.fact(F.SCALAR, "AAPL.vol.30d.divide.AAPL.vol.252d", subject="AAPL", unit="RATIO", value=1.24, as_of="2026-09-10")
    assert F.model_row(ratio)["what"] == "vol 30d ÷ vol 252d"


def test_trades_apply_in_order_and_each_side_keeps_the_engines_refusals():
    from exposure_workbench.analytics import scenario as sc
    book = [sc.Holding("AAPL", "Technology", 1500.0), sc.Holding("JPM", "Financials", 1500.0), sc.Holding("XOM", "Energy", 1000.0)]
    after = sc.traded(book, [("sell", [sc.Sale("AAPL", 0.5)]), ("buy", [sc.Buy("KO", 0.10, "Consumer_Staples")])])
    assert round(after.market_value, 2) == 3611.11 and round(after.weights["KO"], 4) == 0.10
    assert round(after.proceeds, 2) == 388.89                     # what left, less what came in from outside
    assert [(s.ticker, s.market_value_sold) for s in after.sold] == [("AAPL", 750.0)]
    assert [(b.ticker, round(b.market_value_added, 2)) for b in after.bought] == [("KO", 361.11)]
    # the order is the writer's: bought first, KO is diluted by nothing later and AAPL's half is of the larger book
    other = sc.traded(book, [("buy", [sc.Buy("KO", 0.10, "Consumer_Staples")]), ("sell", [sc.Sale("AAPL", 0.5)])])
    assert round(other.weights["KO"], 4) != 0.10 and [b.ticker for b in other.bought] == ["KO"]
    assert round(next(b.weight for b in other.bought), 4) == round(other.weights["KO"], 4)     # its FINAL weight
    assert sc.traded(book, [("buy", [sc.Buy("AAPL", 0.10, "Technology")])])["error"] == "already_held"
    assert sc.traded(book, [("sell", [sc.Sale("KO", 1.0)])])["error"] == "not_held"
    assert sc.traded(book, [])["error"] == "no_trades"


def test_a_scenario_shows_both_sides_of_the_trade():
    payload = {**_SCENARIO, "sales": None, "trades": [{"sell": "AAPL", "fraction": 0.5}, {"buy": "KO", "weight": 0.05}],
               "bought": [{"ticker": "KO", "weight": 0.05, "market_value_added": 522605.5}]}
    payload = {k: v for k, v in payload.items() if v is not None}
    shown, _note, held, made = fa.adapt_all("scenario", {"book": "port_001"}, payload)
    said = "\\n".join(F.line(f) for f in shown)
    assert "bought market value added, KO" in said and "bought weight, KO" in said and "sold market value sold, AAPL" in said
    assert not any(f.measure.startswith("trades") for f in made)          # the caller's list is not echoed as figures


async def test_prices_read_names_the_one_field_it_wants(monkeypatch):
    """Plan V1 §2.3: field ∈ {close, adj_close, volume}. It had none, and volume
    could only be had as the average the liquidity measure computes."""
    from datetime import date
    from exposure_workbench.services import price_analytics_service as pas
    bars = [pas.Bar(date(2026, 9, d), 100.0 + d, 99.0 + d, 1_000_000 * d) for d in (8, 9, 10)]

    async def _bars(db, ticker, start=None, end=None):
        return [b for b in bars if end is None or b.date <= end]

    async def _market_bars(db, ticker):
        return bars if ticker == "AAPL" else []

    recorded = []

    async def _record(db, ticker, op, params, result, inputs, flags, invoked_by, **kw):
        recorded.append((op, params.get("column"), params["result_type"]["unit_class"]))
        return f"calc_{len(recorded):012d}"

    async def _none(db, **kw):
        return {"error": "no_price_data", "detail": kw.get("detail")}
    monkeypatch.setattr(pas, "_bars", _bars)
    monkeypatch.setattr(pas, "_market_bars", _market_bars)
    monkeypatch.setattr(pas.cs, "_record", _record)
    monkeypatch.setattr(pas, "_no_history", _none)

    one = await P._prices_read(None, "AAPL", "volume", why=WHY)
    assert one["volume"]["value"] == 10_000_000.0 and one["as_of"] == "2026-09-10" and "close" not in one
    close = await P._prices_read(None, "AAPL", "close", date="2026-09-09", why=WHY)
    assert close["close"]["value"] == 109.0 and "adj_close" not in close
    series = await P._prices_read(None, "AAPL", "volume", window="1m", why=WHY)
    assert series["quantity"] == "AAPL.volume" and [p["value"] for p in series["points"]] == [8e6, 9e6, 1e7]
    assert series["unit_class"] == "count"
    assert (await P._prices_read(None, "SPY", "volume", window="1m", why=WHY))["error"] == "no_price_data"   # a factor: no volume
    facts, _ = fa.read_prices({"ticker": "AAPL", "field": "volume"}, one)
    assert "volume, AAPL, as of 2026-09-10: 10000000" in F.line(facts[0])
    schema = P.build_analyst_registry("market").get("prices_read").json_schema
    assert schema["required"] == ["ticker", "field", "why"] or set(schema["required"]) == {"ticker", "field", "why"}
