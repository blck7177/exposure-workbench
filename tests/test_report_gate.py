"""V6 — the exposure report is gated (offline: no DB, no network, no LLM).

The last LLM surface that reached a user without passing a gate. Measured on the
live database before this batch: 19 stored reports, 9 of them the mock template,
served as reports — and the mock's disclaimer said the API key was not
configured, which was true for none of them.

The failure branches are tested one by one because they were not one bug. They
were four separate ways to return something shaped exactly like a report, and a
caller cannot tell that shape from a real one.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from exposure_workbench.agents.direct_llm_agent import DirectLlmAgent, ReportUnavailable
from exposure_workbench.agents.schemas import ReportInput
from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services.report_verification import ReportVerdict, _CHECKED_FIELDS
from exposure_workbench.services import table as tbl

GOOD = {
    "executive_summary": "s", "key_movements": "k", "factor_explanation": "f",
    "risk_alert_explanation": "r",
    "markdown_report": "# m",
}


def _agent_returning(payload, monkeypatch):
    """A DirectLlmAgent whose one completion returns `payload` as text."""
    from exposure_workbench.llm import client as llm_client

    monkeypatch.setattr(llm_client, "get_openai_client", lambda: object())

    async def _fake(**kwargs):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return text, "gpt-test", 10, 20

    monkeypatch.setattr(llm_client, "chat_complete", _fake)
    return DirectLlmAgent()


def _input() -> ReportInput:
    return ReportInput(portfolio_id="port_x", as_of_date="2026-08-20")


# ── every branch that used to fabricate a report now names its failure ─────────

async def test_a_valid_report_is_returned(monkeypatch):
    out = await _agent_returning(GOOD, monkeypatch).generate(_input())
    assert out.executive_summary == "s" and out.markdown_report == "# m"
    assert out.confidence_flags == {}, "no mock_mode flag left to mean anything"
    assert out.llm_model == "gpt-test"


async def test_no_llm_client_is_a_named_refusal_not_a_fabricated_report(monkeypatch):
    from exposure_workbench.llm import client as llm_client
    monkeypatch.setattr(llm_client, "get_openai_client", lambda: None)
    with pytest.raises(ReportUnavailable, match="no LLM client"):
        await DirectLlmAgent().generate(_input())


async def test_non_json_is_refused_rather_than_stored_as_the_report(monkeypatch):
    """It used to persist the raw text as markdown_report — the one field no UI
    renders — under an executive_summary reading "see full report for details"."""
    agent = _agent_returning("I'm afraid I can't do that.", monkeypatch)
    with pytest.raises(ReportUnavailable, match="did not return JSON"):
        await agent.generate(_input())


async def test_json_that_is_not_an_object_is_refused_with_the_right_reason(monkeypatch):
    """This is the branch that produced the false diagnosis. A list reached
    `data.get`, raised AttributeError, and landed in the bare `except Exception`
    that returned a mock saying the API key was not configured."""
    agent = _agent_returning(["a", "b"], monkeypatch)
    with pytest.raises(ReportUnavailable, match="not an object"):
        await agent.generate(_input())


async def test_a_missing_section_is_refused_not_silently_blank(monkeypatch):
    """`.get(k, "")` accepted a report missing five of its six sections and
    flagged it {"mock_mode": False} — clean."""
    agent = _agent_returning({**GOOD, "key_movements": "", "factor_explanation": None},
                             monkeypatch)
    with pytest.raises(ReportUnavailable) as e:
        await agent.generate(_input())
    msg = str(e.value)
    assert "key_movements" in msg and "factor_explanation" in msg


async def test_a_provider_error_is_refused_and_says_so(monkeypatch):
    from exposure_workbench.llm import client as llm_client
    monkeypatch.setattr(llm_client, "get_openai_client", lambda: object())

    async def _boom(**kwargs):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(llm_client, "chat_complete", _boom)
    with pytest.raises(ReportUnavailable, match="429 rate limited"):
        await DirectLlmAgent().generate(_input())


def test_the_mock_report_generator_is_gone():
    """Not "unused" — gone. A fabricated report that only a flag distinguishes
    from a real one is one refactor away from being persisted again."""
    import exposure_workbench.agents.direct_llm_agent as mod
    assert not hasattr(mod, "_mock_output")


# ── what the gate reads ────────────────────────────────────────────────────────

def test_the_gate_reads_every_field_a_reader_can_see():
    """markdown_report included: no UI renders it today, but the API serves it,
    so a number wrong only there is still a number this system published.

    Pinned to the agent's own required set rather than a dict kept here, so the
    two ends cannot drift: a field the prompt starts requesting is a field the
    gate must check, in the same commit. recommended_actions left both sets in
    V13-S7 when the prompt stopped asking for verdicts.
    """
    from exposure_workbench.agents.direct_llm_agent import _REQUIRED_FIELDS
    assert set(_CHECKED_FIELDS) == set(_REQUIRED_FIELDS) == set(GOOD)


def test_a_verdict_bounds_what_it_writes_into_the_timeline():
    """A wholly hallucinated report would otherwise put its entire number set in
    a step payload."""
    v = ReportVerdict(accepted=False, checked=40,
                      problems=[{"number": f"{i}%", "nearest": None} for i in range(40)])
    payload = v.as_payload()
    assert payload["numbers_checked"] == 40 and payload["numbers_unverified"] == 40
    assert len(payload["unverified"]) == 10


# ── the report's own boilerplate must not fail its own gate ───────────────────

def test_a_window_label_written_the_short_way_is_not_a_claim():
    """"30d Annualised Vol" is the exposure report's own heading. The duration
    exemption required a separator and a spelled-out unit, so every report
    carried a guaranteed false rejection of the label in its volatility line."""
    keys = {n.key for n in nv.extract_numbers("30d Annualised Vol: 13.56%")}
    assert "13.56" in keys
    assert "30" not in keys


def test_a_confidence_level_is_a_parameter_not_a_measurement():
    for text in ("1-day 95% VaR: 1.41%", "VaR (95%, 1d) is 1.41%"):
        keys = {n.key for n in nv.extract_numbers(text)}
        assert "1.41" in keys, text
        assert "95" not in keys, text


def test_a_bare_percentage_elsewhere_is_still_a_claim():
    """The exemption is narrow on purpose: 95% of anything else must be checked."""
    keys = {n.key for n in nv.extract_numbers("Technology is 95% of the book")}
    assert "95" in keys


def test_a_plain_number_of_days_is_still_a_claim():
    keys = {n.key for n in nv.extract_numbers("The book held 30 positions")}
    assert "30" in keys


# ── the table has one definition of an id ─────────────────────────────────────

def test_an_object_shaped_result_cannot_smuggle_a_malformed_id():
    """Caught live, one row. list_alerts returns {"id": ..., "type": alert_type},
    so `alertb41eec529430` — no underscore, from before the prefix fix — was
    harvested under ref_type "issuer_concentration", which is an alert type and
    not an evidence type. It could never be cited, resolved or valued. The
    declaration (V15-S2a) keys on the id's own prefix and nothing else."""
    refs = tbl.declare({"alerts": [
        {"id": "alertb41eec529430", "type": "issuer_concentration"},
        {"id": "alert_1a2b3c4d5e6f", "type": "issuer_concentration"}]})["evidence"]
    ids = {r["id"] for r in refs}
    assert "alert_1a2b3c4d5e6f" in ids
    assert "alertb41eec529430" not in ids
    assert not any(r["type"] == "issuer_concentration" for r in refs)


def test_a_key_named_calc_id_does_not_make_its_value_an_id():
    """The second bypass trusted the KEY's name rather than the id."""
    refs = tbl.declare({"calc_id": "not-an-id", "fact_id": "fact_abc123"})["evidence"]
    ids = {r["id"] for r in refs}
    assert "fact_abc123" in ids
    assert "not-an-id" not in ids
