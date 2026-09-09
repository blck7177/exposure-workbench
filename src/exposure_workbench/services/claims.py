"""Claims (V30 Phase B): the answer is claims about facts, and prose around them.

WHY THIS EXISTS. The V24 answer was prose with fact ids embedded where numbers
go, and a gate that found digits in the prose and looked each one up. What it
could not see was the ROLE a sentence gave a figure: a breach tier read as a
reading, a MONEY figure called days, the same series point on both sides of
"grew from … to …", a superlative with no ordering behind it — every
reader-visible false statement in 242 turns (review 2026-09-09 §2.4). A
claim states the relation explicitly, and the relation has a TYPE the fact's
identity either fits or does not.

    answer = {"claims": [Claim, …], "prose": ["… {c1} … {c2} …", …]}
    Claim  = {"id": "c1", "relation": R, "of": f_…, "against"?: f_…,
              "rows"?: [[f_…]], "span"?: "verbatim words", "title"?: "…"}

Relations and what each requires of the facts it points at (§2.4 of the plan):

    level    one scalar that is a reading, not a tier (warning/breach/limit)
    tier     a threshold the mandate set (warning_level, breach_level, limit_value), said as one
    change   two readings of ONE measure of ONE subject at two different
             periods (of = later, against = earlier), or one node that IS a
             change (yoy/qoq/pct/cagr/subtract)
    versus   one measure on two subjects (MSFT's margin against AAPL's): same measure and unit,
             different subjects — a comparison, which is not a change
    ratio    a quotient (a divided node, whatever its unit) or a ratio method
    rank     one entry of an ordering (a fact carrying its rank)
    room     a check's current value (or the weight it reads) against one of its own tiers; or a
             room_* figure the desk already computed
    absent   an absence fact
    quote    a passage, and words that appear verbatim in it
    series   one series fact (drawn as a chart)
    table    rows of scalar facts (one row per thing compared)

Prose may carry digits (boss, 2026-09-09): every digit token resolves to a
fact's value or identity on the ledger, to a passage a quote claim cites, or
to the user's own question — else `unsourced_figure`. That lookup is
services/ledger's, unchanged. What is new is that a number reaches the reader
THROUGH a claim whenever it is the point of the sentence, so its role is typed.

The renderer emits the block shape the web client already reads (runs of
strings, {fact}, {link}; table rows of {fact} with derived header and labels;
chart with a filled fact), so apps/web is untouched by the cutover.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services.gate import _core, quoted_spans, verify_quotes   # the lookups, unchanged
from exposure_workbench.services.ledger import Ledger

RELATIONS = ("level", "tier", "change", "versus", "ratio", "rank", "room", "absent", "quote", "series", "table")

# THE statement of what a number in prose may be (V30; supersedes gate.PROSE_RULE
# for the chat exit). Handed to the model verbatim: the system prompt and
# respond's description import it.
PROSE_RULE = ("Write {cN} in the prose where claim cN's figure goes; the reader sees the fact's value with its "
              "identity. A number you write out yourself is accepted only when the ledger accounts for it — a "
              "fact's value, its date or window, a quoted passage's words, or a figure from the user's own "
              "question. A figure you worked out yourself has no fact: run a program for it.")

# Tier columns: a figure whose measure ends with one of these is a threshold the
# mandate set, never a reading of the book (X15: "already at 20.0%" was the
# breach tier). Pinned against analytics/resources by test.
TIER_SUFFIXES = ("warning_level", "breach_level", "limit_value")
CHANGE_OPS = ("yoy", "qoq", "pct", "cagr", "subtract")
# Refusals that say the desk did not UNDERSTAND the call: an id naming no object,
# an argument of the wrong shape, an operand of the wrong type. An absence fact
# born of one of these is not an absence the reader can be told — the call is
# fixed and run again (V30 C2, N12: a guessed `port_1` reported to the reader as
# a book with no completed run).
#
# A refusal that names what the desk DOES hold is deliberately NOT here:
# `unknown_name` ("this run holds no column issuer_exposures.quantity; available:
# …"), `unknown_point` ("no point at 2025-03-31; held: …"), `unknown_method`
# ("nearest: …"), `unknown_metric` and `unknown_company` are coverage statements,
# and a reader is entitled to them. The first cut of this list swallowed five
# honest absences in C3's first 36 turns.
# battery_counters.py reads the same set as its "spelling" class.
SPELLING_REFUSALS = frozenset({
    "expand_needs_a_subject", "unknown_expand", "domain_not_for_subject", "invalid_arguments",
    "invalid_params", "unknown_operand", "unknown_portfolio", "unknown_run", "unknown_kind",
    "unknown_tool", "unknown_job", "unknown_primitive", "op_or_method",
    "query_or_item", "operands", "params", "subject_required", "not_a_series", "series_only",
    "not_a_book", "not_a_quantity", "not_a_scenario", "unsupported_op", "unsupported_direction",
    "untyped_operand", "untyped_series", "undated_operand", "not_on_this_face", "too_few_operands",
    "unrankable_operand", "invalid_as_of_date", "invalid_date", "invalid_window", "type_mismatch",
    "malformed_program", "duplicate_binding", "unbound_name",
    # the desk knows the name and it belongs at another door: the call is re-made
    # there, and the reader is told nothing (V30 C3 replay)
    "wrong_door",
})

PLACEHOLDER = re.compile(r"\{(c\d+)\}")

_CLAIM = {"type": "object", "properties": {
    "id": {"type": "string", "description": "c1, c2, … — written into the prose as {c1}"},
    "relation": {"type": "string", "enum": list(RELATIONS)},
    "of": {"type": ["string", "null"], "description": "the fact (f_…) the claim is about"},
    "against": {"type": ["string", "null"], "description": "change: the earlier reading; room: the tier"},
    "rows": {"type": ["array", "null"], "items": {"type": "array", "items": {"type": "string"}},
             "description": "table: rows of fact ids, one row per thing compared, one column per measure"},
    "span": {"type": ["string", "null"], "description": "quote: the words, verbatim from the passage"},
    "title": {"type": ["string", "null"]},
}, "required": ["id", "relation"], "additionalProperties": False}

ANSWER_SCHEMA = {"type": "object", "properties": {
    "claims": {"type": "array", "minItems": 0, "maxItems": 40, "items": _CLAIM,
               "description": "every figure the answer states, each as a typed relation over facts"},
    "prose": {"type": "array", "minItems": 1, "items": {"type": "string"},
              "description": "paragraphs; {c1} marks where claim c1 is rendered"},
}, "required": ["claims", "prose"], "additionalProperties": False}


@dataclass
class Verdict:
    problems: list[dict] = field(default_factory=list)
    error: str | None = None
    detail: str | None = None
    refs: list[str] = field(default_factory=list)
    links: dict[tuple[int, int], dict] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_refusal(self) -> dict:
        return {"error": self.error, "problems": self.problems, "detail": self.detail}


# ── shape ─────────────────────────────────────────────────────────────────────

def validate_shape(answer) -> list[dict]:
    p: list[dict] = []
    if not isinstance(answer, dict):
        return [{"at": "answer", "reason": "not_an_object"}]
    claims, prose = answer.get("claims"), answer.get("prose")
    if isinstance(prose, str) and prose.strip():
        prose = [p for p in prose.split("\n\n") if p.strip()]     # one string is one or more paragraphs
        answer["prose"] = prose
    if not isinstance(claims, list):
        p.append({"at": "claims", "reason": "claims_not_a_list"})
        claims = []
    if not isinstance(prose, list) or not prose or not all(isinstance(x, str) and x.strip() for x in prose):
        p.append({"at": "prose", "reason": "prose_not_paragraphs", "detail": "prose is a non-empty list of paragraph strings"})
        prose = [x for x in (prose or []) if isinstance(x, str)]
    ids: dict[str, int] = {}
    for i, c in enumerate(claims):
        at = f"claims[{i}]"
        if not isinstance(c, dict):
            p.append({"at": at, "reason": "claim_not_an_object"}); continue
        cid, rel = c.get("id"), c.get("relation")
        if not isinstance(cid, str) or not re.fullmatch(r"c\d+", cid):
            p.append({"at": at, "reason": "bad_claim_id", "detail": "ids are c1, c2, …"})
        elif cid in ids:
            p.append({"at": at, "reason": "duplicate_claim_id", "id": cid})
        else:
            ids[cid] = i
        if rel not in RELATIONS:
            p.append({"at": at, "reason": "unknown_relation", "relation": rel, "allowed": list(RELATIONS)}); continue
        if rel == "table":
            rows = c.get("rows")
            if not isinstance(rows, list) or not rows or not all(isinstance(r, list) and r and all(isinstance(x, str) for x in r) for r in rows):
                p.append({"at": at, "reason": "table_without_rows"})
            elif len({len(r) for r in rows}) != 1:
                p.append({"at": at, "reason": "row_width_mismatch"})
        elif rel == "absent" and not c.get("of"):
            p.append({"at": at, "reason": "claim_without_of", "detail": "absent: point at the absence fact (of=f_…) — a refused program node's fact (in the run's facts), or a describe not_held / cannot entry. "
                                                                        "An absence the ledger holds no fact for is not a claim: say it in the prose in your own words, with no {cN} (a claim is what the desk said; the prose is what you say)"})
        elif not isinstance(c.get("of"), str) or not c["of"]:
            p.append({"at": at, "reason": "claim_without_of", "detail": f"a {rel} claim points at a fact: of=f_…"})
        if rel in ("change", "room") and rel == "room" and not isinstance(c.get("against"), str):
            p.append({"at": at, "reason": "room_without_tier", "detail": "room: against = the tier fact (warning or breach)"})
        if rel == "quote" and not (isinstance(c.get("span"), str) and len(c["span"].split()) >= 1):
            p.append({"at": at, "reason": "quote_without_span"})
    used: set[str] = set()
    for i, para in enumerate(prose):
        for m in PLACEHOLDER.finditer(para):
            if m.group(1) not in ids:
                p.append({"at": f"prose[{i}]", "reason": "unknown_placeholder", "id": m.group(1)})
            used.add(m.group(1))
    # a claim the prose does not place is not refused: it stands as what the
    # answer rests on (the V24 `cites`) and is recorded in the citations
    return p


# ── the gate ──────────────────────────────────────────────────────────────────

def _rec(led: Ledger, ref: str | None) -> dict | None:
    """The fact a claim points at. `f_…@period` addresses one point of a series
    (V24's syntax, which the model keeps writing): it resolves to a scalar
    record at that period, and the id stays the series' so the chip opens it."""
    if not ref:
        return None
    base, period = A.split_point(ref)
    rec = led.by_id.get(base)
    if rec is None or period is None:
        return rec
    if rec.get("kind") != F.SERIES:
        return rec if period == rec.get("as_of") else None
    pts = {str(p[0]): float(p[1]) for p in (rec.get("points") or [])}
    if period not in pts:
        return None
    return {**rec, "kind": F.SCALAR, "value": pts[period], "as_of": period, "window": None,
            "params": {**(rec.get("params") or {}), "point": period}}


def _holds(led: Ledger, ref: str) -> bool:
    return _rec(led, ref) is not None


def _is_tier(rec: dict) -> bool:
    m = rec.get("measure") or ""
    return any(m.endswith(s) for s in TIER_SUFFIXES)


def _period_key(rec: dict):
    w = rec.get("window") or {}
    return (w.get("start"), w.get("end")) if isinstance(w, dict) and w.get("end") else (None, rec.get("as_of"))


def _same_measure(a: dict, b: dict) -> bool:
    return (a.get("measure") == b.get("measure") and a.get("unit") == b.get("unit")
            and (a.get("subject") or None) == (b.get("subject") or None))


def _check_relation(c: dict, led: Ledger) -> dict | None:
    rel, of = c["relation"], c.get("of")
    rec = _rec(led, of)
    if rel == "table":
        bad = [x for r in c["rows"] for x in r if (_rec(led, x) or {}).get("kind") != F.SCALAR]
        return {"reason": "kind_does_not_fit", "ids": bad, "detail": "a table cell is a scalar fact (a series point is f_…@period)"} if bad else None
    kind = rec.get("kind") if rec else None
    params = (rec or {}).get("params") or {}
    if kind == F.PASSAGE and rel != "quote":
        # V30 C3: 18 of 25 kind_does_not_fit refusals were a figure relation aimed
        # at a filing passage (`level` on 10-K Item 7). The passage holds words, not
        # a figure, and the relation that fits is the one that carries the words.
        return {"reason": "kind_does_not_fit", "detail": f"{rel}: {of} is a passage of a filing, which holds words and no figure — "
                                                        f"state it with relation 'quote' and the words verbatim in `span`; a figure from it is read with a program"}
    if rel == "level":
        if kind == F.SERIES:
            return None                       # a series' latest reading is a reading; the chip shows it with its period
        if kind != F.SCALAR:
            return {"reason": "kind_does_not_fit", "detail": f"level: a scalar fact; {of} is {kind}"}
        if _is_tier(rec):
            return {"reason": "tier_as_level", "detail": f"{of} ({rec.get('measure')}) is a tier the mandate set, not a reading: "
                                                          f"state it with relation 'tier', or as room (the check's current value against it)"}
        return None
    if rel == "tier":
        if kind != F.SCALAR or not _is_tier(rec):
            return {"reason": "kind_does_not_fit", "detail": f"tier: a warning, breach or limit level; {of} is {rec.get('measure') if rec else kind}"}
        return None
    if rel == "series":
        return None if kind == F.SERIES else {"reason": "kind_does_not_fit", "detail": f"series: a series fact; {of} is {kind}"}
    if rel == "absent":
        if not of:
            # V30 C2 (N12): "the desk has no completed run for port_1" passed as text
            # over a misspelled id. An absence is a fact the desk produced, like
            # any other claim's; the reader is not told one the desk did not say.
            return {"reason": "absence_unsourced", "detail": "absent: `of` is the absence fact — a refused program node (its f_… is in the run's facts), "
                                                          "or a describe not_held / cannot entry; an absence with no fact is a guess"}
        if kind != F.ABSENCE:
            # V30 C3: nine of these. Every refusal names the relation that fits, as
            # the passage and the change refusals above already do.
            fits = "level" if kind == F.SCALAR else ("series" if kind == F.SERIES else "quote" if kind == F.PASSAGE else None)
            return {"reason": "kind_does_not_fit", "detail": f"absent: an absence fact; {of} is {kind}. A figure the desk holds cannot be claimed absent"
                                                            + (f" — state it with relation '{fits}'" if fits else "")}
        err = ((params.get("root") or {}).get("error") if isinstance(params.get("root"), dict) else None) or params.get("error")
        if err in SPELLING_REFUSALS:
            return {"reason": "refused_not_absent", "detail": f"{of} was refused for {err} — an address or argument the desk did not recognise, not a figure it lacks: "
                                                            f"fix the call and run it again; the reader cannot be told this as an absence"}
        return None
    if rel == "quote":
        if kind != F.PASSAGE:
            return {"reason": "kind_does_not_fit", "detail": f"quote: a passage fact; {of} is {kind}"}
        # a span may elide with … or ...; each part of four words or more must be verbatim
        span = re.sub(r"\[[^\]]*\]", "", c.get("span") or "")            # "[and] may fail" — the insertion is the writer's
        parts = [s.strip() for s in re.split(r"…|\.\.\.", span) if len(s.split()) >= 1]
        bad = [s for s in parts if verify_quotes(f"\"{s}\"", [led.passages.get(of, "")])] if parts else [""]
        return {"reason": "unverified_quote", "span": c.get("span"), "detail": f"not verbatim in the passage: {bad[0][:80]!r}"} if bad else None
    if rel == "ratio":
        if kind == F.SERIES:
            return None if rec.get("unit") in ("RATIO", "MULTIPLE") or params.get("op") == "divide" else {"reason": "unit_does_not_fit", "detail": f"ratio: {of} is a {rec.get('unit')} series"}
        if kind != F.SCALAR:
            return {"reason": "kind_does_not_fit", "detail": f"ratio: a scalar fact; {of} is {kind}"}
        if params.get("op") == "divide":
            return None                       # a quotient, whatever the algebra says its unit is (MONEY over a flow is days)
        if rec.get("unit") not in ("RATIO", "MULTIPLE"):
            return {"reason": "unit_does_not_fit", "detail": f"ratio: {of} is {rec.get('unit')} and was not divided; state it as a level"}
        return None
    if rel == "rank":
        if kind != F.SCALAR or "rank" not in params:
            # 37 superlatives a battery rest on no ordering, in every arm and both
            # protocols (V26 R2 37, R3 36, C3 37). The generic sentence has not moved
            # it, so the refusal names the binding the ordering would be built from:
            # the fact knows which node it is an entry of.
            node, label = params.get("node"), params.get("label")
            how = (f' The figure is entry {label!r} of node ${node}: add {{"fn": "rank", "of": "${node}"}} '
                   f'(or "top" with n) to the program and claim its entry.' if node and label else
                   f' A superlative rests on a rank node: compute {{"fn": "rank", "of": <the vector>}} first.')
            return {"reason": "no_ordering", "detail": f"rank: the fact must be an entry of a computed ordering (fn rank / top); {of} carries no rank.{how}"}
        return None
    if rel == "room":
        measure = rec.get("measure") or "" if rec else ""
        if kind == F.SCALAR and ("room_to" in measure or measure.startswith("subtract(")):
            return None                       # already a distance (book.analysis room_*, or warning − current)
        readings = ("current_value", "issuer_exposures.weight", "sector_exposures.weight", "exposure_metrics.gross_exposure_pct",
                    "exposure_metrics.net_exposure_pct")
        if kind != F.SCALAR or not measure.endswith(readings):
            return {"reason": "kind_does_not_fit", "detail": f"room: `of` is the check's current value (or the weight the check reads); {of} is {measure or kind}"}
        tier = _rec(led, c.get("against"))
        if not tier or not _is_tier(tier):
            return {"reason": "no_tier", "detail": "room: `against` is the check's warning or breach tier fact"}
        ts, rs = str(tier.get("subject") or ""), str(rec.get("subject") or "")
        if not (ts == rs or ts.endswith(":" + rs) or rs.endswith(":" + ts)):
            return {"reason": "different_check", "detail": f"room: {of} is {rs}'s reading and {c.get('against')} is {ts}'s tier"}
        return None
    if rel == "versus":
        other = _rec(led, c.get("against"))
        if kind != F.SCALAR or not other or other.get("kind") != F.SCALAR:
            return {"reason": "no_two_readings", "detail": "versus: two scalar facts, of and against"}
        same_measure = rec.get("measure") == other.get("measure")
        same_subject = (rec.get("subject") or None) == (other.get("subject") or None)
        if rec.get("unit") != other.get("unit"):
            return {"reason": "different_measures", "detail": f"versus: {rec.get('unit')} against {other.get('unit')} are not comparable"}
        if same_measure and same_subject and _period_key(rec) != _period_key(other):
            return {"reason": "is_a_change", "detail": "versus compares subjects or measures; the same measure of one subject at two periods is a change"}
        if not same_measure and not same_subject:
            return {"reason": "different_measures", "detail": f"versus: one measure on two subjects, or two measures of one subject; {rec.get('subject')} {rec.get('measure')} against {other.get('subject')} {other.get('measure')} is neither"}
        return None
    if rel == "change":
        if kind == F.SERIES:
            return None                       # first point to last, or a yoy/qoq series; rendered from its ends
        if kind == F.SCALAR and params.get("op") in CHANGE_OPS:
            if not c.get("against"):
                return None                   # the node IS the move
            against = _rec(led, c.get("against"))
            base = (rec.get("measure") or "").rsplit(".", 1)[0]
            if not against or against.get("kind") != F.SCALAR:
                return {"reason": "kind_does_not_fit", "detail": f"change: {of} already is the move (a {params.get('op')} node) — leave `against` out, "
                                                               f"or make it the earlier reading of {base} it moved from (a scalar, f_…@period)"}
            if against.get("id") == rec.get("id") and against.get("as_of") == rec.get("as_of"):
                # V30 C2 (N01 t2): rendered "6.50% (2026-01-25) from 6.50% (2026-01-25)"
                return {"reason": "same_figure", "detail": f"change: `against` is {of} itself; a {params.get('op')} node needs no `against` — "
                                                          f"leave it out, or point it at the earlier reading of {base}"}
            if against.get("measure") not in (base, rec.get("measure")) or (against.get("subject") or None) != (rec.get("subject") or None):
                return {"reason": "different_measures", "detail": f"change: {of} is {rec.get('subject')} {rec.get('measure')}; `against` is "
                                                                 f"{against.get('subject')} {against.get('measure')}, not the reading it moved from"}
            return None
        against = _rec(led, c.get("against"))
        if kind != F.SCALAR or not against or against.get("kind") != F.SCALAR:
            return {"reason": "no_two_readings", "detail": "change: two readings of one measure (of = later, against = earlier; a series point is f_…@period), a series, or a yoy/qoq/subtract node"}
        if not _same_measure(rec, against):
            # C3: six "rolling_vol_30d against rolling_vol_60d" — two measures of one subject is a versus, and the refusal says so
            return {"reason": "different_measures", "detail": f"change: {rec.get('subject')} {rec.get('measure')} against {against.get('subject')} {against.get('measure')} are not one measure of one subject at two dates; "
                                                              f"two measures of one subject, or one measure of two subjects, is relation 'versus'"}
        if _period_key(rec) == _period_key(against):
            return {"reason": "same_period", "detail": f"change: both readings are at {rec.get('as_of')} — the same figure twice is not a change"}
        return None
    return None


def _absence_candidates(led: Ledger, n: int = 8) -> list[dict]:
    """The absence facts on the ledger a claim may point at, newest last: id,
    the node or name, the refusal it was born of, and whether it can back an
    absence (a spelling-class refusal cannot)."""
    out = []
    for rec in led.by_id.values():
        if rec.get("kind") != F.ABSENCE:
            continue
        params = rec.get("params") or {}
        err = ((params.get("root") or {}).get("error") if isinstance(params.get("root"), dict) else None) or params.get("error")
        out.append({"id": rec["id"], "about": params.get("node") or rec.get("measure"), "refusal": err,
                    "citable": err not in SPELLING_REFUSALS, "text": (rec.get("text") or "")[:140]})
    return out[-n:]


def check(answer: dict, led: Ledger, question: str | None = None) -> Verdict:
    v = Verdict()
    shape = validate_shape(answer)
    if shape:
        # an absent claim with no fact: the refusal carries the absence facts this
        # session's ledger holds (C3 showed the model dropping the absence in 7 of
        # 10 turns rather than finding the id), the way unknown_portfolio carries
        # the ids — a fact the desk produced is what the reader can be told
        absences = _absence_candidates(led)
        for p in shape:
            if p.get("reason") == "claim_without_of" and "absent" in (p.get("detail") or "") and absences:
                p["absences_on_ledger"] = absences
        v.error, v.problems = "malformed_answer", shape
        v.detail = "an answer is {claims: [{id, relation, of, …}], prose: [paragraphs with {cN}]}"
        return v
    claims: dict[str, dict] = {c["id"]: c for c in answer["claims"]}
    # G1 — every fact pointed at is on this session's ledger
    pointed = []
    for c in answer["claims"]:
        for k in ("of", "against"):
            if isinstance(c.get(k), str) and c[k]:
                pointed.append((c["id"], c[k]))
        for r in c.get("rows") or []:
            pointed += [(c["id"], x) for x in r]
    off = [(cid, fid) for cid, fid in pointed if not _holds(led, fid)]
    v.refs = list(dict.fromkeys(A.split_point(f)[0] for _, f in pointed))
    if off:
        v.error, v.problems = "not_on_ledger", [{"at": cid, "id": fid, "reason": "not_on_ledger"} for cid, fid in off]
        v.detail = "every id an answer points at is a fact a tool result showed this session (f_… in a facts block)"
        return v
    # G2 — the relation fits the facts' identity
    for c in answer["claims"]:
        bad = _check_relation(c, led)
        if bad:
            v.problems.append({"at": c["id"], "relation": c["relation"], **bad})
    if v.problems:
        v.error = "relation_does_not_fit"
        v.detail = "a claim's relation must fit what its facts are: " + "; ".join(f"{p['at']}: {p['reason']}" for p in v.problems)
        return v
    # G3 — digits in the prose account to the ledger, a quoted passage or the question
    asked = {_core(t["token"]) for t in A.tokens_in(question or "")}
    cited_passages = [c["of"] for c in answer["claims"] if c["relation"] == "quote"]
    for i, para in enumerate(answer["prose"]):
        text = _blank_placeholders(para)
        for t in A.tokens_in(text):
            tok, kind = t["token"], t["kind"]
            if kind == "id":
                v.problems.append({"at": f"prose[{i}]", "reason": "id_in_prose", "id": tok,
                                   "detail": "a fact is stated through a claim ({cN}), never by its id"})
                continue
            ids = led.resolve_number(tok) if kind == "num" else []
            if not ids:
                ids = led.resolve_identity(tok)
            if ids:
                v.links[(i, t["start"])] = {"to": "fact", "ids": ids, "as_written": tok}
                continue
            pids = led.resolve_in_passages(tok, cited_passages)
            if pids:
                v.links[(i, t["start"])] = {"to": "passage", "ids": pids, "as_written": tok}
                continue
            if _core(tok) in asked:
                v.links[(i, t["start"])] = {"to": "question", "ids": [], "as_written": tok}
                continue
            v.problems.append({"at": f"prose[{i}]", "reason": "unsourced_figure", "figure": tok,
                               "detail": "a number the ledger cannot account for: state it through a claim, quote the passage that says it, or drop it"})
        for q in verify_quotes(text, [led.passages[p] for p in cited_passages if p in led.passages]):
            v.problems.append({"at": f"prose[{i}]", **q, "reason": "unverified_quote"})
    if v.problems:
        reasons = {p["reason"] for p in v.problems}
        v.error = "unsourced_figure" if "unsourced_figure" in reasons else "id_in_prose" if "id_in_prose" in reasons else "unverified_quote"
        v.detail = {"unsourced_figure": "every number in the prose is a fact's value or date on the ledger, a quoted passage's words, or the user's own figure",
                    "id_in_prose": "write {cN} where a figure goes; the id belongs in the claim",
                    "unverified_quote": "quotation marks say these words are verbatim in a passage a quote claim cites"}[v.error]
    return v


def _blank_placeholders(text: str) -> str:
    return PLACEHOLDER.sub(lambda m: " " * len(m.group(0)), text)


# ── rendering: the shape the web client reads ─────────────────────────────────

def _runs_for(c: dict, led: Ledger) -> list:
    rel = c["relation"]
    rec = _rec(led, c.get("of")) or {"id": c.get("of")}
    if rel == "change" and rec.get("kind") == F.SERIES and not c.get("against"):
        pts = sorted((str(p[0]), float(p[1])) for p in (rec.get("points") or []))
        if len(pts) >= 2:
            first = {**rec, "kind": F.SCALAR, "value": pts[0][1], "as_of": pts[0][0], "window": None}
            last = {**rec, "kind": F.SCALAR, "value": pts[-1][1], "as_of": pts[-1][0], "window": None}
            return ["from ", {"fact": A.fill(first)}, " to ", {"fact": A.fill(last)}]
    if rel == "versus" and _rec(led, c.get("against")):
        return [{"fact": A.fill(rec)}, " against ", {"fact": A.fill(_rec(led, c["against"]))}]
    if rel == "change" and isinstance(c.get("against"), str) and _rec(led, c["against"]):
        a, b = _rec(led, c["against"]), rec
        if (rec.get("params") or {}).get("op") in CHANGE_OPS:
            # `of` IS the change (a delta or a yoy node); `against` is what it moved from
            return [{"fact": A.fill(rec)}, " from ", {"fact": A.fill(a)}]
        earlier, later = (a, b) if (a.get("as_of") or "") <= (b.get("as_of") or "") else (b, a)
        return ["from ", {"fact": A.fill(earlier)}, " to ", {"fact": A.fill(later)}]
    if rel == "room" and isinstance(c.get("against"), str) and _rec(led, c["against"]):
        return [{"fact": A.fill(rec)}, " against ", {"fact": A.fill(_rec(led, c["against"]))}]
    if rel == "quote":
        return [f"“{c.get('span', '')}” ", {"fact": A.fill(rec)}]
    if rel == "tier":
        m = (rec.get("measure") or "").rsplit(".", 1)[-1].replace("_level", "").replace("limit_value", "limit")
        return [f"the {m} tier of ", {"fact": A.fill(rec)}]
    if rel == "rank":
        r = (rec.get("params") or {}).get("rank")
        return [{"fact": A.fill(rec)}, f" (#{r})"] if r else [{"fact": A.fill(rec)}]
    if rel == "table":
        return ["the table below"]
    if rel == "series":
        return ["the chart below"]
    return [{"fact": A.fill(rec)}]


def rendered(answer: dict, led: Ledger, links: dict[tuple[int, int], dict]) -> list[dict]:
    claims = {c["id"]: c for c in answer["claims"]}
    blocks: list[dict] = []
    for i, para in enumerate(answer["prose"]):
        marks: list[tuple[int, int, str, object]] = []
        for m in PLACEHOLDER.finditer(para):
            marks.append((m.start(), m.end(), "claim", m.group(1)))
        for (pi, s), link in links.items():
            if pi == i and link["to"] != "question":
                marks.append((s, s + len(link["as_written"]), "link", link))
        marks.sort(key=lambda m: m[0])
        runs: list = []
        pos = 0
        for s, e, kind, payload in marks:
            if s < pos:
                continue
            if s > pos:
                runs.append(para[pos:s])
            if kind == "claim":
                runs += _runs_for(claims[payload], led)
            else:
                runs.append({"link": {"to": payload["to"], "ids": payload["ids"], "as_written": para[s:e]}})
            pos = e
        if pos < len(para):
            runs.append(para[pos:])
        blocks.append({"type": "paragraph", "runs": runs})
    for c in answer["claims"]:
        if c["relation"] == "table":
            grid = [[A.fill(_rec(led, x)) for x in row] for row in c["rows"]]
            b = {"type": "table", "rows": [[{"fact": f} for f in row] for row in grid], **A.derive_table(grid)}
            if c.get("title"):
                b["title"] = c["title"]
            blocks.append(b)
        elif c["relation"] == "series":
            b = {"type": "chart", "kind": "line", "fact": A.fill(led.by_id[c["of"]])}
            if c.get("title"):
                b["title"] = c["title"]
            blocks.append(b)
    return blocks


def accepted(answer: dict, verdict: Verdict, led: Ledger) -> dict:
    blocks = rendered(answer, led, verdict.links)
    linked = [fid for l in verdict.links.values() for fid in l["ids"]]
    facts_used = list(dict.fromkeys([*verdict.refs, *linked]))
    figures = [led.by_id[f] for f in facts_used if f in led.by_id and led.kind(f) in (F.SCALAR, F.SERIES)]
    passages = [f for f in facts_used if led.kind(f) == F.PASSAGE]
    return {"blocks": blocks, "text": A.prose_of(blocks), "citations": facts_used,
            "claims": answer["claims"],
            "verified": {"figures": len(figures), "sources": len(passages),
                         "matches": [{"label": r.get("measure"), "value": r.get("value"), "unit_class": r.get("unit"),
                                      "source_id": r["id"], "subject": r.get("subject"), "as_of": r.get("as_of")} for r in figures]}}
