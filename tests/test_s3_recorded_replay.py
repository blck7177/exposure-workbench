"""Replay S2_mini recorded evidence/submissions without a provider or database.

This does not measure live answer correctness. Producer checks prevent new bad
arithmetic; the legacy X07 answer still needs a semantic completeness eval.
"""
import gzip
import json
from pathlib import Path

import pytest

from exposure_workbench.agents.handoff import Submission
from exposure_workbench.services import answer_check, ledger as ledger_svc, typed_calculator as tc
from exposure_workbench.services.ledger import Ledger

CASES = json.loads(gzip.decompress((Path(__file__).parent / "data/s2_mini_regressions.json.gz").read_bytes()))["cases"]


def test_recorded_q16_rates_beta_cannot_be_labelled_spy():
    case = CASES["Q16"]
    answer = json.loads([s for s in case["steps"] if s["step_type"] == "answer"][-1]["args"])["text"]
    verdict = answer_check.check(answer, Ledger.of(case["facts"]), question=case["question"])
    assert not verdict.ok
    assert "benchmark_mismatch" in {p["reason"] for p in verdict.problems}


def test_recorded_q19_wrong_year_share_cannot_borrow_guidance_digits():
    case = CASES["Q19"]
    rows = [r for r in case["facts"] if r["id"] in ("f_0e919a8b0c7a", "f_9041be7889e5")]
    text = json.loads(next(s for s in case["steps"] if s["step_type"] == "answer")["args"])["text"].split(". So the mix")[0] + "."
    led = Ledger.of(rows)
    assert led.resolve_in_passages("16%", ["f_9041be7889e5"]) == []
    assert not answer_check.check(text, led, question=case["question"]).ok


def test_recorded_x01_revised_note_can_finish_without_old_identity():
    case = CASES["X01"]
    payloads = [json.loads(s["args"])["submission"] for s in case["steps"]
                if s["step_type"] == "brief" and s["actor"] == "sub:issuer"]
    sub = Submission()
    led = Ledger.of(case["facts"])
    assert not sub.apply(payloads[0], led, case["question"])["accepted"]
    assert sub.apply(payloads[1], led, case["question"])["accepted"]


async def test_recorded_x07_rejects_mismatched_drawdown_at_calculation_boundary(monkeypatch):
    records = {r["id"]: r for r in CASES["X07"]["facts"]}
    async def record(db, fid):
        return records[fid]
    monkeypatch.setattr(ledger_svc, "record", record)
    position = await tc._resolve_fact_ref(None, "f_0c45a08fe6e3")
    book = await tc._resolve_fact_ref(None, "f_708fc3a161aa")
    stock = await tc._resolve_fact_ref(None, "f_a1139502f62c")
    assert tc._check("multiply", position, book)["error"] == "subject_mismatch"
    assert tc._check("multiply", position, stock) is None
    assert position.value * stock.value == pytest.approx(88280.38496174205)
    assert records["f_a3537195b26e"]["value"] * stock.value * 100 == pytest.approx(.8215238562551929)
