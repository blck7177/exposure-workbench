"""V38 — the tool layer does what the program says, and says what it did
(docs/IMPLEMENTATION_PLAN_V38.md, offline).

Round C's tool-layer analysis (docs/spikes/v37/TOOLS_V37C.md) found the language
page, the digest and the services disagreeing about what a result holds. These
tests hold the surface and the service to one account.
"""
from __future__ import annotations

from exposure_workbench.analytics import resources, skill


# ── S5: the language page lists every figure a book method records ────────────

def _covers(yields: list[str], family: str, key: str) -> bool:
    name = f"{family}.{key}"
    return any(y == name or y.startswith(name + ".") or y.startswith(name + "[") for y in yields)


def test_every_figure_a_book_method_records_is_on_the_language_page():
    """`book.reconcile` recorded the factor sum and alpha-plus-residual and the
    page listed neither, so round C's sol Q18 reconciled with the only sum the
    page offered — the position sum — and said the book did not reconcile."""
    book_yields = [y for m in skill.METHODS.values() if m.subject_kind in ("run", "portfolio") for y in m.yields]
    missing = [f"{fam}.{key}" for fam, keys in resources.CALC_RESULTS.items() for key in keys
               if not _covers(book_yields, fam, key)]
    assert missing == [], f"recorded by a service and not offered on the page: {missing}"


def test_the_reconciliation_offers_both_sums():
    from exposure_workbench.services import program_service as ps
    text = ps.signature_text()
    line = next(l for l in text.splitlines() if l.strip().startswith("book.reconcile("))
    assert "portfolio.reconcile.sum_of_factor_contributions" in line
    assert "portfolio.reconcile.alpha_plus_residual" in line


# ── T3(d)(e)(f): a refusal says what failed, all of it ────────────────────────

def _type_report(problems):
    from exposure_workbench.services import digest as dg
    minter = dg.Minter()
    d = dg.render({"error": "type_errors", "problems": problems, "detail": "the program did not run"},
                  mint=minter, call={"tool": "run", "args": {}})
    (b,) = d["boundaries"]
    return b["text"]


def test_a_schema_refusal_names_the_field_and_the_shape():
    """sol Q13 seq13 read "book.buy: params do not fit the method's schema" and
    nothing else, and never fixed the buy."""
    from exposure_workbench.services import program_service as ps
    prog = {"let": [["book", {"fn": "run", "portfolio": "port_001"}],
                    ["after", {"fn": "method", "name": "book.buy", "subject": "$book",
                               "params": {"buys": [{"ticker": "TLT", "weight": 1.5}]}}]]}
    text = _type_report(ps.typecheck(prog))
    assert "buys.0.weight" in text and "1.5" in text
    assert "params take {buys: [{ticker: string, weight: number (0..1)}, …]}" in text


def test_every_type_problem_is_said_and_a_repeated_one_is_counted():
    problems = [{"at": f"n{i}", "reason": "type_mismatch", "fix": f"fix number {i}"} for i in range(5)]
    problems += [{"at": "n9", "reason": "type_mismatch", "fix": "same"}] * 3
    text = _type_report(problems)
    assert all(f"fix number {i}" in text for i in range(5)), text
    assert text.count("n9: same") == 1 and "(×3)" in text


def test_a_runtime_schema_refusal_names_the_field_too():
    from exposure_workbench.services import program_service as ps
    from exposure_workbench.tools.arg_validation import validate_args
    schema = skill.METHODS["book.buy"].params_schema
    r = ps._err("invalid_params", "book.buy: params do not fit the method's schema",
                problems=validate_args(schema, {"buys": [{"ticker": "TLT"}]}), params_schema=schema)
    text = ps._absence_text(ps.Node("after", ps.ABSENCE, None), r)
    assert "buys.0.weight" in text and "params take" in text


def test_the_collinear_refusal_ends_where_the_reader_can_act():
    """The sentence stopped at "their sum, X, is"."""
    import inspect
    from exposure_workbench.services import quantities as qn
    src = inspect.getsource(qn._from_run)
    assert "their sum, {total:.8f}, is\")" not in src
    assert "pick(of=$<the run>, key='factor_attributions.sum_of_contributions')" in src
