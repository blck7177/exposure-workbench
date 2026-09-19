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


# ── K5: the sign of a net beta, said as the code computes it ──────────────────

def test_the_net_beta_sign_the_desk_states_is_the_sign_it_computes():
    """Round C: the skill said "TLT and HYG enter with the sign opposite", the
    code enters SPY, QQQ and IWM that way too, and mini read net_beta.equity_down
    of −0.86 as a book short the market (it is long). The words and the table
    are held together here: a factor added to _RISK_SENSE must be named."""
    from exposure_workbench.analytics import integration
    procedure = skill.METHODS["book.analysis"].procedure
    reading = skill.READINGS["book.analysis"].reads
    desk = " ".join(skill.PROCEDURES["book_market_risk"].desk)
    for ticker, (risk, sense) in integration._RISK_SENSE.items():
        assert ticker in procedure and risk in procedure, (ticker, risk)
        assert sense == -1.0, "a factor entering with +1 needs its own sentence"
    for text in (reading, desk):
        assert "below zero" in text and "long equities" in text.lower()
        assert "TLT and HYG enter with the sign opposite" not in text


# ── T1: a program shows what its `return` names ───────────────────────────────

def _program_result(facts, returns, nodes):
    from exposure_workbench.services import facts as F
    return {"program_id": "calc_p", "returns": returns, "nodes": nodes, "settled": len(nodes), "refused": [],
            "_facts": [F.for_record(f) for f in facts]}


def _sc(measure, subject, value, node, **params):
    from exposure_workbench.services import facts as F
    return F.fact(F.SCALAR, measure, subject=subject, unit="RATIO", value=value, as_of="2026-09-10",
                  params={"node": node, **params})


def test_round_c_q08_the_returned_scalars_are_shown_and_the_tables_are_counted():
    """mini Q08 seq24 returned two scalars; the program's two 48-row analysis tables
    came first, the cap stopped at 65 facts, and both scalars were held back."""
    from exposure_workbench.services import fact_adapters as fa, facts as F
    tables = [_sc("portfolio.integration.room_to_warning", f"check_{i}", i / 100, node)
              for node in ("analysis_latest", "analysis_prev") for i in range(48)]
    refused = F.fact(F.ABSENCE, "gross_after", text="gross_after was not computed — no_sector: TLT has no sector",
                     as_of="n/a", params={"node": "gross_after", "error": "no_sector"})
    latest = _sc("portfolio.integration.net_beta.equity_down", "run_latest", -0.8599, "latest_exposure")
    prev = _sc("portfolio.integration.net_beta.equity_down", "run_prev", -0.8574, "prev_exposure")
    nodes = {n: {"kind": k} for n, k in (("analysis_latest", "table"), ("analysis_prev", "table"),
                                         ("gross_after", "absence"), ("latest_exposure", "scalar"),
                                         ("prev_exposure", "scalar"))}
    kept, note, held, made = fa.adapt_all("run", {}, _program_result(tables + [refused, latest, prev],
                                                                     ["latest_exposure", "prev_exposure"], nodes))
    assert [f.id for f in kept] == [refused.id, latest.id, prev.id], "the named nodes, and every refusal"
    assert held is None
    assert note["not_returned"] == {"analysis_latest": 48, "analysis_prev": 48}
    assert len(made) == 99, "every fact is still made for the ledger"


def test_a_returned_node_too_large_to_show_is_held_back_by_name():
    from exposure_workbench.services import fact_adapters as fa, facts as F
    wide = [_sc("issuer_exposures.weight", f"T{i:03d}", i / 1000, "w", label=f"T{i:03d}")
            for i in range(F.FACTS_PER_RESULT + 30)]
    kept, note, held, made = fa.adapt_all("run", {}, _program_result(wide, ["w"], {"w": {"kind": "vector"}}))
    assert held["nodes"] == {"w": held["count"]} and held["count"] == len(wide) - len(kept)
    assert "pick(of=$node" in held["how"]


def test_a_program_with_no_return_shows_its_own_bindings_not_the_hoisted_ones():
    from exposure_workbench.services import fact_adapters as fa
    mine = _sc("issuer_exposures.weight", "MSFT", 0.16, "ranked", rank=1)
    hoisted = _sc("issuer_exposures.weight", "MSFT", 0.16, "_ranked_1")
    kept, note, _, _ = fa.adapt_all("run", {}, _program_result([hoisted, mine], ["ranked"],
                                                               {"_ranked_1": {"kind": "vector"},
                                                                "ranked": {"kind": "ranking"}}))
    assert [f.id for f in kept] == [mine.id] and note["not_returned"] == {"_ranked_1": 1}


# ── T2: a refusal is never capped, and is said once ───────────────────────────

def test_the_cap_never_holds_back_a_refusal():
    from exposure_workbench.services import facts as F
    figures = [F.fact(F.SCALAR, f"m{i}", subject="X", unit="RATIO", value=float(i), as_of="2026-01-01")
               for i in range(300)]
    refusals = [F.fact(F.ABSENCE, f"n{i}", text=f"n{i} was not computed — no_sector: TLT", as_of="n/a")
                for i in range(40)]
    kept, held = F.cap(figures + refusals, per_result=200)
    assert sum(1 for f in kept if f.kind == F.ABSENCE) == 40 and held["count"] == 100
    kept2, held2 = F.cap(figures[:50] + refusals, char_limit=2_000)
    assert sum(1 for f in kept2 if f.kind == F.ABSENCE) == 40 and held2


def _render(res, **kw):
    from exposure_workbench.services import digest as dg
    minter = dg.Minter()
    return dg.render(res, mint=minter, **kw), minter


def _rows(*facts):
    from exposure_workbench.services import facts as F
    return {"columns": list(F.COLUMNS), "rows": [F.row_for_model(f) for f in facts]}


def test_refusals_that_follow_one_root_are_said_once_under_it():
    """sol Q13 seq4: one `no_sector` stopped twenty nodes, and the analyst would
    have read the same sentence twenty times — had any of them been shown."""
    from exposure_workbench.services import facts as F
    root = F.fact(F.ABSENCE, "after", text="after was not computed — no_sector: TLT has no sector on this desk",
                  as_of="n/a", params={"node": "after", "error": "no_sector"})
    deps = [F.fact(F.ABSENCE, n, text=f"{n} was not computed: after was refused — no_sector: TLT has no sector",
                   as_of="n/a", params={"node": n, "error": "depends_on_refused",
                                        "root": {"node": "after", "error": "no_sector"}})
            for n in ("after_mv", "after_tlt_w", "_after_tlt_w_3", "change_gross")]
    nodes = {"after": {"kind": "absence"}, "after_mv": {"kind": "absence"}, "after_tlt_w": {"kind": "absence"},
             "_after_tlt_w_3": {"kind": "absence"}, "change_gross": {"kind": "absence"}, "sold": {"kind": "table"}}
    d, _ = _render({"facts": _rows(root, *deps), "nodes": nodes})
    (b,) = d["boundaries"]
    assert b["fact"] == root.id and b["code"] == "no_sector"
    assert b["blocks"] == ["after_mv", "after_tlt_w", "change_gross"]
    kinds = {e["name"]: e for e in d["nodes"]}
    assert kinds["after_tlt_w"] == {"name": "after_tlt_w", "kind": "refused", "boundary": root.id}
    assert "_after_tlt_w_3" not in kinds and kinds["sold"]["kind"] == "table"


# ── T3: what the tool already said reaches the analyst ────────────────────────

def test_a_composed_total_says_what_it_was_made_of():
    """sol Q02: XOM's "total debt" was its current debt alone, and fcf_to_debt read
    254%; V37/S1 wrote the cover's leftovers on the node's note, which the digest
    does not read."""
    from datetime import date
    from exposure_workbench.services import formula_service as fs_, program_service as ps, typed_calculator as tc
    cover = {"id": "calc_td", "value": 9.3e9, "formula": "debt_current_total",
             "no_facts_for_issuer": ["long_term_debt_total", "long_term_debt_noncurrent"]}
    made_of = fs_._made_of(("free_cash_flow", "total_debt"), [{"id": "calc_f", "value": 2.4e10}, cover], {})
    assert made_of == {"total_debt": {"formula": "debt_current_total",
                                      "no_facts_for_issuer": ["long_term_debt_total", "long_term_debt_noncurrent"]}}
    nested = fs_._made_of(("net_debt", "ebitda"), [{"id": "c", "value": 1.0, "made_of": made_of}, {"id": "e", "value": 2.0}], {})
    assert nested == made_of, "a nested formula carries its composition up"
    node = ps.Node("fcf_support", ps.SCALAR, None, ref="calc_r",
                   typed=tc.Typed(value=2.54, unit_class="ratio", instant=date(2025, 12, 31), quantity="fcf_to_debt",
                                  issuers=("XOM",)),
                   payload={"value": 2.54, "made_of": made_of})
    (fact,) = ps._facts_of(node)
    assert fact.params["made_of"] == made_of
    d, _ = _render({"facts": _rows(fact), "nodes": {"fcf_support": {"kind": "scalar"}}})
    assert d["figures"][0]["made_of"] == made_of


def test_an_entry_a_method_could_not_compute_is_a_refusal():
    """sol Q12 seq22: roe over [JPM, GS] showed JPM and said nothing of GS."""
    from datetime import date
    from exposure_workbench.services import program_service as ps
    node = ps.Node("roe_by_bank", ps.VECTOR, None, measure="roe", ref="calc_jpm",
                   entries=[("JPM", "calc_jpm", 0.162, "RATIO")],
                   payload={"method": "roe", "subjects": ["JPM", "GS"],
                            "refused": [{"subject": "GS", "error": "series_not_derivable", "detail": "GS files no net_income"}]})
    facts = ps._facts_of(node)
    (refusal,) = [f for f in facts if f.kind == "absence"]
    assert refusal.subject == "GS" and "roe_by_bank[GS] was not computed — series_not_derivable" in refusal.text
    d, _ = _render({"facts": _rows(*facts), "nodes": {"roe_by_bank": {"kind": "vector"}}})
    (b,) = d["boundaries"]
    assert (b["node"], b["subject"], b["code"]) == ("roe_by_bank", "GS", "series_not_derivable")


def test_a_picked_date_is_shown_with_the_node_that_used_it():
    """sol Q14 seq10 returned `peak` and `trough` and read no date at all."""
    nodes = {"episodes": {"kind": "table"},
             "peak": {"kind": "literal", "value": "2026-01-07", "deps": ["episodes"]},
             "_explain_trough_2": {"kind": "literal", "value": "2026-03-27", "deps": ["episodes"]},
             "explain": {"kind": "table", "deps": ["peak", "_explain_trough_2"]},
             "book": {"kind": "run", "run": "run_e2945c5ebd5a", "portfolio": "port_001"}}
    d, _ = _render({"facts": _rows(), "nodes": nodes, "not_returned": {"episodes": 4}})
    by = {e["name"]: e for e in d["nodes"]}
    assert by["peak"] == {"name": "peak", "kind": "literal", "value": "2026-01-07", "used_by": ["explain"]}
    assert by["_explain_trough_2"]["value"] == "2026-03-27"
    assert by["book"] == {"name": "book", "kind": "run", "run": "run_e2945c5ebd5a"}
    assert by["episodes"]["figures"] == 4 and by["episodes"]["shown"] is False
