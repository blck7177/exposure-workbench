"""V24 phase B: the ledger's indices, offline, over the phase-0 fixtures' facts.

The gate's three lookups (G1 id, G2 kind, G3 number / identity / passage) are
exercised here against real facts, so phase C's gate is a client of a tested
ledger rather than a second place that decides what a token equals.
"""

from __future__ import annotations

import pytest

import tests.test_fact_adapters as A
from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L


def _facts(name: str) -> list[F.Fact]:
    tool, args = A.CASES[name]
    return fa.ADAPTERS[tool](args, A._load(name))[0]


@pytest.fixture(scope="module")
def led() -> L.Ledger:
    facts: list[F.Fact] = []
    for name in ("read_book_run_sections", "read_book_port", "compute_book_analysis", "read_fundamentals_flow",
                 "read_fundamentals_sheet", "read_filings_search", "compute_beta", "compute_op_rank",
                 "compute_price_drawdown", "compute_book_episodes", "read_prices_1y"):
        facts += _facts(name)
    return L.Ledger.of_facts(facts)


def test_step_entry_round_trips_through_facts_in(led):
    facts = _facts("read_fundamentals_sheet")
    entry = L.step_entry(facts)
    recs = L.facts_in([{"type": "run", "id": "run_x", "scope": ["issuer_exposures"]}, entry])
    assert [r["id"] for r in recs] == [f.id for f in facts]
    assert L.Ledger.of(recs).holds(facts[0].id)


def test_G1_G2_id_and_kind(led):
    fid = next(iter(led.by_id))
    assert led.holds(fid) and led.kind(fid) in F.KINDS
    assert not led.holds("f_000000000000") and led.kind("f_000000000000") is None
    assert any(led.kind(i) == F.PASSAGE for i in led.by_id)
    assert any(not led.standalone(i) for i in led.by_id), "book.analysis legs carry standalone=False"


def test_G3_number_exact_and_at_written_precision(led):
    weight = next(r for r in led.by_id.values() if r["measure"] == "issuer_exposures.weight" and r["subject"] == "MSFT")
    v = weight["value"]                                  # e.g. 0.16251671
    assert weight["id"] in led.resolve_number(f"{v}")
    assert weight["id"] in led.resolve_number(f"{v*100:.1f}%")          # "16.3%"
    assert weight["id"] in led.resolve_number(f"{v*100:.2f}%")          # "16.25%"
    assert weight["id"] in led.resolve_number(f"{v:.4f}")               # "0.1625"
    assert weight["id"] not in led.resolve_number("17.1%")


def test_G3_money_under_a_scale(led):
    mv = next(r for r in led.by_id.values() if r["measure"] == "issuer_exposures.market_value" and r["subject"] == "MSFT")
    v = mv["value"]                                       # 1785420.0
    assert mv["id"] in led.resolve_number(f"${v:,.0f}")
    assert mv["id"] in led.resolve_number(f"${v/1e6:.2f}M")
    assert mv["id"] in led.resolve_number(f"{v/1e6:.2f} million")
    assert mv["id"] in led.resolve_number(f"${v/1e6:.1f}m")


def test_G3_a_ratio_written_as_bare_percent_number(led):
    weight = next(r for r in led.by_id.values() if r["measure"] == "issuer_exposures.weight" and r["subject"] == "MSFT")
    assert weight["id"] in led.resolve_number(f"{weight['value']*100:.1f}")   # "16.3" — plainly a percentage
    # but a bare small number does not turn a count into a ratio
    assert led.resolve_number("0.5") == [] or all(led.by_id[i]["unit"] != "COUNT" for i in led.resolve_number("0.5"))


def test_G3_identity_fields(led):
    as_of = next(r["as_of"] for r in led.by_id.values() if r["measure"] == "issuer_exposures.weight")
    assert led.resolve_identity(as_of), "the run's as_of resolves"
    assert led.resolve_identity(as_of[:4]), "and its year"
    beta = next(r for r in led.by_id.values() if ".beta." in r["measure"] and r.get("params", {}).get("benchmark"))
    assert beta["id"] in led.resolve_identity(beta["params"]["benchmark"])
    dd = next(r for r in led.by_id.values() if r["params"].get("peak_date"))
    assert dd["id"] in led.resolve_identity(dd["params"]["peak_date"])
    win = next(r for r in led.by_id.values() if (r.get("window") or {}).get("name"))
    assert win["id"] in led.resolve_identity(win["window"]["name"])           # "1y"
    assert led.resolve_identity("this-is-not-a-token") == []


def test_G3_confidence_and_measure_digits():
    f = F.fact(F.SCALAR, "exposure_metrics.var_95_1d", subject="run_x", unit="RATIO", value=0.0123,
               as_of="2026-09-03", params={"confidence": 0.95})
    led = L.Ledger.of_facts([f])
    for tok in ("95", "95%", "1", "2026", "2026-09-03"):
        assert f.id in led.resolve_identity(tok), tok


def test_G3_passages(led):
    pid, text = next(iter(led.passages.items()))
    import re
    m = re.search(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(?![\d])", text)
    if m:
        assert pid in led.resolve_in_passages(m.group(1), [pid])
    assert led.resolve_in_passages("9999999", [pid]) == []
    assert led.resolve_in_passages("1", []) == []


def test_pre_v24_declarations_are_not_facts():
    assert L.facts_in([{"type": "run", "id": "run_abc", "scope": ["issuer_exposures"]}, {"type": "calc", "id": "calc_1"}]) == []


def test_a_bare_short_integer_cannot_borrow_a_source_from_a_passage(led):
    """A twelve-thousand-character filing contains nearly every one- and
    two-digit number. The 2026-09-05 battery linked a forecast the desk had
    invented ("low-20s percent") to a 10-K passage that happened to contain the
    digits 20. A figure a passage STATES carries its unit."""
    pid, text = next(iter(led.passages.items()))
    assert led.resolve_in_passages("20", [pid]) == []
    assert led.resolve_in_passages("7", [pid]) == []
    import re
    m = re.search(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s?(?:percent|%)", text)
    if m:
        assert led.resolve_in_passages(m.group(1) + "%", [pid]) == [pid], "a marked figure still resolves"
    m4 = re.search(r"(?<![\d.])(\d[\d,]{3,}(?:\.\d+)?)(?![\d])", text)
    if m4:
        assert led.resolve_in_passages(m4.group(1), [pid]) == [pid], "a long number needs no marker"


def test_the_day_and_month_of_a_date_are_not_identity_tokens():
    from exposure_workbench.services import facts as F
    f = F.fact(F.PASSAGE, "10-K Item 7", subject="LLY", text="…", as_of="2026-02-20",
               params={"form_type": "10-K", "filed": "2026-02-20"})
    led = L.Ledger.of_facts([f])
    assert led.resolve_identity("2026-02-20") and led.resolve_identity("2026")
    assert led.resolve_identity("20") == [] and led.resolve_identity("02") == []
    assert led.resolve_identity("10-K") and led.resolve_identity("10"), "a form name still gives its digits"
