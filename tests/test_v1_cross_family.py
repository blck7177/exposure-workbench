"""V1 step 7, the cross-family series: questions whose second half depends on what the first half
FOUND, and the instrument that reads what crossed the lead between two analysts.

An analyst reaches one family of evidence (tools/faces), so "the largest holding — and that
company's cash" is two asks with the lead in between. The twenty questions of the measured rounds
span families too, but the user spells every half out, so the lead can take them apart before
anything comes back; whether a finding survives the trip through the lead — and what the trip
costs — is not something they isolate. `docs/spikes/v1/questions_cross_family.json` does: one
dependency a question, every direction between the three families once, one join of two families'
FIGURES, and one dependency cut across two turns. `scripts/battery_counters.py` reads a round for
the asks in order and what became of each handoff; `scripts/v36_forensics.py` prints what went
down and what came back in full, because that is what such a round is read by.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
from pathlib import Path

import pytest

from exposure_workbench.analytics import registry as desk
from exposure_workbench.tools import primitives as P

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "docs" / "spikes" / "v1" / "questions_cross_family.json"
TWENTY = ROOT / "docs" / "spikes" / "v33" / "questions_v33.json"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _script("battery_counters")


# ── the questions ────────────────────────────────────────────────────────────

def _questions() -> list[dict]:
    return json.loads(QUESTIONS.read_text())


def test_the_file_is_what_the_battery_reads_and_the_twenty_are_untouched():
    qs = _questions()
    assert all(isinstance(q["tag"], str) and q["turns"] and all(isinstance(t, str) and t.strip() for t in q["turns"]) for q in qs)
    tags = [q["tag"] for q in qs]
    assert len(set(tags)) == len(tags)
    # a series of its own: the twenty stay the twenty, so round E reads against round C question for question
    twenty = json.loads(TWENTY.read_text())
    assert len(twenty) == 20 and not {q["tag"] for q in twenty} & set(tags)
    assert all(t.startswith("X") for t in tags) and all(q["tag"].startswith("Q") for q in twenty)


def test_every_direction_between_the_three_families_is_asked_once():
    named = [(q["handoff"]["from"], q["handoff"]["to"]) for q in _questions() if q["handoff"]["kind"] == "name"]
    assert sorted(named) == sorted(itertools.permutations(P.FACES, 2))
    kinds = [q["handoff"]["kind"] for q in _questions()]
    assert kinds.count("figure") == 1 and kinds.count("name_across_turns") == 1


def test_a_handoff_says_what_a_counter_can_read():
    for q in _questions():
        h = q["handoff"]
        assert h["kind"] in ("name", "figure", "name_across_turns") and h["fixture"].strip()
        if h["kind"] == "figure":
            assert set(h["from"]) <= set(P.FACES) and len(h["from"]) == 2 and len(q["turns"]) == 1
            continue
        assert h["from"] in P.FACES and h["to"] in P.FACES and h["from"] != h["to"]
        assert len(q["turns"]) == (2 if h["kind"] == "name_across_turns" else 1)
        # what is carried is ONE of the candidates, each under its ticker first and its name after
        assert len(h["carries"]) == 1 and h["carries"][0] in h["among"] and len(h["among"]) >= 3
        assert all(c[0].isupper() and len(c) >= 2 for c in h["among"])


def test_the_question_does_not_give_the_finding_away():
    """The dependency is real only if the name comes from the desk: a question that says which company
    it means hands the second analyst its subject with no finding in between. Where the candidates are
    named (X02, X04) the found one is one of several, under no mark of its own."""
    for q in _questions():
        h = q["handoff"]
        if h["kind"] == "figure":
            continue
        text = " ".join(q["turns"])
        named = [c for c in h["among"] if any(re.search(rf"\b{re.escape(s)}\b", text, re.I) for s in c)]
        assert not named or (len(named) == len(h["among"]) >= 3), (q["tag"], named)


def test_a_question_is_the_users_and_holds_none_of_the_desks_vocabulary():
    verbs = {v for face in P.FACES for v in P.FACE_TOOLS[face]} - {"list", "start", "metric", "calc", "scenario"}
    keys = [k for k in desk.METHODS if "_" in k or "." in k]
    for q in _questions():
        text = " ".join(q["turns"])
        assert not [v for v in verbs if re.search(rf"(?<![\w.]){v}(?![\w.])", text)], q["tag"]
        assert not [k for k in keys if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", text)], q["tag"]
        assert not re.search(r"\b(?:analyst|risk manager|f_[0-9a-f]+|port_\w+|run_\w+)\b", text), q["tag"]


# ── the instrument ───────────────────────────────────────────────────────────

def _ask(*tasks: dict, status="completed") -> dict:
    """A `delegate` step as the battery stores it: the summary, and `args` as text."""
    full = [{"task_id": f"tsk_{i}", "analyst": t["analyst"], "subjects": t["subjects"],
             "lines": [f"{n}. {w}" for n, w in enumerate(t.get("lines") or ["what it shows"], 1)],
             **({"context": t["context"]} if t.get("context") else {}),
             **({"follow_up_of": t["follow_up_of"]} if t.get("follow_up_of") else {})} for i, t in enumerate(tasks)]
    return {"step_type": "delegate", "tool_name": "ask", "actor": None, "status": status,
            "result": "; ".join(f"{t['analyst']} [{','.join(t['subjects'])}] {len(t['lines'])} line(s)" for t in full),
            "args": json.dumps({"tasks": full})}


def _pull(analyst: str, verb: str, **args) -> dict:
    return {"step_type": "tool_call", "tool_name": verb, "actor": f"sub:{analyst}", "status": "completed",
            "result": f"r_1 {verb}(…) → 1 row", "args": json.dumps({**args, "why": f"line 1, said differently each time {len(args)}"})}


def _report(analyst: str) -> dict:
    return {"step_type": "report", "tool_name": "report", "actor": f"sub:{analyst}", "status": "completed", "result": "verified"}


def _turn(*steps: dict, delegations=(), n=1, answer="completed") -> dict:
    return {"turn": n, "answer": "x", "elapsed_s": 30.0,
            "steps": [{"step_type": "llm_call", "actor": None, "status": "completed", "prompt_tokens": 5000}, *steps,
                      {"step_type": "answer", "tool_name": "answer", "actor": None, "status": answer, "result": "accepted"}],
            "meta": {"delegations": [{"domain": a, "status": "settled", "coverage": {"asked": k, "settled": s, "unsettled": k - s, "refused": 0},
                                      "cost": {"completions": 3, "evidence_calls": e, "starts": 0}} for a, k, s, e in delegations]}}


def _round(tmp_path, convs: dict[str, list[dict]]) -> str:
    p = tmp_path / "round.json"
    p.write_text(json.dumps([{"tag": tag, "session_id": "s", "turns": turns} for tag, turns in convs.items()]))
    return str(p)


RISK_THEN_ISSUER = _turn(
    _ask({"analyst": "risk", "subjects": ["port_001"], "lines": ["which holding carries the largest weight"]}),
    _pull("risk", "book_read", book="port_001", table="issuer_exposures", column="weight"), _report("risk"),
    _ask({"analyst": "issuer", "subjects": ["MSFT"], "lines": ["capital expenditure as a share of revenue, last three fiscal years"]}),
    _pull("issuer", "metric", name="capex_intensity", subject="MSFT"), _report("issuer"),
    delegations=[("risk", 1, 1, 2), ("issuer", 1, 1, 3)])


def test_a_turn_is_read_for_the_asks_in_order_and_what_the_later_one_named(tmp_path):
    out = C.tally([_round(tmp_path, {"X01-largest-weight-then-its-cash": [RISK_THEN_ISSUER]})], questions=str(QUESTIONS))
    row = out["handoff_turns"][0]
    assert (row["chain"], row["shape"], row["asks"], row["tasks"]) == ("risk → issuer", "in_sequence", 2, 2)
    assert row["later_subjects"] == ["MSFT"] and row["families"] == ["issuer", "risk"]
    assert (row["evidence_calls"], row["settled"], row["asked"], row["answer"]) == (5, 2, 2, "accepted")
    assert out["handoffs_expected"] == {"X01-largest-weight-then-its-cash": "carried"} and row["expected"] == "carried"
    assert out["handoff_shapes"] == {"in_sequence": 1}
    assert out["handoff_by_shape"]["in_sequence"]["asks_mean"] == 2 and out["handoff_by_shape"]["in_sequence"]["settled_share"] == 1.0


def _expected(tmp_path, tag: str, *turns: dict) -> str:
    return C.tally([_round(tmp_path, {tag: list(turns)})], questions=str(QUESTIONS))["handoffs_expected"][tag]


def test_what_became_of_a_handoff_the_question_was_written_to_need(tmp_path):
    x01, x02 = "X01-largest-weight-then-its-cash", "X02-weakest-fcf-margin-then-sell-it"
    risk = {"analyst": "risk", "subjects": ["port_001"]}
    # both families in the first ask: the lead did not wait for the finding
    assert _expected(tmp_path, x01, _turn(_ask(risk, {"analyst": "issuer", "subjects": ["MSFT", "AAPL", "JPM"]}))) == "up_front"
    # asked afterwards, about another name
    assert _expected(tmp_path, x01, _turn(_ask(risk), _ask({"analyst": "issuer", "subjects": ["AAPL"]}))) == "wrong_name"
    # asked afterwards about what was found AND the others it was found among: nothing was carried
    assert _expected(tmp_path, x01, _turn(_ask(risk), _ask({"analyst": "issuer", "subjects": ["MSFT", "AAPL"]}))) == "shotgun"
    assert _expected(tmp_path, x01, _turn(_ask(risk))) == "never_asked"
    assert _expected(tmp_path, x01, _turn(_ask({"analyst": "issuer", "subjects": ["MSFT"]}))) == "upstream_never_asked"
    # a name sold in a scenario travels in the LINE, under the company's name: the subject is the book
    issuer = {"analyst": "issuer", "subjects": ["AAPL", "MSFT", "NVDA"]}
    sold = {"analyst": "risk", "subjects": ["port_001"], "lines": ["the book after selling the whole Apple position, every check re-run"]}
    assert _expected(tmp_path, x02, _turn(_ask(issuer), _ask(sold))) == "carried"
    three = {"analyst": "risk", "subjects": ["port_001"], "lines": ["the book after selling all of Apple", "… all of Microsoft", "… all of NVIDIA"]}
    assert _expected(tmp_path, x02, _turn(_ask(issuer), _ask(three))) == "shotgun"


def test_a_join_of_two_families_figures_is_carried_by_id_or_not_at_all(tmp_path):
    x07 = "X07-drawdown-repeated-in-dollars"
    both = _ask({"analyst": "risk", "subjects": ["port_001"]}, {"analyst": "market", "subjects": ["NVDA"]})
    by_id = _ask({"analyst": "risk", "subjects": ["port_001"], "follow_up_of": "tsk_0",
                  "lines": ["the position's market value [f_2592baab170e] times the drawdown [f_0ab266def5fe]"]})
    again = _ask({"analyst": "risk", "subjects": ["port_001"], "lines": ["what the position loses if the name falls 31%"]})
    out = C.tally([_round(tmp_path, {x07: [_turn(both, by_id)]})], questions=str(QUESTIONS))
    assert out["handoffs_expected"][x07] == "carried"
    assert (out["asks_carrying_ids"], out["asks_with_follow_up"], out["handoff_turns"][0]["shape"]) == (1, 1, "together")
    assert _expected(tmp_path, x07, _turn(both, again)) == "not_carried"
    assert _expected(tmp_path, x07, _turn(both)) == "not_carried"


def test_a_dependency_across_two_turns_is_read_on_the_second(tmp_path):
    x08 = "X08-two-turns-high-then-filings"
    first = _turn(_ask({"analyst": "market", "subjects": ["AAPL", "AMZN", "GOOGL", "JPM", "LLY", "MSFT", "NVDA", "XOM"]}))
    straight = _turn(_ask({"analyst": "issuer", "subjects": ["GOOGL"]}), n=2)
    back_upstream = _turn(_ask({"analyst": "market", "subjects": ["GOOGL"]}, {"analyst": "issuer", "subjects": ["GOOGL"]}), n=2)
    assert _expected(tmp_path, x08, first, straight) == "carried"
    assert _expected(tmp_path, x08, first, back_upstream) == "carried+re_asked"
    assert _expected(tmp_path, x08, first, _turn(_ask({"analyst": "issuer", "subjects": ["LLY"]}), n=2)) == "wrong_name"
    # the outcome sits on the conversation's last turn, once
    rows = C.tally([_round(tmp_path, {x08: [first, straight]})], questions=str(QUESTIONS))["handoff_turns"]
    assert [r.get("expected") for r in rows] == [None, "carried"]


def test_the_shapes_and_what_each_cost(tmp_path):
    together = _turn(_ask({"analyst": "issuer", "subjects": ["XOM"]}, {"analyst": "risk", "subjects": ["port_001"]}),
                     _ask({"analyst": "issuer", "subjects": ["XOM"], "follow_up_of": "tsk_0"}),
                     delegations=[("issuer", 3, 2, 9), ("risk", 1, 1, 2), ("issuer", 1, 1, 4)])
    alone = _turn(_ask({"analyst": "risk", "subjects": ["port_001"]}), delegations=[("risk", 2, 0, 16)], answer="rejected")
    nobody = _turn()
    out = C.tally([_round(tmp_path, {"A": [RISK_THEN_ISSUER], "B": [together], "C": [alone], "D": [nobody]})])
    assert out["handoff_shapes"] == {"no_ask": 1, "one_family": 1, "together": 1, "in_sequence": 1}
    assert [r["chain"] for r in out["handoff_turns"]] == ["risk → issuer", "issuer+risk → issuer", "risk", "-"]
    assert out["handoff_by_shape"]["together"]["evidence_calls_median"] == 15
    # a task that came back with nothing settled, and an answer the check did not accept
    assert out["tasks_returned_empty"] == 1 and out["handoff_by_shape"]["one_family"]["empty_returns"] == 1
    assert out["handoff_by_shape"]["one_family"]["answers_not_accepted"] == 1
    assert "handoffs_expected" not in out                      # no question file, nothing expected


def test_a_call_a_second_task_makes_again_is_counted_and_a_repeat_inside_one_task_is_not(tmp_path):
    weight = dict(book="port_001", table="issuer_exposures", column="weight")
    turn = _turn(
        _ask({"analyst": "risk", "subjects": ["port_001"]}),
        _pull("risk", "list", what="book", subject="port_001"),
        _pull("risk", "book_read", **weight), _pull("risk", "book_read", **weight), _report("risk"),
        _ask({"analyst": "risk", "subjects": ["port_001"], "follow_up_of": "tsk_0"}),
        _pull("risk", "list", what="book", subject="port_001"),                  # a look, not evidence
        _pull("risk", "book_read", **weight),                                    # the first task pulled exactly this
        _pull("risk", "book_read", book="port_001", table="limit_checks"), _report("risk"),
        {"step_type": "boundary", "tool_name": "calc", "actor": "sub:risk", "status": "completed",
         "result": "1 boundary row stated", "args": json.dumps({"of": "analyst_budget"})},
        {"step_type": "open", "tool_name": "open", "actor": None, "status": "completed", "result": "1 row", "args": json.dumps({"id": "f_1"})})
    out = C.tally([_round(tmp_path, {"A": [turn]})])
    assert (out["re_pulled_calls"], out["analyst_budget_stops"], out["lead_opens"], out["asks_with_follow_up"]) == (1, 1, 1, 1)


def test_an_ask_the_batterys_cut_broke_is_unreadable_and_is_said_to_be(tmp_path):
    ask = _ask({"analyst": "risk", "subjects": ["port_001"]})
    later = _ask({"analyst": "risk", "subjects": ["port_001"], "lines": ["sell the whole Apple position " + "x" * 5000]})
    later["args"] = later["args"][:4000]                       # conversation_battery._ARGS_CAP
    issuer = _ask({"analyst": "issuer", "subjects": ["AAPL", "MSFT", "NVDA"]})
    out = C.tally([_round(tmp_path, {"X02-weakest-fcf-margin-then-sell-it": [_turn(issuer, later)], "B": [_turn(ask)]})],
                  questions=str(QUESTIONS))
    assert out["asks_unreadable"] == 1 and out["handoffs_expected"]["X02-weakest-fcf-margin-then-sell-it"] == "unreadable"
    # the chain and the shape are read off the step's summary, which no cut reaches
    assert out["handoff_turns"][0]["chain"] == "issuer → risk"


def test_a_round_from_before_v1_still_tallies_and_its_asks_name_its_domains():
    out = C.tally([str(ROOT / "docs" / "spikes" / "v37" / "V37C.json")])
    assert sum(out["handoff_shapes"].values()) == out["turns"] == 20 and set(out["handoff_shapes"]) <= set(C.SHAPES)
    assert any("issuer_" in r["chain"] or "book_" in r["chain"] for r in out["handoff_turns"])


# ── the communication table reads a V1 round ─────────────────────────────────

F = _script("v36_forensics")

V1_ASK = {"seq": 2, "step_type": "delegate", "tool_name": "ask", "actor": None, "status": "completed",
          "args": {"tasks": [{"task_id": "tsk_a", "analyst": "risk", "subjects": ["port_001"], "lines": ["1. the largest holding"]},
                             {"task_id": "tsk_b", "analyst": "issuer", "subjects": ["MSFT"], "follow_up_of": "tsk_0",
                              "lines": ["1. capex against revenue", "2. interest coverage"], "context": "where the cash goes"}]}}
V36_DELEGATE = {"seq": 2, "step_type": "delegate", "tool_name": "delegate", "actor": None, "status": "completed",
                "args": {"tasks": [{"domain": "book_composition", "subjects": ["port_001"], "want_to_know": ["a", "b", "c"]}]}}
V1_BRIEF = {"seq": 9, "step_type": "brief", "tool_name": "submit", "actor": "sub:issuer", "status": "completed",
            "args": {"task_id": "tsk_b", "coverage": {"asked": 2, "settled": 1, "unsettled": 1, "refused": 0},
                     "brief": {"lines": [{"n": 1, "settled": True, "finding": "Capex was 22.9% [f_2592baab170e] of revenue.", "facts": ["f_2592baab170e"]},
                                         {"n": 2, "settled": False, "why": "no interest line is filed", "boundary": "f_0ab266def5fe"}],
                               "caveats": [{"line": 1, "text": "fiscal year to June"}], "follow_ups": ["the same for the prior year"]}}}


def test_an_ask_is_an_edge_to_the_analysts_it_names_and_an_older_delegate_reads_as_before():
    assert F._edge(V1_ASK, F.LEAD) == (F.LEAD, "sub:issuer+risk", "ask")
    assert F._edge(V36_DELEGATE, F.LEAD) == (F.LEAD, "sub", "delegate")
    assert F._edge({"step_type": "open", "tool_name": "open", "actor": None}, F.LEAD) == (F.LEAD, "store", "open")
    assert F._summary(V1_ASK, V1_ASK["args"]) == "risk [port_001] 1 line(s); issuer [MSFT] 2 line(s) ↩tsk_0"
    assert F._summary(V36_DELEGATE, V36_DELEGATE["args"]) == "book_composition [port_001] 3 line(s)"
    assert F._summary({**V1_BRIEF, "result_summary": "accepted"}, V1_BRIEF["args"]).startswith("coverage 1/2 not_done 1 refused 0 · completed")


def test_what_went_down_and_what_came_back_is_printed_in_full():
    said = "\n".join(F._exchange([V1_ASK, V1_BRIEF]))
    for piece in ("ask → risk [port_001]", "ask → issuer [MSFT]", "follows up tsk_0", "2. interest coverage", "context: where the cash goes",
                  "sub:issuer → check  tsk_b", "1. settled, 1 row(s): Capex was 22.9% [f_2592baab170e]",
                  "2. not settled [f_0ab266def5fe]: no interest line is filed", "caveat on 1: fiscal year to June",
                  "would ask next: the same for the prior year"):
        assert piece in said, piece
    assert F._exchange([V36_DELEGATE]) == []                   # a round before V1 has no such block
    # the replay reads a V1 brief's findings, and a V36 one's
    assert F._brief_text(V1_BRIEF["args"]["brief"]) == "Capex was 22.9% [f_2592baab170e] of revenue."
    assert F._brief_text({"findings": [{"finding": "a"}, {"finding": "b"}]}) == "a\nb"
