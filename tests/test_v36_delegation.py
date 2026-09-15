"""V36 Phase 1b — the protocol between the lead analyst and a domain analyst
(offline: no DB, no network, no LLM).

Two failures this boundary exists to catch, both invisible at the receiving end:
a brief that answers three of four lines reads exactly like one that answers
four, and a finding whose figures do not point at facts costs the lead its turn
rather than the analyst's. So coverage is counted and every figure is resolved
against the same ledger the answer check will read.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.analytics import skill
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger

DOMAINS = set(skill.PROCEDURES)
_n = [0]


def _id(prefix: str) -> str:
    _n[0] += 1
    return f"{prefix}{_n[0]:04d}"


def _task(**kw) -> dl.Task:
    base = dict(task_id="tsk_1", domain="book_limits_and_triggers", subjects=("port_001",),
                want_to_know=("which check is nearest its warning", "how much room is left"))
    return dl.Task(**{**base, **kw})


def _ledger(*facts) -> Ledger:
    return Ledger.of_facts(facts)


def _scalar(measure, subject, value, unit="RATIO", **params):
    return F.fact(F.SCALAR, measure, subject=subject, unit=unit, value=value,
                  as_of="2026-09-10", params=params or {"node": "n"})


# ── parse ────────────────────────────────────────────────────────────────────

def test_a_well_formed_delegation_becomes_tasks():
    tasks = dl.parse_tasks({"tasks": [{
        "domain": "book_limits_and_triggers", "subjects": ["port_001"],
        "want_to_know": ["which position is nearest its warning tier", "how much room is left to warning and breach"],
        "facts_to_derive": ["move to breach = room to breach over the name's weight"],
        "constraints": {"window": "latest", "compare": "ranked, nearest first"},
        "context": "the user is deciding whether to trim"}]}, DOMAINS, _id)
    t = tasks[0]
    assert (t.domain, t.subjects, t.window, t.compare) == (
        "book_limits_and_triggers", ("port_001",), "latest", "ranked, nearest first")
    assert len(t.want_to_know) == 2 and t.facts_to_derive and t.task_id.startswith("tsk_")


def test_the_numbered_lines_are_numbered_for_the_analyst():
    """The analyst answers BY NUMBER, so the numbering has to be the desk's, not
    something each model invents from a bare list."""
    t = _task()
    assert t.as_dict()["want_to_know"] == ["1. which check is nearest its warning", "2. how much room is left"]


@pytest.mark.parametrize("args, says", [
    ({}, "delegate takes"),
    ({"tasks": []}, "delegate takes"),
    ({"tasks": [{"domain": "no_such_domain", "subjects": ["x"], "want_to_know": ["y"]}]}, "not a domain on the ROSTER"),
    ({"tasks": [{"domain": "book_liquidity", "subjects": [], "want_to_know": ["y"]}]}, "names at least one"),
    ({"tasks": [{"domain": "book_liquidity", "subjects": ["port_001"], "want_to_know": []}]}, "non-empty list"),
    ({"tasks": [{"domain": "book_liquidity", "subjects": ["p"], "want_to_know": ["a"]},
                {"domain": "book_liquidity", "subjects": ["p"], "want_to_know": ["b"]}]}, "asked twice"),
])
def test_a_malformed_delegation_is_told_to_the_lead_in_words_it_can_act_on(args, says):
    with pytest.raises(dl.BadDelegation) as e:
        dl.parse_tasks(args, DOMAINS, _id)
    assert says in str(e.value)


def test_too_many_lines_is_more_than_one_task():
    with pytest.raises(dl.BadDelegation) as e:
        dl.parse_tasks({"tasks": [{"domain": "book_liquidity", "subjects": ["p"],
                                   "want_to_know": [f"line {i}" for i in range(dl.MAX_WANTS + 1)]}]}, DOMAINS, _id)
    assert "more than one task" in str(e.value)


# ── C1: coverage ─────────────────────────────────────────────────────────────

def test_a_line_with_no_finding_and_no_not_done_is_refused():
    """The failure this boundary exists for: three of four answered reads like
    four at the other end."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [f.id], "finding": f"MSFT reads 16.0% [{f.id}]."}], "not_done": []}
    v = dl.handoff_check(_task(), brief, {"text": "MSFT is the nearest."}, led)
    assert not v.ok
    assert [p["reason"] for p in v.problems if p["where"] == "coverage"] == ["uncovered_want"]
    assert v.problems[0]["want"] == 2 and "how much room is left" in v.problems[0]["line"]


def test_a_line_the_desk_could_not_settle_is_covered_by_not_done():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    b = F.fact(F.ABSENCE, "room", text="the desk holds no dollar market value for this run", as_of="n/a",
               params={"reason": "cannot", "class": "boundary"})
    led = _ledger(f, b)
    brief = {"findings": [{"want": 1, "facts": [f.id], "finding": f"MSFT reads 16.0% [{f.id}]."}],
             "not_done": [{"want": 2, "why": "the desk holds no dollar market value for this run", "boundary": b.id}]}
    v = dl.handoff_check(_task(), brief, {"text": f"MSFT reads 16.0% [{f.id}]."}, led)
    assert v.ok, v.problems
    assert v.coverage == {"asked": 2, "done": 1, "not_done": 1, "refused": 0}


def test_answering_a_line_the_task_does_not_have():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [], "finding": f"MSFT reads 16.0% [{f.id}]."},
                          {"want": 2, "facts": [], "finding": f"Room is 16.0% [{f.id}]."},
                          {"want": 7, "facts": [], "finding": f"Something else, 16.0% [{f.id}]."}]}
    v = dl.handoff_check(_task(), brief, {"text": "-"}, led)
    assert any(p["reason"] == "unknown_want" and p["want"] == 7 for p in v.problems)


# ── C2 / C3: the figures point ───────────────────────────────────────────────

def test_a_figure_that_points_at_the_wrong_fact_is_refused_before_the_lead_sees_it():
    """J round Q11, at the boundary that did not exist then: the analyst wrote a
    number it had subtracted in its head and hung the tier's id on it."""
    cur = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(cur)
    brief = {"findings": [{"want": 1, "facts": [cur.id], "finding": f"MSFT is 1.0% [{cur.id}] above warning."},
                          {"want": 2, "facts": [cur.id], "finding": f"It reads 16.0% [{cur.id}]."}]}
    v = dl.handoff_check(_task(), brief, {"text": f"It reads 16.0% [{cur.id}]."}, led)
    assert not v.ok
    assert [f["want"] for f in v.accepted] == [2]
    assert v.rejected[0]["want"] == 1
    assert any(p["reason"] == "mark_mismatch" for p in v.rejected[0]["problems"])


def test_a_finding_naming_an_id_the_ledger_does_not_hold():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [f.id, "f_invented"], "finding": f"MSFT reads 16.0% [{f.id}]."},
                          {"want": 2, "facts": [], "finding": f"Room follows from 16.0% [{f.id}]."}]}
    v = dl.handoff_check(_task(), brief, {"text": "-"}, led)
    assert any(p["reason"] == "not_on_ledger" and p.get("id") == "f_invented" for p in v.problems)


def test_a_number_the_lead_itself_asked_for_is_the_leads_to_repeat():
    """The lead's "over 8%" is the user's number, not the desk's; a finding that
    repeats it must not be refused for having no fact behind it."""
    w = _scalar("issuer_exposures.weight", "MSFT", 0.1604)
    led = _ledger(w)
    task = _task(want_to_know=("which issuers would be over an 8% single-issuer cap",))
    brief = {"findings": [{"want": 1, "facts": [w.id],
                           "finding": f"Over an 8% cap: MSFT at 16.0% [{w.id}]."}]}
    v = dl.handoff_check(task, brief, {"text": f"Over an 8% cap: MSFT at 16.0% [{w.id}]."}, led)
    assert v.ok, v.problems


def test_an_empty_finding_is_not_an_answer():
    led = _ledger(_scalar("x", "y", 1.0))
    brief = {"findings": [{"want": 1, "facts": [], "finding": "  "}],
             "not_done": [{"want": 2, "why": "nothing"}]}
    v = dl.handoff_check(_task(), brief, {"text": "-"}, led)
    assert any(p["reason"] == "empty_finding" for p in v.problems)


# ── C4 / C5 ──────────────────────────────────────────────────────────────────

def test_a_not_done_pointing_at_something_that_is_not_a_boundary():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [], "finding": f"MSFT reads 16.0% [{f.id}]."}],
             "not_done": [{"want": 2, "why": "could not", "boundary": f.id}]}
    v = dl.handoff_check(_task(), brief, {"text": "-"}, led)
    assert any(p["reason"] == "not_a_boundary" for p in v.problems)


def test_the_report_is_read_the_same_way_a_finding_is():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [], "finding": f"MSFT reads 16.0% [{f.id}]."}],
             "not_done": [{"want": 2, "why": "not asked"}]}
    v = dl.handoff_check(_task(), brief, {"text": "MSFT has 4.0% of room left."}, led)
    assert any(p["where"] == "report" for p in v.problems)
    assert v.report_verdict is not None and not v.report_verdict.ok


# ── the refusal, and what the lead reads ─────────────────────────────────────

def test_the_refusal_names_only_what_failed_and_what_to_do():
    cur = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(cur)
    brief = {"findings": [{"want": 1, "facts": [], "finding": f"MSFT is 1.0% [{cur.id}] above warning."}],
             "not_done": [{"want": 2, "why": "not reached"}]}
    v = dl.handoff_check(_task(), brief, {"text": f"MSFT reads 16.0% [{cur.id}]."}, led)
    msg = dl.refusal_message(_task(), v)
    assert "findings[0]" in msg and "mark_mismatch" in msg
    assert "Everything not named here is kept" in msg
    assert "not_done" in msg           # the way out for a line the desk cannot settle


def test_what_the_lead_reads_carries_the_line_each_finding_answers():
    task = _task()
    r = dl.AnalystResult(task=task, status="verified",
                         findings=[{"want": 2, "facts": ["f_a"], "finding": "Room is -1.0%.",
                                    "desk_said": [{"id": "f_b", "said": "rank(of=$room): no ordering"}]}],
                         coverage={"asked": 2, "done": 1, "not_done": 1, "refused": 0},
                         not_done=[{"want": 1, "why": "no ordering", "boundary": "f_b",
                                    "said": "rank(of=$room): no ordering"}], report_id="rep_1",
                         cost={"completions": 2})
    out = dl.for_lead([r])
    a = out["analysts"][0]
    assert a["domain"] == "book_limits_and_triggers" and a["report_id"] == "rep_1"
    assert a["findings"][0]["asked"] == "how much room is left"
    # V36.1: the desk's words ride beside the id, both ways they can be cited
    assert a["findings"][0]["desk_said"][0]["said"] == "rank(of=$room): no ordering"
    assert a["not_done"][0]["said"] == "rank(of=$room): no ordering"
    assert "read_report" in out["how_to_cite"] and "`said`" in out["how_to_cite"]


# ── the roster the lead picks from ───────────────────────────────────────────

def test_every_domain_says_what_it_can_be_asked_for():
    for entry in skill.roster():
        assert entry["offers"], entry["domain"]
        assert entry["absent"]
        assert all(len(o) > 20 for o in entry["offers"])


def test_the_roster_puts_the_matching_domains_first_and_still_lists_the_rest():
    r = skill.roster("how much room is left before the issuer-concentration check trips")
    assert r[0]["domain"] == "book_limits_and_triggers"
    assert len(r) == len(skill.PROCEDURES)


def test_the_roster_names_no_method_and_no_program():
    """The lead must not be able to write the desk's language from what it reads
    — that vocabulary is exactly what V35 handed it, and V33J Q11 is what came
    back."""
    text = str(skill.roster())
    # The identifiers, not the English. "the accruals ratio" is how a person
    # says it; `accruals_ratio` is something the lead could paste into a request,
    # and the lead having a request to paste it into is what V36 removed.
    for name in skill.METHODS:
        if "_" in name or "." in name:
            assert name not in text, f"the roster names the method {name}"
    assert '"let"' not in text and '"fn"' not in text and "'fn'" not in text


# ── what the smoke round found ───────────────────────────────────────────────

def test_a_line_cannot_be_both_answered_and_explained():
    """The first live round produced a brief with three findings and three
    not_done entries over the same three lines, and its coverage read 3 done and
    3 not done — a number saying two opposite things."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604)
    led = _ledger(f)
    brief = {"findings": [{"want": 1, "facts": [f.id], "finding": f"MSFT reads 16.0% [{f.id}]."},
                          {"want": 2, "facts": [f.id], "finding": f"Its tier reads 16.0% [{f.id}]."}],
             "not_done": [{"want": 1, "why": "the desk holds no ordering"},
                          {"want": 2, "why": "the desk holds no ordering"}]}
    v = dl.handoff_check(_task(), brief, {"text": f"MSFT reads 16.0% [{f.id}]."}, led)
    assert [p["reason"] for p in v.problems] == ["answered_and_explained"] * 2
    assert v.problems[0]["want"] == 1 and v.problems[0]["line"]
