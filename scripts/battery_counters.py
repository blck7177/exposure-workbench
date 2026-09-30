#!/usr/bin/env python3
"""V30 Phase 0 — the two counters the instrument keeps apart, plus the mechanics.

The rubric is a judged distribution. THIS is countable and reproducible, and it
splits every refusal by whose work it was:

  spelling   the call was written wrongly for the protocol (a name at the wrong
             door, an id the desk never showed, two shapes in one call, an
             address the schema refused). V30 removes the protocol; this class
             is what should go to zero.
  gate       the answer's pointers or prose were refused (unsourced figure,
             not on ledger, malformed, quote not verbatim).
  algebra    the typed calculator or a floor refused a combination — the
             desk being right about the world. These stay.
  data       the desk does not hold it (not filed, not prepared, no prices).
  system     an adapter or transport failure, budget, quota.

V36 (2026-09-15): a turn has more than one agent in it. The lead delegates; a
domain analyst per task takes the evidence calls and files a brief that a code
check (delegation.handoff_check) accepts or refuses; a report lands beside the
answer. The counters below read that: how often the lead delegated, how many
analysts ran and how each ended, how much of what was asked came back settled
(coverage), how often a submission was refused at the handoff and for what, how
the reports were marked, and the completions split by who spent them. Note that
`prompt_tokens_median` sums every completion of the turn, analysts included;
`lead_prompt_peak_*` is the lead's own peak (meta.prompt_tokens) and is the
series comparable with the rounds before V36. A round without analysts reads as
zeros here and its lead completions equal its round trips.

V1 (2026-09-19): the analysts hold twelve primitive verbs, every call says WHY, and a step says
what the call GOT — "r_… book_read(…) → 1 row | refused: unknown_name" (fact_adapters.came_back).
What plan step 7 measures is read off that: asks a turn and tasks an ask, calls a task and by
verb, how a why reads (its length, whether it names the line it serves), the analysts' own prompt
peak, the share of calls refused, refusals by the style guide's RULE (the sentences that
contradicted the word on their row are rule 6: `sense_conflict`, `status_conflict`), how much of
what the desk refused was arithmetic (decides whether `calc` needs another operation), and which
model each agent ran on. A round from before V1 reads as zeros in these and keeps its own series.

V1, the cross-family series (2026-09-20): an analyst reaches one family of evidence, so a question
whose second half depends on what the first half found goes through the lead between two
analysts. Read per turn: the asks in order ("risk → issuer"), the shape (`together`: every family
in the first ask; `in_sequence`: a later ask brought one in), what a later ask named that the
first did not, asks that carried a row's id down, calls one task made that an earlier task had
already made, analysts stopped by their budget — and, by shape, what the turns cost and came to.
`--questions` reads docs/spikes/v1/questions_cross_family.json beside the round: each entry says
which handoff it was written to need, and the round is read for what became of it.

    python scripts/battery_counters.py docs/spikes/v30/V26_R1.json [more.json] [--json out]
    python scripts/battery_counters.py ROUND_X.json --questions docs/spikes/v1/questions_cross_family.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from exposure_workbench.services.claims import SPELLING_REFUSALS   # noqa: E402

# The counter asks a different question from the gate, and the two sets have
# deliberately diverged since C4. claims.SPELLING_REFUSALS is "this refusal
# cannot back an absence a reader is told"; a coverage refusal (unknown_name,
# unknown_point, unknown_method, unknown_metric) left that set because it names
# what the desk DOES hold. Here the question is only "did the call land", and a
# coverage refusal is still a round trip spent, so the counter keeps them — which
# also keeps this series comparable with every round measured before C4. The
# import is the floor: whatever the gate calls an address error is one here too.
SPELLING = set(SPELLING_REFUSALS) | {
    "expand_needs_a_subject", "unknown_expand", "domain_not_for_subject", "invalid_arguments",
    "invalid_params", "unknown_method", "unknown_name", "unknown_operand", "unknown_portfolio",
    "unknown_run", "unknown_row", "unknown_series", "unknown_formula", "unknown_metric",
    "unknown_kind", "unknown_window", "unknown_span", "unknown_unit", "op_or_method",
    "query_or_item", "operands", "params", "subject_required", "not_a_series", "series_only",
    "not_a_book", "not_a_quantity", "not_a_scenario", "unsupported_op", "unsupported_direction",
    "untyped_operand", "untyped_series", "undated_operand", "not_on_this_face", "too_few_operands",
    "unrankable_operand", "invalid_as_of_date", "invalid_date", "invalid_window", "unknown_job",
    "unknown_company", "unknown_tool",
    # V33: the program writer's type work (a static report before anything runs)
    # and a request the analyst's one tool could not parse
    "type_errors", "malformed_program", "invalid_request", "not_a_filed_line", "metric_is_a_method",
    # V1: a trade that is neither a sale nor a purchase, a trade list with nothing in it
    "bad_trade", "no_trades",
}
GATE = {
    "unsourced_figure", "malformed_answer", "unverified_quote", "not_on_ledger", "id_in_prose",
    "name_in_prose", "pointer_written_as_text", "pointer_not_separated", "kind_does_not_fit",
    "unknown_point", "not_standalone", "missing_citations", "unverified_numbers", "not_on_table",
    "unresolved_slots", "invalid_citations", "unsupported_assertion",
    # V33 answer check (services/answer_check.py): numbers against the ledger,
    # relation words against the facts' rank/op/as_of/tier
    "ambiguous_figure", "mark_mismatch", "unknown_node", "subject_mismatch", "measure_mismatch",
    "superlative_without_rank", "date_expected", "tier_mismatch", "direction_conflict",
    "change_conflict",
    # V37: the period a sentence claims against the readings' own dates
    "period_mismatch",
    # V35 (the figures point): a bare figure the ledger holds, a series point on
    # several dates, a reply written while a verdict stood
    "unpointed_figure", "ambiguous_point", "malformed_repair",
    # V1: the sentence against the word its own row carries
    "sense_conflict", "status_conflict", "repeated_answer",
}
ALGEBRA = {
    "different_instants", "overlapping_intervals", "mismatched_windows", "overlapping_quantities",
    "incompatible_units", "incompatible_bases", "inconsistent_units", "incomparable_units",
    "mixed_basis_operand", "undefined_product", "undefined_quotient", "different_books",
    "mixed_worlds", "incomparable_quantities", "unnamed_quantity", "division_by_zero",
    "misaligned_series", "not_alone", "duplicate_operand", "indistinguishable_operands",
    "insufficient_history", "degenerate_regressor", "self_regression", "series_in_set",
    "not_combinable", "undeclarable_unit", "bad_sale", "bad_buy", "bad_fraction", "bad_weight",
    "duplicate_sale", "duplicate_buy", "already_held", "empty_book", "unpriced_holding",
    "run_not_reconcilable", "limits_incomplete",
    # V1: a measure with no meaning for the subject, as the desk refuses it
    "not_for_financials", "denominator_not_positive", "several_figures", "double_count", "different_dates",
}
DATA = {
    "metric_not_filed", "not_reported", "not_reported_at_this_date", "no_price_data",
    "no_price_history", "not_prepared", "company_not_found", "section_not_found", "not_indexed",
    "no_brief", "no_completed_run", "run_not_completed", "input_unavailable", "line_superseded",
    "series_not_derivable", "not_applicable", "empty_series", "no_positions", "no_limits",
    "no_sector", "no_balance_sheet_data", "not_held", "not_listed", "not_investigable",
    "not_an_sec_filer", "active_run_exists", "not_your_portfolio",
    "no_entry_satisfies", "no_prior_run",
}
SYSTEM = {"tool_error", "fact_adapter_error", "tool_transport_error", "budget_exceeded",
          "quota_exceeded", "provider_unavailable", "sign_in_required", "no_research_run",
          "analyst_budget"}                  # V1: an analyst's own evidence calls, used

# a tool step's summary is "error: <code>"; a V33 answer step's is "refused: <code>; …"
_ERR = re.compile(r"^(?:error|refused): ([a-z_]+)")
_ARTIFACT = re.compile(r"(?:%|\d)=-?\d[\d.,]*|\b\d[\d.,]*%?, \d[\d.,]*%?\b")   # "16.1%=0.161", "16.1%, 16.1%"
_MARK = re.compile(r"\[10-[KQ][^\]]*\]")
# A superlative or top-N claim in the answer, against a successful rank in the
# same turn (V29 §6.1: 47/55, 47/58, 51/60 claims with no ordering computed).
# The WIDE definition the V29 findings use (§6.1), so the two sessions publish one
# number: "nearest to tripping" is an ordering claim too.
_SUPERLATIVE = re.compile(r"\b(largest|biggest|highest|lowest|smallest|worst|best|nearest|closest|most concentrated|top\s+(?:\d+|five|three|ten))\b", re.I)
# The producer's declaration, as tools/registry._declared_nodes writes it, and
# the one call that is its own declaration. Structure, not spelling: a node's
# kind is `ranking` because program_service typed it, not because the program
# text happened to contain a word.
_NODES = re.compile(r"\| nodes: ")
_RANK_NODE = re.compile(r"\| nodes: [^|]*\b=ranking\b")
_RANK_OP = re.compile(r'"op":\s*"(?:rank|top)"')
# V36: a refused submission's summary, as sub_analyst records the brief step —
# the count of problems and the FIRST problem's reason.
_HANDOFF = re.compile(r"^refused: \d+ problem\(s\); ([a-z_]+)")


# V37: what one `run` came back as, read off the producer's own declaration.
# `| nodes: name=kind` is written by tools/registry._declared_nodes, so a node
# that refused says `=absence` there — structure, not a spelling in the program.
_ABSENCE_NODE = re.compile(r"\| nodes: [^|]*\b=absence\b")


def runs_by_domain(steps: list[dict]) -> dict[str, collections.Counter]:
    """Every `run` of one turn, attributed to the analyst that made it.

    WHY THIS COUNT EXISTS. Round B's headline numbers were per round: 100 runs,
    28 of them type errors. Per DOMAIN they said something the round-level
    number hid — `book_market_risk` made 23 of those runs and exactly one came
    back clean, while it was answering 6 of the 24 lines asked of it. A domain
    the lead keeps being routed to and which cannot execute is a skill problem
    (its offers promise what the desk withholds), and no round-level counter can
    show that.

    The actor is on the row from V37/M1 on (it rides on the call as request
    metadata). Before that the registry wrapper sat behind the MCP door and was
    not told, so a tool call is attributed to the analyst that spoke last —
    exact while analysts run one at a time, which is every round to date
    (`parallel_analysts` is off). Same rule as scripts/v36_forensics.py, so a
    reading of an old round and a new one are the same reading.
    """
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    speaking: str | None = None
    for s in sorted(steps, key=lambda x: x.get("seq") or 0):
        actor = str(s.get("actor") or "")
        if actor.startswith("sub:"):
            speaking = actor[4:]
        elif s.get("step_type") in ("delegate", "answer", "respond", "read_report"):
            speaking = None                      # the lead took the floor back
        if s.get("tool_name") != "run" or s.get("step_type") != "tool_call":
            continue
        who = actor[4:] if actor.startswith("sub:") else (speaking or "meta")
        result = s.get("result") or ""
        c = out[who]
        c["runs"] += 1
        if result.startswith("error: type_errors"):
            c["type_errors"] += 1
        elif result.startswith("error"):
            c["other_errors"] += 1
        elif _ABSENCE_NODE.search(result):
            c["with_absence"] += 1
        else:
            c["clean"] += 1
    return out


# V1: what a primitive's step says its call got (services/fact_adapters.came_back)
_V1_STEP = re.compile(r"^r_[0-9a-z]+ (?P<verb>[a-z_]+)\(")
_V1_REFUSED = re.compile(r"\| refused: (?P<codes>[a-z_]+(?:, [a-z_]+)*)\s*$")
_WHY = re.compile(r'"why":\s*"((?:[^"\\]|\\.)*)"')
_NAMES_A_LINE = re.compile(r"\blines?\s*\d", re.I)
_MODEL = re.compile(r"^([^:\s]+): \d+ tool call")
ARITHMETIC_VERBS = ("calc",)


def channel_of(where, step_type) -> str:
    """Which of the analyst's channels a handoff problem is about (V2 P1.1): the finding
    of a line, a caveat, an unsettled line's why, a follow-up — or the lead's answer.
    Read off the problem's `where`, which the check writes; a problem about the SHAPE
    of the brief (a line with no entry) names no channel."""
    if step_type == "answer":
        return "answer"
    w = str(where or "")
    if w.startswith("caveats["):
        return "caveat"
    if w.endswith("/ why"):
        return "why"
    if w.startswith("follow_ups["):
        return "follow_up"
    if w.startswith("line"):
        return "finding"
    return "shape"


def _rule_of(reason) -> int | None:
    """The style guide's rule a reason enforces, for a problem recorded before problems carried it.
    The guide is the one place that mapping is written (services/style_guide); where it is not
    there to ask, a problem without a rule stays unnumbered rather than guessed."""
    try:
        from exposure_workbench.services import style_guide
    except ImportError:
        return None
    return style_guide.rule_of(reason)


def refused_codes(summary: str) -> list[str]:
    """The codes of the refusals among a V1 call's rows; none for a call that only read."""
    m = _V1_REFUSED.search(summary or "")
    return m.group("codes").split(", ") if m else []


def class_of(code: str) -> str:
    for name, members in (("spelling", SPELLING), ("gate", GATE), ("algebra", ALGEBRA), ("data", DATA), ("system", SYSTEM)):
        if code in members:
            return name
    return f"other:{code}"


def why_of(args) -> str | None:
    """A call's `why`, from its arguments as the battery stored them (text, cut at a cap: a cut
    breaks the JSON, never the why, which a call says before anything long)."""
    if isinstance(args, dict):
        return args.get("why")
    try:
        got = json.loads(args or "{}")
        return got.get("why") if isinstance(got, dict) else None
    except (ValueError, TypeError):
        m = _WHY.search(args or "")
        return m.group(1) if m else None


def problems_of(step: dict) -> list[dict]:
    """Every problem a check named on an `answer` or a `brief` step (V1 keeps the list on both)."""
    for raw in (step.get("problems"), step.get("args")):
        try:
            got = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        if isinstance(got, dict):
            got = got.get("problems")
        if isinstance(got, list):
            return [x for x in got if isinstance(x, dict)]
    return []


def calls_by_analyst(steps: list[dict]) -> dict[str, collections.Counter]:
    """V1: every call of one turn by the analyst that made it — how many, by verb, and how each
    came back. `list` is a look and `start` an id; the rest are the evidence calls a task is
    allowed sixteen of. The actor is on every row a V1 round records."""
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for s in steps:
        actor = str(s.get("actor") or "")
        if (not actor.startswith("sub:") and actor != "meta") or s.get("step_type") not in ("tool_call", "delegation"):
            continue
        result = s.get("result") or ""
        # the first V1 turns (2026-09-19, before a step said what its call got) summarised every
        # primitive by its payload's keys: a call, by a verb, that came back as nobody can now say
        unstated = result.startswith("keys: pull, head")
        if not (_V1_STEP.match(result) or unstated or s.get("status") == "rejected" or result.startswith("error")):
            continue                                  # a call of the surface before V1: runs_by_domain reads those
        c = out[actor[4:] if actor.startswith("sub:") else "meta"]
        c["calls"] += 1
        c[f"verb.{s.get('tool_name')}"] += 1
        if unstated:
            c["unstated"] += 1
        elif s.get("status") == "rejected":
            c["not_run"] += 1                         # arguments that do not fit, or a budget spent
        elif refused_codes(result):
            c["refused"] += 1
        elif result.startswith("error"):
            c["errors"] += 1
        else:
            c["read"] += 1
    return out


# ── V1, the cross-family series (plan step 7): what crosses the lead between two analysts ──
# An analyst reaches one family of evidence, so a question whose second half depends on what the
# first half FOUND — the largest holding, then that issuer's filings — is two asks with the lead
# in between: the name travels down in the second ask's subjects or lines, a figure only by its
# id. What that costs, and whether the thing carried was the thing found, is read off the
# `delegate` steps: their summary ("risk [port_001] 2 line(s); issuer [MSFT] 3 line(s)") survives
# the battery's cut of `args`, and the lines themselves are read from `args` where it parses.
_ASKED = re.compile(r"([a-z_]+) \[([^\]]*)\] (\d+) line\(s\)")
_FACT_ID = re.compile(r"\bf_[0-9a-f]{6,}\b")
LOOKS = ("list", "start")                      # a look and an id: neither is evidence pulled twice
SHAPES = ("no_ask", "one_family", "together", "in_sequence")


def _json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "null")
    except (ValueError, TypeError):
        return None


def asks_of(steps: list[dict]) -> list[list[dict]]:
    """The asks of one turn that the protocol accepted, in order, each a list of its tasks:
    {analyst, subjects, lines, text, follow_up_of}. `text` is what the lead wrote down to that
    analyst — its lines and its sentence of context — or None where the battery's cut broke the
    JSON: a counter that reads the text then says `unreadable`, never "not there"."""
    out: list[list[dict]] = []
    for s in steps:
        if s.get("step_type") != "delegate" or s.get("status") == "rejected":
            continue
        tasks = [{"analyst": a, "subjects": [x for x in subs.split(",") if x], "lines": int(n), "text": None,
                  "follow_up_of": None} for a, subs, n in _ASKED.findall(s.get("result") or "")]
        args = _json(s.get("args"))
        sent = args.get("tasks") if isinstance(args, dict) else None
        if isinstance(sent, list) and len(sent) == len(tasks):
            for t, got in zip(tasks, sent):
                if isinstance(got, dict):
                    t["text"] = " ".join([*(str(w) for w in got.get("lines") or []), str(got.get("context") or "")])
                    t["follow_up_of"] = got.get("follow_up_of") or None
                    t["input_refs"] = list(got.get("input_refs") or [])
        if tasks:
            out.append(tasks)
    return out


def shape_of(asks: list[list[dict]]) -> str:
    """How a turn reached its families. `together`: every family it used was in the first ask — the
    lead took the question apart before anything came back. `in_sequence`: a later ask brought in a
    family not asked before — something had to come back first, or the lead did not see the second
    half coming. One family, however many asks, is `one_family`."""
    if not asks:
        return "no_ask"
    families = {t["analyst"] for ask in asks for t in ask}
    if len(families) < 2:
        return "one_family"
    return "together" if families == {t["analyst"] for t in asks[0]} else "in_sequence"


def chain_of(asks: list[list[dict]]) -> str:
    """The asks as a reader says them: "risk → issuer", "issuer+risk → risk", "issuer×3"."""
    said = []
    for ask in asks:
        n = collections.Counter(t["analyst"] for t in ask)
        said.append("+".join(a + (f"×{k}" if k > 1 else "") for a, k in sorted(n.items())))
    return " → ".join(said) or "-"


def re_pulls(steps: list[dict]) -> int:
    """Evidence calls one task made that an EARLIER task of the turn had already made, argument for
    argument (the `why` aside). Inside a task the desk answers a repeat from what it said before and
    does not charge it (agents/repeats); across tasks nothing does, because the second analyst was
    never shown the first one's rows. Tasks run one after another and each ends at its `report`
    step; with `parallel_analysts` on they would interleave and this could not tell them apart."""
    seen: dict[str, int] = {}
    task = again = 0
    for s in steps:
        if s.get("step_type") == "report":
            task += 1
            continue
        if (s.get("step_type") != "tool_call" or not str(s.get("actor") or "").startswith("sub:")
                or s.get("tool_name") in LOOKS or s.get("status") == "rejected"):
            continue
        args = _json(s.get("args"))
        if not isinstance(args, dict):
            continue
        key = json.dumps([s.get("tool_name"), {k: v for k, v in args.items() if k != "why"}], sort_keys=True, default=str)
        if seen.setdefault(key, task) != task:
            again += 1
    return again


def handoff_of(tag: str, t: dict) -> dict:
    """One turn, read for what crossed the lead: the asks in order, the shape, what was carried
    down, what was pulled twice, where a budget stopped an analyst — beside what the turn cost and
    what came of it, so that turns of one shape can be set against turns of another."""
    steps, meta = t.get("steps") or [], t.get("meta") or {}
    asks = asks_of(steps)
    tasks = [x for ask in asks for x in ask]
    later = [x for ask in asks[1:] for x in ask]
    first = {sub for x in (asks[0] if asks else []) for sub in x["subjects"]}
    cov = [d.get("coverage") or {} for d in meta.get("delegations") or []]
    evidence_handoffs = [d["handoff"] for d in meta.get("delegations") or []
                         if (d.get("handoff") or {}).get("protocol") == "evidence-v2"]
    answers = [s for s in steps if s.get("step_type") == "answer"]
    return {
        "tag": tag, "turn": t.get("turn"), "chain": chain_of(asks), "shape": shape_of(asks),
        "asks": len(asks), "tasks": len(tasks), "families": sorted({x["analyst"] for x in tasks}),
        # what a later ask named that the first did not: the subject the lead carried across
        "later_subjects": sorted({sub for x in later for sub in x["subjects"]} - first),
        "follow_ups": sum(1 for x in tasks if x["follow_up_of"]),
        "ids_carried": sum(1 for x in tasks if x.get("input_refs") or (x["text"] and _FACT_ID.search(x["text"]))),
        "bound_input_refs": sum(len(x.get("input_refs") or []) for x in tasks),
        "lead_evidence_calls": int(meta.get("lead_evidence_calls") or 0),
        "unreadable": sum(1 for x in tasks if x["text"] is None),
        "re_pulls": re_pulls(steps),
        "budget_stops": sum(1 for s in steps if s.get("step_type") == "boundary" and "analyst_budget" in str(s.get("args") or "")),
        "opens": sum(1 for s in steps if s.get("step_type") == "open"),
        "lead_completions": sum(1 for s in steps if s.get("step_type") == "llm_call"
                                and not str(s.get("actor") or "").startswith("sub:")),
        "evidence_calls": int(meta.get("lead_evidence_calls") or 0) + sum(int((d.get("cost") or {}).get("evidence_calls") or 0) for d in meta.get("delegations") or []),
        "elapsed_s": t.get("elapsed_s") or 0,
        "asked": sum(int(c.get("asked") or 0) for c in cov),
        "settled": sum(int(c.get("settled", c.get("done")) or 0) for c in cov),
        # a task that came back with no line settled: the family asked did not hold it, or could
        # not reach it — in a turn `in_sequence`, the round trip that found out who does
        "empty_returns": (sum(1 for c in cov if int(c.get("asked") or 0) and not int(c.get("settled", c.get("done")) or 0))
                          + sum(1 for h in evidence_handoffs if not any(h.get(k) for k in
                                ("selected_evidence", "available_evidence", "accepted_notes")))),
        "evidence_handoff_tasks": len(evidence_handoffs),
        "answer": ("accepted" if any(s.get("status") == "completed" for s in answers)
                   else "refused" if answers else "none"),
        "_asks": asks,
    }


def _names(task: dict, spellings: list[str]) -> bool | None:
    """Whether a task names one company, under any of its spellings (["MSFT", "Microsoft"]) — as a
    subject, or as a word of what the lead wrote: a name sold in a scenario is in the line, and the
    subject is the book. None: the lines could not be read, and the subjects do not say."""
    if any(s.upper() in (x.upper() for x in task["subjects"]) for s in spellings):
        return True
    if task["text"] is None:
        return None
    return any(re.search(rf"\b{re.escape(s)}\b", task["text"], re.I) for s in spellings)


def _carried_by(task: dict, carries: list[list[str]], among: list[list[str]]) -> str:
    """One downstream task against what it should have been handed: `carried` — it names what was
    found and none of the other candidates; `shotgun` — it names what was found AND others it was
    found among, which is asking about everything rather than about the finding; `wrong_name`;
    `unreadable`."""
    named = [_names(task, c) for c in carries]
    if any(n is None for n in named):
        return "unreadable"
    if not all(named):
        return "wrong_name"
    found = {c[0] for c in carries}
    others = [c for c in among if c[0] not in found and _names(task, c)]
    return "shotgun" if others else "carried"


def expected_handoff(expect: dict, rows: list[dict]) -> str:
    """What became of the handoff a question was WRITTEN to need (docs/spikes/v1/questions_cross_family
    .json, `handoff`), read off the turns of its conversation.

      carried            the analyst downstream was asked AFTER the one upstream came back, and about
                         what it found (a figure-level join: a later ask carries a row's id)
      shotgun            asked afterwards about what was found and about the others it was found
                         among: everything was asked, so nothing was carried
      wrong_name         asked afterwards, about something else
      up_front           asked before the finding could have come back: the lead did not wait for it
      never_asked        the family downstream was not asked at all
      upstream_never_asked, not_carried, unreadable — as they say
    `+re_asked` on a conversation of two turns: the second turn went back upstream for what the
    first had already found."""
    kind, to = expect.get("kind"), expect.get("to")
    carries, among = list(expect.get("carries") or []), list(expect.get("among") or [])
    if kind == "figure":
        asks = [a for r in rows for a in r["_asks"]]
        later = [x for ask in asks[1:] for x in ask]
        if any(x["text"] and _FACT_ID.search(x["text"]) for x in later):
            return "carried"
        return "unreadable" if later and all(x["text"] is None for x in later) else "not_carried"
    frm = expect.get("from")
    if kind == "name_across_turns":
        asks, before = (rows[-1]["_asks"] if rows else []), 0
        upstream = any(x["analyst"] == frm for r in rows[:-1] for ask in r["_asks"] for x in ask)
    else:
        asks = [a for r in rows for a in r["_asks"]]
        at = next((i for i, ask in enumerate(asks) if any(x["analyst"] == frm for x in ask)), None)
        upstream, before = at is not None, (at + 1 if at is not None else 0)
    if not upstream:
        return "upstream_never_asked"
    down = [x for ask in asks[before:] for x in ask if x["analyst"] == to]
    if not down:
        early = any(x["analyst"] == to for ask in asks[:before] for x in ask)
        return "up_front" if early else "never_asked"
    got = [_carried_by(x, carries, among) for x in down]
    out = next(o for o in ("carried", "shotgun", "unreadable", "wrong_name") if o in got)
    if kind == "name_across_turns" and any(x["analyst"] == frm for ask in asks for x in ask):
        out += "+re_asked"
    return out


def classify(summary: str, status: str) -> str | None:
    s = summary or ""
    if s.startswith("not attempted"):
        return "held"
    if s.startswith("invalid arguments"):
        return "spelling"
    m = _ERR.match(s)
    if not m:
        return "error" if status == "error" else None
    code = m.group(1)
    for name, members in (("spelling", SPELLING), ("gate", GATE), ("algebra", ALGEBRA),
                          ("data", DATA), ("system", SYSTEM)):
        if code in members:
            return name
    return f"other:{code}"


def tally(paths: list[str], questions: str | None = None) -> dict:
    """`questions`: the file the round was asked from, when its entries say which handoff each was
    written to need (`handoff`); the round is then also read for what became of each."""
    c: collections.Counter = collections.Counter()
    turns_with: dict[str, set] = collections.defaultdict(set)
    rt, calls, resp, elapsed, ptok, figs = [], [], [], [], [], []
    reqs, terrs, writer, answer_refusals = [], 0, 0, 0
    artifacts = marks = zero = exhausted = 0
    superl = superl_no_rank = superl_undeclared = 0
    # V36
    lead_rt, sub_rt, delegates, lead_peak = [], [], [], []
    analysts = submits = submits_rejected = boundaries = delegates_rejected = read_reports = 0
    analyst_status: collections.Counter = collections.Counter()
    # V37: one row per domain — what it was asked, what it settled, what it spent
    # and how its programs came back. See runs_by_domain() for why.
    by_domain: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    report_status: collections.Counter = collections.Counter()
    handoff: collections.Counter = collections.Counter()
    coverage: collections.Counter = collections.Counter()
    evidence_handoff_counts: collections.Counter = collections.Counter()
    legacy_coverage_tasks = 0
    # V1
    sub_peak, per_task_calls, why_words = [], [], []
    why_missing = why_lines = v1_calls = v1_refused = v1_not_run = v1_unstated = 0
    by_rule: collections.Counter = collections.Counter()
    by_reason: collections.Counter = collections.Counter()
    by_channel: collections.Counter = collections.Counter()     # V2 P1.1: finding / caveat / why / follow_up / answer
    absences: collections.Counter = collections.Counter()
    absences_by_verb: collections.Counter = collections.Counter()
    models: dict[str, collections.Counter] = {"lead": collections.Counter(), "analysts": collections.Counter()}
    by_analyst: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    handoffs: list[dict] = []                   # V1, cross-family: one row a turn, in the order asked
    n = 0
    for p in paths:
        for conv in json.loads(Path(p).read_text()):
            for t in conv.get("turns", []):
                n += 1
                handoffs.append(handoff_of(str(conv.get("tag")), t))
                tid = f"{conv.get('tag')}#{t.get('turn')}#{p}"
                steps = t.get("steps", [])
                llm = [s for s in steps if s.get("step_type") == "llm_call"]
                rt.append(len(llm)); ptok.append(sum((s.get("prompt_tokens") or 0) for s in llm))
                calls.append(sum(1 for s in steps if s.get("step_type") in ("tool_call", "delegation")))
                # V33: the analyst's exit is an `answer` step; `respond` is the
                # research path's and every round before. One series, both names.
                resp.append(sum(1 for s in steps if s.get("tool_name") in ("respond", "answer")))
                reqs.append(sum(1 for s in steps if s.get("step_type") == "request"))
                terrs += sum(1 for s in steps if s.get("tool_name") == "run"
                             and (s.get("result") or "").startswith("error: type_errors"))
                answer_refusals += sum(1 for s in steps if s.get("step_type") == "answer" and s.get("status") == "rejected")
                # V36: who spent the completions, and what the handoff saw. An
                # actor-less llm_call is the lead's (every row before V36, and
                # the lead's own rows after it).
                lead = [s for s in llm if not str(s.get("actor") or "").startswith("sub:")]
                lead_rt.append(len(lead)); sub_rt.append(len(llm) - len(lead))
                delegates.append(sum(1 for s in steps if s.get("step_type") == "delegate" and s.get("status") != "rejected"))
                delegates_rejected += sum(1 for s in steps if s.get("step_type") == "delegate" and s.get("status") == "rejected")
                read_reports += sum(1 for s in steps if s.get("step_type") == "read_report")
                boundaries += sum(1 for s in steps if s.get("step_type") == "boundary")
                for s in steps:
                    if s.get("step_type") != "brief":
                        continue
                    submits += 1
                    if s.get("status") == "rejected":
                        submits_rejected += 1
                        hm = _HANDOFF.match(s.get("result") or "")
                        handoff[hm.group(1) if hm else "unstated"] += 1
                elapsed.append(t.get("elapsed_s") or 0)
                meta = t.get("meta") or {}
                figs.append((meta.get("verified") or {}).get("figures") or 0)
                writer += int(meta.get("writer_calls") or 0)
                # V36: the lead's meta names every analyst it ran and every report filed
                for d in meta.get("delegations") or []:
                    analysts += 1
                    analyst_status[d.get("status") or "unstated"] += 1
                    h = d.get("handoff") or {}
                    if h.get("protocol") == "evidence-v2":
                        evidence_handoff_counts["tasks"] += 1
                        for key in ("selected_evidence", "available_evidence", "accepted_notes", "rejected_items"):
                            evidence_handoff_counts[key] += int(h.get(key) or 0)
                    elif d.get("coverage"):
                        legacy_coverage_tasks += 1
                    # one series under two spellings: V36 filed lines `done / not_done`, V1 `settled / unsettled`
                    cov = d.get("coverage") or {}
                    cov = {"asked": cov.get("asked"), "refused": cov.get("refused"),
                           "done": cov.get("done", cov.get("settled")), "not_done": cov.get("not_done", cov.get("unsettled"))}
                    for k in ("asked", "done", "not_done", "refused"):
                        coverage[k] += int(cov.get(k) or 0)
                    dom = by_domain[str(d.get("domain") or "unstated")]
                    dom["delegations"] += 1
                    for k in ("asked", "done", "not_done", "refused"):
                        dom[k] += int(cov.get(k) or 0)
                    if isinstance((d.get("cost") or {}).get("evidence_calls"), int):
                        per_task_calls.append(d["cost"]["evidence_calls"])
                    for k in ("completions", "evidence_calls", "starts"):
                        dom[k] += int((d.get("cost") or {}).get(k) or 0)
                for who, counts in runs_by_domain(steps).items():
                    by_domain[who].update(counts)
                # V1: the calls, the whys, the refusals by rule, the models
                for who, counts in calls_by_analyst(steps).items():
                    by_analyst[who].update(counts)
                    v1_calls += counts["calls"]; v1_refused += counts["refused"]; v1_not_run += counts["not_run"]
                    v1_unstated += counts["unstated"]
                subs = [s.get("prompt_tokens") or 0 for s in llm if str(s.get("actor") or "").startswith("sub:")]
                if subs:
                    sub_peak.append(max(subs))
                for s in llm:
                    m = _MODEL.match(s.get("result") or "")
                    if m:
                        models["analysts" if str(s.get("actor") or "").startswith("sub:") else "lead"][m.group(1)] += 1
                for s in steps:
                    if s.get("step_type") in ("tool_call", "delegation") and str(s.get("actor") or "").startswith("sub:"):
                        why = why_of(s.get("args"))
                        if why is None or not str(why).strip():
                            why_missing += 1
                        else:
                            why_words.append(len(str(why).split()))
                            why_lines += int(bool(_NAMES_A_LINE.search(str(why))))
                        for code in refused_codes(s.get("result") or ""):
                            absences[code] += 1
                            absences_by_verb[str(s.get("tool_name"))] += 1
                    if s.get("step_type") in ("answer", "brief") and s.get("status") == "rejected":
                        for pr in problems_of(s):
                            by_reason[str(pr.get("reason"))] += 1
                            rule = pr.get("rule") if pr.get("rule") is not None else _rule_of(pr.get("reason"))
                            by_rule[str(rule) if rule is not None else "shape"] += 1
                            by_channel[channel_of(pr.get("where"), s.get("step_type"))] += 1
                for r in meta.get("reports") or []:
                    report_status[r.get("status") or "unstated"] += 1
                if isinstance(meta.get("prompt_tokens"), (int, float)):
                    lead_peak.append(meta["prompt_tokens"])
                if meta.get("gate") == "exhausted":
                    exhausted += 1
                a = str(t.get("answer") or "")
                if not a:
                    zero += 1
                if _ARTIFACT.search(a):
                    artifacts += 1
                # the mark is the MODEL's habit: read its last respond prose, not the
                # rendered text (V30 renders a quote's passage with its item in brackets)
                written = a
                for s in reversed(steps):
                    if s.get("tool_name") in ("respond", "answer"):
                        try:
                            arg = json.loads(s.get("args") or "{}")
                            pr = arg.get("prose") or arg.get("text") or ""
                            written = " ".join(pr) if isinstance(pr, list) else str(pr)
                        except (ValueError, TypeError):
                            pass
                        break
                if _MARK.search(written):
                    marks += 1
                if _SUPERLATIVE.search(a):
                    superl += 1
                    # DID THIS TURN COMPUTE AN ORDERING? Asked of each producer in
                    # the terms that producer declares, never of a serialised
                    # program read as a string:
                    #   run     — the executor types every node at birth and the
                    #             step records `| nodes: name=kind`
                    #             (tools/registry._declared_nodes).
                    #   compute — one call is one op and the call IS the
                    #             declaration; its longest argument list across
                    #             both V26 rounds is 298 characters, so this
                    #             protocol never met the battery's cut.
                    # A `run` step recorded before the declaration existed is
                    # neither ranked nor unranked. It is UNDECLARED and is kept
                    # out of superlative_without_rank, because the reading it
                    # would otherwise get — grepping the program for '"fn": "rank"'
                    # — is what reported 37 of 52 on V26_C3 where the full
                    # arguments say 14. An instrument that cannot see says so.
                    done = [s for s in steps if s.get("status") == "completed"
                            and not (s.get("result") or "").startswith("error")]
                    runs = [s for s in done if s.get("tool_name") == "run"]
                    declared = [s for s in runs if _NODES.search(s.get("result") or "")]
                    ranked = (any(_RANK_NODE.search(s.get("result") or "") for s in declared)
                              or any(_RANK_OP.search((s.get("args") or "").replace("'", '"'))
                                     for s in done if s.get("tool_name") == "compute"))
                    if ranked:
                        pass
                    elif len(declared) < len(runs):
                        superl_undeclared += 1
                    else:
                        superl_no_rank += 1
                for s in steps:
                    if s.get("step_type") not in ("tool_call", "delegation", "respond", "answer"):
                        continue
                    k = classify(s.get("result") or "", s.get("status") or "")
                    # V1: a call that came back with refusals among its rows names each by code
                    for k in ([k] if k else []) + [class_of(code) for code in refused_codes(s.get("result") or "")]:
                        c[k] += 1
                        turns_with[k].add(tid)
    med = lambda xs: statistics.median(xs) if xs else 0
    q = lambda xs, pp: sorted(xs)[int(pp * (len(xs) - 1))] if xs else 0
    out = {
        "turns": n, "no_answer": zero, "gate_exhausted": exhausted,
        "round_trips_median": med(rt), "round_trips_p90": q(rt, .9),
        "tool_calls_median": med(calls), "tool_calls_p90": q(calls, .9),
        "respond_attempts_mean": round(statistics.mean(resp), 2) if resp else 0,
        # V33: what the analyst asked for, what the writer's programs were refused for, how often it wrote
        "requests_mean": round(statistics.mean(reqs), 2) if reqs else 0,
        "type_errors": terrs, "writer_calls": writer, "answer_refusals": answer_refusals,
        "prompt_tokens_median": med(ptok), "prompt_tokens_p90": q(ptok, .9),
        "elapsed_s_median": med(elapsed), "elapsed_s_p90": q(elapsed, .9),
        "figures_median": med(figs),
        "answers_with_double_figure_artifact": artifacts,
        "answers_with_passage_mark_as_figure": marks,
        "superlative_claims": superl, "superlative_without_rank": superl_no_rank,
        # turns this instrument cannot answer for: a `run` step from a round
        # recorded before the node declaration existed. Not zero and not a miss —
        # the coverage of the number above.
        "superlative_rank_undeclared": superl_undeclared,
        # V36: delegation, coverage, the handoff, the reports, completions by agent
        "delegate_calls_mean": round(statistics.mean(delegates), 2) if delegates else 0,
        "delegates_rejected": delegates_rejected, "read_reports": read_reports,
        "analysts": analysts,
        "analysts_by_status": dict(sorted(analyst_status.items())),
        "coverage": {k: coverage[k] for k in ("asked", "done", "not_done", "refused")},
        "legacy_coverage_tasks": legacy_coverage_tasks,
        "evidence_handoffs": dict(evidence_handoff_counts),
        "coverage_done_share": (round(coverage["done"] / coverage["asked"], 2) if coverage["asked"]
                                else None if evidence_handoff_counts["tasks"] else 0),
        "submits": submits, "submits_rejected": submits_rejected,
        "submits_per_analyst": round(submits / analysts, 2) if analysts else 0,
        "handoff_refusals": dict(sorted(handoff.items())),
        "reports_by_status": dict(sorted(report_status.items())),
        "boundaries_minted": boundaries,
        "by_domain": {d: dict(c) for d, c in sorted(by_domain.items())},
        "lead_completions_median": med(lead_rt), "sub_completions_median": med(sub_rt),
        "sub_completions_total": sum(sub_rt),
        "lead_prompt_peak_median": med(lead_peak), "lead_prompt_peak_p90": q(lead_peak, .9),
        "refusals": {k: {"count": v, "turns": len(turns_with[k]),
                         "per_turn": round(v / n, 2) if n else 0} for k, v in sorted(c.items())},
        # V1 (plan step 7)
        "tasks_per_turn_mean": round(analysts / n, 2) if n else 0,
        "evidence_calls_per_task_median": med(per_task_calls), "evidence_calls_per_task_p90": q(per_task_calls, .9),
        "analyst_calls": v1_calls, "analyst_calls_refused": v1_refused, "analyst_calls_not_run": v1_not_run,
        # of the calls whose step says how they came back (the first V1 turns' steps do not)
        "analyst_calls_refused_share": (round((v1_refused + v1_not_run) / (v1_calls - v1_unstated), 2)
                                        if v1_calls > v1_unstated else 0),
        "why_words_median": med(why_words), "why_missing": why_missing,
        "why_names_a_line_share": round(why_lines / len(why_words), 2) if why_words else 0,
        "analyst_prompt_peak_median": med(sub_peak), "analyst_prompt_peak_p90": q(sub_peak, .9),
        "check_problems_by_rule": dict(sorted(by_rule.items())),
        "check_problems_by_channel": dict(by_channel.most_common()),
        "sense_conflicts": by_reason["sense_conflict"], "status_conflicts": by_reason["status_conflict"],
        "check_problems_by_reason": dict(by_reason.most_common()),
        "absences": sum(absences.values()), "absences_by_code": dict(absences.most_common()),
        "absences_by_verb": dict(absences_by_verb.most_common()),
        "absences_arithmetic_share": round(sum(v for code, v in absences.items() if class_of(code) == "algebra")
                                           / sum(absences.values()), 2) if absences else 0,
        "absences_from_calc": sum(absences_by_verb[v] for v in ARITHMETIC_VERBS),
        "completions_by_model": {k: dict(v.most_common()) for k, v in models.items()},
        "by_analyst": {a: dict(cn) for a, cn in sorted(by_analyst.items())},
    }
    # V1, cross-family (plan step 7): the turns by how they reached their families, and what each
    # shape cost and came to — the comparison that says whether going through the lead is the cost
    by_shape = {}
    for shape in SHAPES:
        rows = [r for r in handoffs if r["shape"] == shape]
        if not rows:
            continue
        asked = sum(r["asked"] for r in rows)
        by_shape[shape] = {
            "turns": len(rows), "asks_mean": round(statistics.mean(r["asks"] for r in rows), 2),
            "lead_completions_median": med([r["lead_completions"] for r in rows]),
            "evidence_calls_median": med([r["evidence_calls"] for r in rows]),
            "elapsed_s_median": med([r["elapsed_s"] for r in rows]),
            "settled_share": round(sum(r["settled"] for r in rows) / asked, 2) if asked else 0,
            "answers_not_accepted": sum(1 for r in rows if r["answer"] != "accepted"),
            "empty_returns": sum(r["empty_returns"] for r in rows),
            "re_pulls": sum(r["re_pulls"] for r in rows), "budget_stops": sum(r["budget_stops"] for r in rows)}
    out.update({
        "handoff_shapes": {s: by_shape[s]["turns"] for s in by_shape},
        "handoff_by_shape": by_shape,
        "asks_with_follow_up": sum(r["follow_ups"] for r in handoffs),
        "asks_carrying_ids": sum(r["ids_carried"] for r in handoffs),
        "asks_unreadable": sum(r["unreadable"] for r in handoffs),
        "re_pulled_calls": sum(r["re_pulls"] for r in handoffs),
        "tasks_returned_empty": sum(r["empty_returns"] for r in handoffs),
        "analyst_budget_stops": sum(r["budget_stops"] for r in handoffs),
        "lead_opens": sum(r["opens"] for r in handoffs),
    })
    if questions:
        expect = {str(q.get("tag")): q["handoff"] for q in json.loads(Path(questions).read_text())
                  if isinstance(q.get("handoff"), dict)}
        by_tag: dict[str, list[dict]] = collections.defaultdict(list)
        for r in handoffs:
            by_tag[r["tag"]].append(r)
        became = {tag: expected_handoff(e, by_tag[tag]) for tag, e in expect.items() if tag in by_tag}
        for r in handoffs:
            if r["tag"] in became and r is by_tag[r["tag"]][-1]:
                r["expected"] = became[r["tag"]]
        out["handoffs_expected"] = became
        out["handoffs_expected_by_outcome"] = dict(collections.Counter(became.values()).most_common())
    out["handoff_turns"] = [{k: v for k, v in r.items() if k != "_asks"} for r in handoffs]
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--questions", help="the question file the round was asked from; where an entry says which "
                                        "handoff it was written to need, the round is read for what became of it")
    args = ap.parse_args(argv)
    out = tally(args.traces, questions=args.questions)
    for k, v in out.items():
        if k in ("refusals", "by_domain", "by_analyst", "handoff_by_shape", "handoff_turns", "handoffs_expected"):
            continue
        if isinstance(v, dict):
            print(f"{k:40s} " + (", ".join(f"{kk} {vv}" for kk, vv in v.items()) or "-"))
        else:
            print(f"{k:40s} {v}")
    if out["by_domain"]:
        cols = ("delegations", "asked", "done", "not_done", "refused",
                "completions", "evidence_calls", "starts", "runs", "clean", "type_errors",
                "with_absence", "other_errors")
        print("by domain (a domain the lead keeps reaching for and which cannot execute is a skill problem):")
        print("  " + "domain".ljust(34) + "".join(c[:6].rjust(8) for c in cols))
        for dom, c in sorted(out["by_domain"].items(), key=lambda kv: -kv[1].get("completions", 0)):
            print("  " + dom.ljust(34) + "".join(str(c.get(k, 0)).rjust(8) for k in cols))
    if out["by_analyst"]:
        verbs = sorted({k for c in out["by_analyst"].values() for k in c if k.startswith("verb.")})
        cols = ("calls", "read", "refused", "not_run", "errors", "unstated", *verbs)
        print("by analyst (V1: every call, how it came back, and by verb):")
        print("  " + "analyst".ljust(12) + "".join(c.removeprefix("verb.")[:9].rjust(10) for c in cols))
        for who, c in sorted(out["by_analyst"].items(), key=lambda kv: -kv[1].get("calls", 0)):
            print("  " + who.ljust(12) + "".join(str(c.get(k, 0)).rjust(10) for k in cols))
    if out["handoff_by_shape"]:
        cols = ("turns", "asks_mean", "lead_completions_median", "evidence_calls_median", "elapsed_s_median",
                "settled_share", "answers_not_accepted", "empty_returns", "re_pulls", "budget_stops")
        heads = ("turns", "asks", "lead_cmp", "ev_calls", "elapsed", "settled", "not_acc", "empty_ret", "re_pulls", "bdg_stop")
        print("by shape (V1: how a turn reached its families — `in_sequence` went through the lead between two of them):")
        print("  " + "shape".ljust(14) + "".join(h.rjust(10) for h in heads))
        for shape, v in out["handoff_by_shape"].items():
            print("  " + shape.ljust(14) + "".join(str(v[k]).rjust(10) for k in cols))
        print("by question (the asks in order; what a later ask named that the first did not; what was carried by id):")
        rows = [("question", "t", "asks", "shape", "carried down", "ids", "f-up", "empty", "re-pull", "stops", "settled", "answer", "expected")]
        for r in out["handoff_turns"]:
            rows.append((r["tag"][:36], r["turn"], r["chain"], r["shape"], ",".join(r["later_subjects"]) or "-",
                         r["ids_carried"], r["follow_ups"], r["empty_returns"], r["re_pulls"], r["budget_stops"],
                         f"{r['settled']}/{r['asked']}", r["answer"], r.get("expected", "")))
        widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
        for row in rows:
            print("  " + "  ".join(str(x).ljust(widths[i]) for i, x in enumerate(row)).rstrip())
    print("refusals by class (count / turns / per turn):")
    for k, v in out["refusals"].items():
        print(f"  {k:28s} {v['count']:5d} {v['turns']:5d} {v['per_turn']:6.2f}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
