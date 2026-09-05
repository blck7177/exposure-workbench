#!/usr/bin/env python3
"""Score battery traces against atomic criteria — the V14 acceptance instrument.

`agent_battery.py` measures BEHAVIOUR (what was called, what came back). This
scores SHAPE: whether an answer does what an analyst's answer does — order the
drivers, net the offsetting legs, quantify the trigger, say what to do. Round 4
established that the gate cannot carry this: verification's unit is the number
and meaning's unit is the sentence. So shape is measured, never gated, and the
judge that measures it runs HERE and nowhere near the serving path.

Two kinds of criterion, and the split is the point:

  structural  judged from `agent_steps` by code. Deterministic, free, and the
              only kind allowed to gate a batch. "Did it read what the question
              needs" is a fact about the trace.
  semantic    judged offline by a model reading the answer. Costs money and is
              not reproducible to the token, so it reports a distribution over
              repeats, never a verdict on one run.

Every criterion is BINARY, following DeepResearch Bench II: a rubric that scores
impressions cannot regress-test, because nobody can say which change moved a 7
to a 6. `unmet` is a claim you can argue with; 0.62 is not.

    # free: structure only, no model calls
    python scripts/rubric_battery.py traces.json --out scored.json

    # adds the semantic pass (costs tokens; --estimate first)
    python scripts/rubric_battery.py traces.json --out scored.json --semantic
    python scripts/rubric_battery.py traces.json --semantic --estimate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(".env", override=True)

from exposure_workbench.llm.client import chat_complete

# --- the closed vocabulary -------------------------------------------------
#
# Closed on purpose. A criterion invented per question is a criterion that
# cannot be compared across a batch, and the whole instrument exists to compare
# across batches. Adding one is a deliberate act: name it here, say what makes
# it FALSE, and every question that carries it is asking for the same thing.

STRUCTURAL = {
    # The question's frame names inputs; did the turn actually read them? Round
    # 4's finding was that answers fail for want of a read far more often than
    # for want of a tool.
    "read_required_inputs": "the tools this question's answer rests on were called",
    # Turn 2 of sess_16b176ea4c9b spent 11 of 15 calls locating. A book-level
    # question that pays per holding to find out what it holds has no budget
    # left to read anything.
    "no_linear_locating": "locating calls did not scale with the number of holdings",
}

SEMANTIC = {
    "ranking": (
        "The drivers are ordered by magnitude and the largest is named as the largest. "
        "FALSE if exposures are listed flat, in arbitrary or narrative order, or if a "
        "smaller driver is presented with the same weight as a larger one."
    ),
    "netting": (
        "Where exposures offset, the net is stated with its direction. FALSE if legs "
        "that point opposite ways (a duration long against a spread short, a hedge "
        "against the thing it hedges) are listed side by side as if they added up."
    ),
    "trigger": (
        "At least one monitoring threshold is quantified — a level, a move, a spread "
        "in basis points — such that crossing it would change the assessment. FALSE if "
        "the answer says to watch something without saying at what level it matters."
    ),
    "so_what": (
        "The answer closes with an implication for this book that a portfolio manager "
        "could act on. FALSE if it ends by restating the data, or offers only to do "
        "more work."
    ),
    "grounded_claims": (
        "Claims about a business or a period rest on this system's evidence rather than "
        "general knowledge. FALSE if the substance would read identically for a company "
        "the system has never ingested — generic sector prose with no filed figure, no "
        "quoted passage, and no named period behind it."
    ),
    # V24 (the boss, 2026-09-05). The V23 battery scored an honest "the desk
    # does not hold this split" (C04#t2) BELOW V21's substituted wrong figure,
    # because no criterion rewarded correct abstention. This one does: the
    # answer that says what is not held, points at the record of its absence
    # and offers the nearest thing the desk does hold beats one that fills the
    # gap with a neighbouring figure wearing the asked-for name.
    "honest_absence": (
        "Where the question asks for a figure or a split the desk does not hold, the "
        "answer says so plainly, names why (not filed; not held as a figure; no method), "
        "and offers the nearest thing the desk DOES hold as what it is. FALSE if a "
        "nearby figure is presented under the asked-for name, if a number is estimated, "
        "or if the gap is passed over in silence."
    ),
    # V21. A conversation's second turn is not a question on its own: "and the
    # other two?" has no subject, and "is that a one-off" has no referent. The
    # unit the other criteria score is one answer; this one scores the JOIN.
    "follows_on": (
        "The turn resolves what the user's words point at — the entities, the measure or "
        "the finding carried over from the exchange before it — and answers THAT. FALSE if "
        "it asks the user to restate what was already said, silently changes the subject, "
        "the measure or the period, or re-answers the previous turn instead of this one."
    ),
    "precision": (
        "Figures are written at a precision a reader uses. FALSE if ledger-raw precision "
        "is reproduced in prose (33.878625%, 0.5556454228194568) where two or three "
        "significant figures is what the sentence needs."
    ),
}

LOCATING_TOOLS = {"describe"}

# Which tools count as having read the thing each question rests on. Keyed by
# tag, because "required" is a property of the question, not of the system: a
# drawdown question that never measures an episode has not read its inputs, and
# a rate question that never looks at the factor loadings has not either.
REQUIRED: dict[str, set[str]] = {
    "V1-macro-breakdown": {"read_book", "read_book"},
    "V2-fundamental-lens": {"read_filings", "read_filings"},
    "V3-rate-exposure": {"read_book"},
    "V4-what-to-watch": {"read_book", "read_book", "read_book"},
    "V5-drawdown-forensics": {"compute"},
    "V6-concentration-mandate": {"read_book"},
    "V7-single-name-integration": {"read_book", "read_book"},
    "V8-cross-issuer": {"compute"},
}

_JUDGE_PROMPT = """You are scoring one answer from a financial analysis assistant against \
one criterion. Answer with a single word, MET or UNMET, then a newline, then one \
sentence of at most 25 words quoting or pointing at what decided it.

Score only the criterion given. An answer can be excellent and still UNMET on a \
criterion it did not attempt. An answer can be poor and still MET on this one. Do \
not reward length, hedging, or offers to do more work.

CRITERION ({name}): {definition}

THE QUESTION ASKED:
{question}

THE ANSWER:
{answer}
"""


def _tools_called(steps: list[dict]) -> list[str]:
    return [s["tool_name"] for s in steps
            if s.get("tool_name") and s["step_type"] == "tool_call"]


def _question_tag(rec: dict) -> str:
    """Which question this record answers. A record that states it is believed;
    otherwise the --repeat suffix is stripped. Conversation turns state it,
    because `C01-trim-one#t2` ends in a digit and is not a repeat of `C01`."""
    if rec.get("question_tag"):
        return rec["question_tag"]
    return rec["tag"].rsplit("-", 1)[0] if rec["tag"][-1].isdigit() else rec["tag"]


def flatten_conversations(convos: list[dict]) -> list[dict]:
    """A conversation file (scripts/conversation_battery.py) as one record per
    TURN, each carrying the exchange before it as `context`."""
    out: list[dict] = []
    for c in convos:
        history: list[str] = []
        for t in c.get("turns", []):
            tag = f"{c['tag']}#t{t.get('turn', len(history) + 1)}"
            out.append({"tag": tag, "question_tag": tag, "session_id": c.get("session_id"),
                        "question": t.get("q"), "answer": t.get("answer"), "error": t.get("error"),
                        "steps": t.get("steps", []), "context": "\n\n".join(history)})
            history.append(f"USER: {t.get('q')}\nDESK: {(t.get('answer') or '')[:1500]}")
    return out


def _score_structural(rec: dict, holdings: int) -> dict:
    tools = _tools_called(rec.get("steps", []))
    tag = _question_tag(rec)
    out = {}

    required = REQUIRED.get(tag, set())
    missing = sorted(required - set(tools))
    out["read_required_inputs"] = {
        "met": not missing,
        "why": "all required reads present" if not missing else f"never called: {', '.join(missing)}",
    }

    locating = sum(1 for t in tools if t in LOCATING_TOOLS)
    # Linear means "one per holding". Half the book is the line: below it the
    # turn is locating selectively, at or above it the turn is sweeping.
    ceiling = max(2, holdings // 2)
    out["no_linear_locating"] = {
        "met": locating < ceiling,
        "why": f"{locating} locating calls against a ceiling of {ceiling} for {holdings} holdings",
    }
    return out


async def _judge_one(name: str, question: str, answer: str, model: str | None,
                     context: str = "") -> dict:
    prompt = _JUDGE_PROMPT.format(name=name, definition=SEMANTIC[name],
                                  question=question, answer=answer)
    if context:
        # Only for a turn that has one. A criterion about the JOIN cannot be
        # scored without the thing joined to, and every other criterion is
        # scored on this turn alone — so the context is appended, never mixed
        # into the answer under judgement.
        prompt += f"\n\nWHAT WAS SAID BEFORE THIS TURN (context, not under judgement):\n{context}\n"
    content, _model, _p, _c = await chat_complete(
        [{"role": "user", "content": prompt}], model=model, max_tokens=120)
    head, _, rest = (content or "").strip().partition("\n")
    verdict = head.strip().upper()
    if verdict not in {"MET", "UNMET"}:
        # A judge that cannot be parsed is not a failing answer — it is a
        # failing measurement, and recording it as UNMET would silently move
        # the batch's score. Same discipline as the gate: no third state
        # pretending to be one of the two.
        return {"met": None, "why": f"unparsed judge reply: {head[:60]}"}
    return {"met": verdict == "MET", "why": rest.strip()[:200]}


def _estimate(records: list[dict], questions: dict) -> None:
    calls = chars = 0
    for rec in records:
        tag = _question_tag(rec)
        q = questions.get(tag)
        if not q or not rec.get("answer"):
            continue
        for name in q["criteria"]:
            if name in SEMANTIC:
                calls += 1
                chars += len(_JUDGE_PROMPT.format(name=name, definition=SEMANTIC[name],
                                                  question=rec.get("question") or q["q"],
                                                  answer=rec["answer"]))
                chars += len(rec.get("context", "")) if name == "follows_on" else 0
    print(f"semantic pass: {calls} judge calls, ~{chars // 4:,} prompt tokens "
          f"(+{calls * 120:,} completion cap)")


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", help="output of agent_battery.py")
    ap.add_argument("--questions", default="tests/battery/questions_v14.json")
    ap.add_argument("--out")
    ap.add_argument("--semantic", action="store_true", help="run the judge pass (costs tokens)")
    ap.add_argument("--estimate", action="store_true", help="print the semantic cost and stop")
    ap.add_argument("--judge-model", default=os.getenv("RUBRIC_JUDGE_MODEL") or None)
    ap.add_argument("--holdings", type=int, default=10, help="positions in the book under test")
    args = ap.parse_args(argv)

    raw = json.load(open(args.traces))
    records = flatten_conversations(raw) if raw and "turns" in raw[0] else raw
    questions = {q["tag"]: q for q in json.load(open(args.questions))}

    if args.estimate:
        _estimate(records, questions)
        return 0

    scored = []
    for rec in records:
        tag = _question_tag(rec)
        q = questions.get(tag)
        if q is None:
            print(f"[{rec['tag']}] no such question in {args.questions}", file=sys.stderr)
            continue

        criteria = {}
        structural = _score_structural(rec, args.holdings)
        for name in q["criteria"]:
            if name in STRUCTURAL:
                criteria[name] = structural[name]

        answered = bool(rec.get("answer")) and not rec.get("error")
        if args.semantic and answered:
            for name in q["criteria"]:
                if name in SEMANTIC:
                    criteria[name] = await _judge_one(
                        name, rec.get("question") or q["q"], rec["answer"], args.judge_model,
                        context=rec.get("context", "") if name == "follows_on" else "")
        elif not answered:
            for name in q["criteria"]:
                if name in SEMANTIC:
                    criteria[name] = {"met": False, "why": "no answer to score"}

        refusals = sum(1 for s in rec.get("steps", [])
                       if s["step_type"] == "respond" and "error" in (s.get("result") or ""))
        met = sum(1 for c in criteria.values() if c["met"] is True)
        judged = sum(1 for c in criteria.values() if c["met"] is not None)
        scored.append({"tag": rec["tag"], "question_tag": tag, "answered": answered,
                       "gate_refusals": refusals, "tool_calls": len(_tools_called(rec.get("steps", []))),
                       "met": met, "judged": judged, "criteria": criteria})
        flags = " ".join(f"{'+' if c['met'] else '-' if c['met'] is False else '?'}{n}"
                         for n, c in criteria.items())
        print(f"[{rec['tag']}] {met}/{judged}  refusals={refusals}  {flags}", flush=True)

    by_criterion: dict[str, list[bool]] = defaultdict(list)
    for s in scored:
        for name, c in s["criteria"].items():
            if c["met"] is not None:
                by_criterion[name].append(c["met"])
    print("\n--- by criterion ---")
    for name in sorted(by_criterion):
        hits = by_criterion[name]
        print(f"  {name:24s} {sum(hits)}/{len(hits)}")
    total_met = sum(s["met"] for s in scored)
    total_judged = sum(s["judged"] for s in scored)
    print(f"  {'TOTAL':24s} {total_met}/{total_judged}")
    print(f"  {'answered':24s} {sum(1 for s in scored if s['answered'])}/{len(scored)}")
    print(f"  {'gate refusals (median)':24s} "
          f"{sorted(s['gate_refusals'] for s in scored)[len(scored) // 2] if scored else 0}")

    if args.out:
        json.dump({"scored": scored,
                   "by_criterion": {k: [sum(v), len(v)] for k, v in by_criterion.items()}},
                  open(args.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
