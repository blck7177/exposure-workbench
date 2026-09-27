"""V1 step 6 (docs/IMPLEMENTATION_PLAN_V1.md §2.5, §3 步骤 6, §6): the style guide is written
ONCE, both role texts include it once, and a refusal names the rule by number.

The acceptance is a count: each rule's key phrase appears exactly once in EVERYTHING one reader
is sent — its role text, its blocks, its tools' descriptions and schemas, its handbook chapter,
and every refusal, repair and nudge a loop or a check can say to it (read off the source, the way
the wording sheet reads it). A second copy is somebody doing validation's work.

The research brief is not read here: it writes claims with placeholders, not prose with brackets,
under a gate of its own (services/claims) — whether it joins the desk's one flow is an open decision
of the plan (§5), and until then its role text is not the style guide's reader.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.agents import meta_agent, repeats, sub_analyst as sa
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.services import answer_check as AC
from exposure_workbench.services import facts as F
from exposure_workbench.services import style_guide as SG
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.tools import primitives as P

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("v1_wording", ROOT / "scripts" / "v1_wording.py")
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)


def _descriptions(schema) -> list[str]:
    out = []
    if isinstance(schema, dict):
        out += [schema["description"]] if isinstance(schema.get("description"), str) else []
        for v in schema.values():
            out += _descriptions(v)
    elif isinstance(schema, list):
        for v in schema:
            out += _descriptions(v)
    return out


# what the two checks can say to anybody
_CHECKS = [AC._SHORT_BARE, *W.said_under_keys(AC, keys=("way_out",)), *W.said_under_keys(dl, "handoff_check", keys=("way_out",))]


def _lead_reads() -> str:
    return "\n".join([
        meta_agent._SYSTEM, meta_agent.BRIEFING_TAG, meta_agent.ROSTER_TAG, meta_agent.READINGS_TAG,
        json.dumps(handbook.roster(), ensure_ascii=False), handbook.meaning_layer(),
        json.dumps([dl.ASK_TOOL, dl.OPEN_TOOL, meta_agent.REPAIR_TOOL], ensure_ascii=False),
        meta_agent._WRITE_OR_ASK, meta_agent._REPAIR_ONLY,
        *W.said_in(meta_agent, "_refusal_message"), *W.said_under_keys(meta_agent, "handle_message"),
        *W.said_in(repeats, "nudge"), *_CHECKS])


def _analyst_reads(analyst: str) -> str:
    tools = P.build_analyst_registry(analyst).tools.values()
    return "\n".join([
        sa.system_text(analyst), sa.TASK_TAG, sa.COVERAGE_TAG, sa._WRITE_OR_ASK, sa._BUDGET_STOP,
        *[t.description for t in tools], *[d for t in tools for d in _descriptions(t.json_schema)],
        json.dumps(dl.SUBMIT_TOOL, ensure_ascii=False),
        *W.said_in(dl, "refusal_message"), *W.said_in(dl, "parse_submission"), *W.said_under_keys(sa, "_run"), *_CHECKS])


READERS = {"lead": _lead_reads, **{a: (lambda a=a: _analyst_reads(a)) for a in handbook.ANALYSTS}}


def test_the_guide_is_eight_rules_numbered_in_order():
    assert [r.n for r in SG.RULES] == list(range(1, 9))
    assert all(r.key in r.text for r in SG.RULES), "a rule's key phrase is a phrase OF the rule"
    assert SG.text().count("\n") == 9                        # the head's two lines and the eight rules


@pytest.mark.parametrize("reader", READERS)
def test_a_role_text_includes_the_guide_once_and_whole(reader):
    assert READERS[reader]().count(SG.text()) == 1


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("rule", SG.RULES, ids=lambda r: f"rule{r.n}")
def test_a_rules_key_phrase_is_said_once_in_everything_a_reader_is_sent(reader, rule):
    text = READERS[reader]()
    assert text.count(rule.key) == 1, f"{reader}: {rule.key!r} is said {text.count(rule.key)} times"
    assert rule.key not in text.replace(SG.text(), ""), "…and the one place is the style guide"


def test_the_role_texts_no_longer_say_the_rules_in_words_of_their_own():
    """The sentences step 6 took out of the two roles and the submit schema, by the words they used."""
    gone = ("in brackets", "in your head", "never an estimate", "nearby figure", "superlative", "uotation marks",
            "exactly as", "stated without")
    for text in (meta_agent._ROLE, sa._SYSTEM, json.dumps(dl.SUBMIT_TOOL)):
        assert not [g for g in gone if g in text]
    # what the desk never writes is POLICY, rendered once into each chapter and the lead's readings
    never = "never a nearby figure under the asked-for name, never an estimate"
    for reader in READERS:
        assert READERS[reader]().count(never) == 1


def _reasons_the_answer_check_speaks() -> set[str]:
    return {line[1:line.index("]")] for line in W.said_under_keys(AC, keys=("way_out",)) if line.startswith("[")}


def test_every_reason_the_answer_check_speaks_enforces_a_numbered_rule():
    reasons = _reasons_the_answer_check_speaks()
    assert len(reasons) >= 15 and not [r for r in reasons if SG.rule_of(r) not in range(1, 9)]
    assert {SG.rule_of(r) for r in reasons} == {1, 2, 3, 4, 5, 6, 8}           # the seventh is the handoff's
    assert SG.rule_of("caveat_without_a_line") == 7
    # a problem about the SHAPE of a brief carries no rule
    assert [SG.rule_of(r) for r in ("uncovered_line", "unknown_line", "not_a_boundary")] == [None, None, None]


WEIGHT = F.Fact(id="f_w1a2b3c4d5e6", kind=F.SCALAR, measure="issuer_exposures.weight", subject="MSFT", unit="RATIO",
                value=0.16, as_of="2026-09-10")


def test_a_refused_sentence_is_told_the_rule_by_number_and_the_way_out():
    v = AC.check("MSFT is 23.4% of the book.", Ledger.of_facts([WEIGHT]))
    (p,) = v.problems
    assert (p["reason"], p["rule"]) == ("unsourced_figure", 1) and p["way_out"] and "fix" not in p
    assert v.failed[0]["problems"][0]["rule"] == 1                               # the sentence's own list holds the same problem
    said = meta_agent._refusal_message(v)
    assert "rule 1 — unsourced_figure ('23.4%')" in said and "Ask for the evidence you lack" in said
    assert "Delegate" not in said and "delegate" not in said                      # the lead's verb is `ask`
    assert "rule 1 — unsourced_figure" in v.detail


def test_a_refused_brief_is_told_the_rule_where_there_is_one():
    task = dl.Task(task_id="tsk_1", analyst="risk", subjects=("port_001",), lines=("how large is MSFT", "and AAPL"))
    brief = dl.parse_submission({"lines": [{"n": 1, "settled": True, "finding": "MSFT is 23.4% of the book.",
                                            "facts": ["f_w1a2b3c4d5e6"]}],
                                 "caveats": [{"line": 7, "text": "as of the prior run"}]})
    v = dl.handoff_check(task, brief, Ledger.of_facts([WEIGHT]))
    by_reason = {p["reason"]: p for p in v.problems}
    assert by_reason["unsourced_figure"]["rule"] == 1 and by_reason["caveat_without_a_line"]["rule"] == 7
    assert "rule" not in by_reason["uncovered_line"] and all(p.get("way_out") for p in v.problems)
    said = dl.refusal_message(task, v)
    assert "[line 1] rule 1 — unsourced_figure" in said and "[coverage] uncovered_line" in said
    assert "[caveats[0]] rule 7 — caveat_without_a_line" in said


def test_what_a_rows_word_means_is_the_handbooks_and_the_refusal_only_says_the_row():
    """The answer check taught "a book that loses to this risk is long it" inside a refusal, after
    the mistake. What a word means is a reading (registry.READS); the way out says what the row says."""
    net = F.Fact(id="f_3a9c", kind=F.SCALAR, measure="portfolio.integration.net_beta.equity_down", subject="run_1",
                 unit="MULTIPLE", value=-0.86, as_of="2026-09-10", means={"direction": "loses"})
    v = AC.check("The book is net short equities, with a net beta of -0.86× [f_3a9c].", Ledger.of_facts([net]))
    (p,) = [p for p in v.problems if p["reason"] == "sense_conflict"]
    assert p["rule"] == 6 and "the row says the book loses if this risk happens" in p["way_out"]
    assert " long " not in p["way_out"] and " short " not in p["way_out"]
    reading = "A book that loses if the risk happens is long the exposure it names"
    assert reading in registry.READS["book.analysis"]
    assert handbook.chapter_text("risk").count(reading) == 1 and handbook.meaning_layer().count(reading) == 1
