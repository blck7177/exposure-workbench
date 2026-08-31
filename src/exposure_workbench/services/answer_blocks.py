"""V14-C. The exit's vocabulary: an answer is blocks, and a figure is a slot.

WHY THIS EXISTS. Until now the model wrote prose with numbers in it and the gate
read the numbers back out. That put the model in the position of a transcriber:
it had already been handed 0.800770 by a tool, and its job was to copy the digits
into a sentence without dropping one. Every failure of that copy is a refusal,
and a refusal costs a turn — sess_16b176ea4c9b spent five of its nine model calls
negotiating with the gate over figures it had already been given correctly.

So the numbers stop being written. A figure in an answer is a SLOT: a reference
to a row in the ledger, resolved to its value at render time. Text may not carry
a substantive number at all, which is the invariant the whole design rests on —
there is nothing to transcribe, so there is nothing to transcribe wrongly. The
class of error is gone rather than checked.

Two things follow that the prose exit could not do. Presentation stops being the
model's business: the ledger holds 0.8007699, the reader sees 0.80, and neither
is a claim the model made. And structure becomes possible — a table's cell and a
chart's series are slots like any other, so a ranked table is expressible and a
picture of a series cannot be drawn from numbers nobody recorded.

A slot names its value one of two ways, and this is a migration, not a
preference. `label` is the ledger's own name for the value and writes no number
at all. `value` is the figure as read from the tool payload, which is what a
model can author on its first attempt without having been taught the label
vocabulary; it is checked against that ONE ref rather than against the pool of
everything cited, and what gets rendered is still the ledger's value and not the
model's copy. Refusals name the labels available under the ref, so the second
attempt can use the stronger form. Both are exact; neither is a fallback for the
other failing.

WHAT IS NOT HERE. `action` — "the research you kicked off" — is checkable, and
trajectory_gate's R2 already checks it: a turn that enqueues runs and names none
is refused there. A second implementation would be a second opinion about the
same turn, and this codebase has been bitten by mirrored rules more than once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from exposure_workbench.services import numeric_verification as nv

# The closed vocabulary. A block whose type is not here is refused rather than
# ignored: an exit that silently drops what it does not understand is an exit
# that can be talked past.
BLOCK_TYPES = ("paragraph", "metric_table", "chart", "trend", "absence")

# Chart kinds, closed for the same reason and short on purpose. Each is a way of
# reading a series or a set of figures that the renderer knows how to draw; a
# kind nobody can draw is a promise the answer cannot keep.
CHART_KINDS = ("bar", "line", "waterfall")

# Ledger operations whose rows carry a series of points rather than one figure.
# A trend claim rests on one of these — "it has been rising" is a statement about
# a sequence, and the sequence has to exist. This is the first of round 4's three
# assertion checks: the risk-history answer that said VaR had been climbing for a
# month, from a library holding exactly one run, drew zero refusals twice.
_SERIES_OPS = ("series", "flow.series", "balance.series", "change.")

# Absence rows. V11 minted these so that "the issuer does not report this" could
# be cited like anything else; until now nothing required an absence CLAIM to
# rest on one, so the model could simply assert a company files nothing and the
# gate — which checks numbers — saw a sentence with no numbers in it and passed.
_ABSENCE_PREFIX = "absence."


@dataclass(frozen=True)
class Resolved:
    """One slot, after the ledger has been consulted.

    `label` is always the ledger's, never the model's: a slot authored by value
    is resolved to the row that holds it and takes that row's name. So a reader
    hovering a figure is shown what the ledger calls it, whichever way the slot
    was written.
    """

    ref: str
    label: str
    value: float
    unit_class: str


def _is_slot(x) -> bool:
    return isinstance(x, dict)


def _slot_problem(slot: dict, i: str) -> dict | None:
    """Shape errors, before anything is looked up.

    Reported all at once and per slot, because a model fixing one slot at a time
    is the ratchet this batch exists to remove.
    """
    if not isinstance(slot.get("ref"), str) or not slot["ref"]:
        return {"at": i, "reason": "slot_without_ref",
                "detail": "a slot names the evidence id its figure comes from"}
    has_label = isinstance(slot.get("label"), str) and slot["label"] != ""
    has_value = isinstance(slot.get("value"), (int, float)) and not isinstance(slot.get("value"), bool)
    # A slot holds ONE NUMBER, and the first thing the exit met in the wild was
    # slots holding sentences — an alert's whole reads_as line, an id, a ticker,
    # a date — because "a reference to evidence" is what a slot looks like from
    # outside. It is not: a reference to evidence is what a REF is, and the slot
    # exists to carry the one figure that ref holds. So the refusal says which
    # kind of thing was passed rather than reporting it as missing, because a
    # model told "give the slot a value" when it gave one learns nothing.
    if isinstance(slot.get("value"), str):
        return {"at": i, "ref": slot["ref"], "reason": "slot_value_is_text",
                "value": slot["value"][:80],
                "detail": "a slot carries one number and nothing else. Words — an id, a "
                          "ticker, a date, a whole sentence — are written as text in the "
                          "run beside it; only the figure goes in the slot"}
    if has_label and has_value:
        return {"at": i, "ref": slot["ref"], "reason": "slot_with_both",
                "detail": "name the value either by label or by figure, not both — "
                          "two names for one slot can disagree"}
    if not has_label and not has_value:
        return {"at": i, "ref": slot["ref"], "reason": "slot_without_value",
                "detail": "give the slot a label (the ledger's name for the figure) "
                          "or a value (the figure as the tool returned it, as a "
                          "number). If what you are placing is not a figure, it is "
                          "text and belongs in the run beside the slot"}
    return None


def _decimals_of(v: float) -> int:
    """How precisely the figure was written.

    repr gives the shortest string that round-trips, which is the authored form
    for anything a model types: 0.16 stays 0.16 and does not become 0.1600000001.
    The tolerance that follows is the gate's own — half an ulp of the precision
    WRITTEN — so a slot authored to two places is held to two places, exactly as
    a figure in prose was.
    """
    s = repr(float(v))
    if "e" in s or "E" in s:
        return 12
    return len(s.split(".")[1]) if "." in s else 0


def resolve_slot(slot: dict, by_ref: dict[str, list[nv.EvidenceValue]], at: str) -> tuple[Resolved | None, dict | None]:
    """One slot against the values its ref holds."""
    ref = slot["ref"]
    holds = by_ref.get(ref, [])
    if not holds:
        return None, {
            "at": at, "ref": ref, "reason": "ref_holds_no_figures",
            "detail": "this id carries no numeric value. A passage or a source is "
                      "cited for what it says, not slotted for a figure",
        }

    if isinstance(slot.get("label"), str) and slot["label"]:
        for v in holds:
            if v.label == slot["label"]:
                return Resolved(ref, v.label, v.value, v.unit_class), None
        return None, {
            "at": at, "ref": ref, "reason": "unknown_label",
            "label": slot["label"],
            # The whole list, not the nearest few. A refusal that names some of
            # the options is a refusal the model answers by guessing again, and
            # guessing again is the ratchet. Capped only where a run's own
            # children run to the hundreds, and the cap says so.
            "available": sorted(v.label for v in holds)[:60],
            "truncated": len(holds) > 60,
            "detail": "use one of the labels this id actually holds, or give the "
                      "figure as `value` and let the ledger name it",
        }

    want = float(slot["value"])
    atol = 0.5 * (10 ** -_decimals_of(want))
    near = [v for v in holds if abs(v.value - want) <= atol]
    if not near:
        # V11-G's discipline, in the shape this exit needs it. Pinning a figure
        # to ONE ref is stronger than the prose gate, which matched it against
        # everything cited pooled — and the first thing that strength costs is
        # an answer whose figures are right and whose refs are swapped. A limit
        # threshold slotted against the run reads as invented, when the alert
        # the same answer already cites holds it.
        #
        # So the refusal looks across the other refs in this answer and names
        # the one that does hold it. The model is not told to guess again; it is
        # told which id it already has.
        elsewhere = [
            {"ref": other, "label": v.label}
            for other, vals in by_ref.items() if other != ref
            for v in vals if abs(v.value - want) <= atol
        ]
        problem = {
            "at": at, "ref": ref, "reason": "figure_not_held_by_this_ref",
            "value": want,
            "detail": "this id holds no such figure. Slot the id that carries it, "
                      "or compute it with a tool so that a row does",
        }
        if elsewhere:
            problem["held_instead_by"] = elsewhere[:5]
            problem["detail"] = ("this id does not hold that figure, but another id in "
                                 "this answer does — `held_instead_by` names it. Point "
                                 "the slot there")
        return None, problem
    # More than one row of the same id holding the same number is not an error —
    # a weight and a share can coincide — but the label has to be decided. First
    # in resolver order, which is table order, which is stable.
    v = near[0]
    return Resolved(ref, v.label, v.value, v.unit_class), None


def _text_problems(text: str, at: str) -> list[dict]:
    """A number written into prose, which this exit does not accept.

    The exemptions are the gate's own closed list — dates, form numbers, regulation
    citations, years — so what stays refused is a MEASUREMENT typed as text. That
    is the invariant: a figure reaches the reader through a slot or it does not
    reach the reader.
    """
    stated = nv.extract_numbers(text)
    if not stated:
        return []
    return [{
        "at": at, "reason": "figure_written_as_text",
        "figures": [n.surface for n in stated],
        "detail": "put each figure in a slot naming the evidence it comes from. "
                  "Text carries the sentence; slots carry the numbers",
    }]


def validate_shape(blocks) -> list[dict]:
    """Everything checkable without the database: types, required fields, prose.

    Runs before any lookup so that a malformed answer costs no queries, and
    reports every problem rather than the first — the argument validator's rule,
    for the same reason.
    """
    problems: list[dict] = []
    if not isinstance(blocks, list) or not blocks:
        return [{"at": "blocks", "reason": "no_blocks",
                 "detail": "an answer is a non-empty list of blocks"}]

    for i, b in enumerate(blocks):
        at = f"blocks[{i}]"
        if not isinstance(b, dict):
            problems.append({"at": at, "reason": "block_not_an_object"})
            continue
        kind = b.get("type")
        if kind not in BLOCK_TYPES:
            problems.append({"at": at, "reason": "unknown_block_type", "type": repr(kind),
                             "allowed": list(BLOCK_TYPES)})
            continue

        if kind == "paragraph":
            runs = b.get("runs")
            if not isinstance(runs, list) or not runs:
                problems.append({"at": at, "reason": "paragraph_without_runs",
                                 "detail": "runs is a list of strings and slots, in order"})
                continue
            for j, r in enumerate(runs):
                if isinstance(r, str):
                    problems += _text_problems(r, f"{at}.runs[{j}]")
                elif _is_slot(r):
                    p = _slot_problem(r, f"{at}.runs[{j}]")
                    if p:
                        problems.append(p)
                else:
                    problems.append({"at": f"{at}.runs[{j}]", "reason": "run_not_text_or_slot"})

        elif kind == "metric_table":
            cols, rows = b.get("columns"), b.get("rows")
            if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols) or not cols:
                problems.append({"at": at, "reason": "table_without_columns"})
                continue
            if not isinstance(rows, list) or not rows:
                problems.append({"at": at, "reason": "table_without_rows"})
                continue
            for j, row in enumerate(rows):
                if not isinstance(row, list):
                    problems.append({"at": f"{at}.rows[{j}]", "reason": "row_not_a_list"})
                    continue
                if len(row) != len(cols):
                    # A short row is a cell silently shifted under the wrong
                    # heading — a figure filed under a column it does not belong
                    # to reads as a different measurement entirely.
                    problems.append({"at": f"{at}.rows[{j}]", "reason": "row_width_mismatch",
                                     "columns": len(cols), "cells": len(row)})
                    continue
                for k, cell in enumerate(row):
                    if isinstance(cell, str):
                        problems += _text_problems(cell, f"{at}.rows[{j}][{k}]")
                    elif _is_slot(cell):
                        p = _slot_problem(cell, f"{at}.rows[{j}][{k}]")
                        if p:
                            problems.append(p)
                    else:
                        problems.append({"at": f"{at}.rows[{j}][{k}]",
                                         "reason": "cell_not_text_or_slot"})
            if isinstance(b.get("title"), str):
                problems += _text_problems(b["title"], f"{at}.title")

        elif kind == "chart":
            if b.get("kind") not in CHART_KINDS:
                problems.append({"at": at, "reason": "unknown_chart_kind",
                                 "kind": repr(b.get("kind")), "allowed": list(CHART_KINDS)})
            if not isinstance(b.get("series_ref"), str) or not b.get("series_ref"):
                problems.append({"at": at, "reason": "chart_without_series",
                                 "detail": "a chart draws a series that was recorded: give "
                                           "the calc id of the series it plots"})
            if isinstance(b.get("title"), str):
                problems += _text_problems(b["title"], f"{at}.title")

        elif kind == "trend":
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "trend_without_text"})
            else:
                problems += _text_problems(b["text"], f"{at}.text")
            if not isinstance(b.get("series_ref"), str) or not b.get("series_ref"):
                problems.append({
                    "at": at, "reason": "trend_without_series",
                    "detail": "a claim that something rose, fell or held is a claim about "
                              "a sequence. Give the calc id of the series it was read from",
                })

        elif kind == "absence":
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "absence_without_text"})
            else:
                problems += _text_problems(b["text"], f"{at}.text")
            if not isinstance(b.get("absence_ref"), str) or not b.get("absence_ref"):
                problems.append({
                    "at": at, "reason": "absence_without_ref",
                    # The way out matters more here than in any other refusal.
                    # An absence block asserts the ISSUER did not report a thing,
                    # and that needs the row a refused read minted. But most of
                    # what a model wants to say in this shape is weaker and true
                    # — this desk could not compute it, the window does not
                    # reach — and that is ordinary prose with no figures in it.
                    # Without the second sentence the model has a claim it can
                    # neither support nor rephrase, and spends the turn trying.
                    "detail": "a claim that the issuer did not report something rests on "
                              "the row a refused read minted. If you have no such row — if "
                              "what you mean is that the desk could not compute it, or the "
                              "window does not reach — say that in a paragraph instead: it "
                              "is prose, and prose with no figures in it needs nothing",
                })

    return problems


def refs_in(blocks) -> list[str]:
    """Every id the answer leans on, slots and block-level refs alike.

    One list, because they are checked the same way: an id that was not returned
    to this session is not evidence, whether it names a figure or a series.
    """
    out: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict):
            continue
        for key in ("series_ref", "absence_ref"):
            if isinstance(b.get(key), str) and b[key]:
                out.append(b[key])
        for r in b.get("runs") or []:
            if _is_slot(r) and isinstance(r.get("ref"), str):
                out.append(r["ref"])
        for row in b.get("rows") or []:
            for cell in row if isinstance(row, list) else []:
                if _is_slot(cell) and isinstance(cell.get("ref"), str):
                    out.append(cell["ref"])
    seen, uniq = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def text_of(blocks) -> str:
    """The answer's prose, for the checks that read sentences.

    The quote rule and the trajectory criteria were written against a string and
    are unchanged by this batch; they get one. Slots contribute nothing here —
    they hold no words — so what these checks see is exactly what the model
    wrote as text.
    """
    parts: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if isinstance(b.get("text"), str):
            parts.append(b["text"])
        if b.get("runs"):
            # A paragraph's runs are CONTIGUOUS prose with figures lifted out of
            # it, so they join with nothing between them. Joining with a newline
            # would put a break wherever a slot sits, and the quote rule reads
            # this string — a quoted phrase with a figure inside it would be
            # split down the middle and refused for not appearing in its source.
            parts.append("".join(r for r in b["runs"] if isinstance(r, str)))
        for row in b.get("rows") or []:
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, str):
                    parts.append(cell)
    return "\n".join(parts)


def check_assertion_refs(blocks, rows_by_id: dict) -> list[dict]:
    """Trend and absence blocks against what their rows actually are.

    Two of round 4's three assertion checks, and the reason they are here rather
    than in the numeric gate: neither claim contains a number, so nothing the
    numeric gate does can see them. "VaR has been climbing all month" needs a
    series to have been read; "they report no debt" needs a refusal to have been
    recorded. Both are mechanical, which is why they can be gated at all.
    """
    problems: list[dict] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        at = f"blocks[{i}]"
        if b.get("type") in ("trend", "chart"):
            ref = b.get("series_ref")
            row = rows_by_id.get(ref)
            op = getattr(row, "operation", "") or ""
            has_points = bool((getattr(row, "result", None) or {}).get("points"))
            if row is None or not (has_points or op.startswith(_SERIES_OPS)):
                problems.append({
                    "at": at, "ref": ref,
                    "reason": "not_a_series",
                    "detail": ("a trend is a claim about a sequence and a chart draws one; "
                               "this id is not a series. Read the series first — the row "
                               "that comes back is what the claim rests on"),
                })
        elif b.get("type") == "absence":
            ref = b.get("absence_ref")
            row = rows_by_id.get(ref)
            op = getattr(row, "operation", "") or ""
            if row is None or not op.startswith(_ABSENCE_PREFIX):
                problems.append({
                    "at": at, "ref": ref,
                    "reason": "not_an_absence",
                    "detail": ("a claim that something was not reported rests on the row a "
                               "refused read mints. This id records something else, so the "
                               "absence is being asserted rather than shown"),
                })
    return problems


def resolve(blocks, values: list[nv.EvidenceValue]) -> tuple[list[Resolved], list[dict]]:
    """Every slot, resolved or refused. Shape is assumed checked."""
    by_ref: dict[str, list[nv.EvidenceValue]] = {}
    for v in values:
        by_ref.setdefault(v.source_id, []).append(v)

    resolved: list[Resolved] = []
    problems: list[dict] = []

    def one(slot: dict, at: str) -> None:
        r, p = resolve_slot(slot, by_ref, at)
        if p:
            problems.append(p)
        else:
            resolved.append(r)

    for i, b in enumerate(blocks):
        at = f"blocks[{i}]"
        for j, r in enumerate(b.get("runs") or []):
            if _is_slot(r):
                one(r, f"{at}.runs[{j}]")
        for j, row in enumerate(b.get("rows") or []):
            for k, cell in enumerate(row if isinstance(row, list) else []):
                if _is_slot(cell):
                    one(cell, f"{at}.rows[{j}][{k}]")
    return resolved, problems


def rendered(blocks, resolved: list[Resolved]) -> list[dict]:
    """The answer as it will be stored and shown: slots carrying their values.

    The model's `value`, where it wrote one, does not survive this. What is
    stored is what the ledger holds and what the ledger calls it, so a figure on
    the page is the row's figure and a reader following it back arrives at the
    row it came from.
    """
    it = iter(resolved)
    out: list[dict] = []

    def fill(x):
        if _is_slot(x):
            r = next(it)
            return {"slot": {"ref": r.ref, "label": r.label,
                             "value": r.value, "unit_class": r.unit_class}}
        return x

    for b in blocks:
        nb = dict(b)
        if b.get("runs"):
            nb["runs"] = [fill(r) for r in b["runs"]]
        if b.get("rows"):
            nb["rows"] = [[fill(c) for c in row] for row in b["rows"]]
        out.append(nb)
    return out


def prose_of(rendered_blocks) -> str:
    """The answer as a complete sentence, for every reader that has no renderer.

    `text_of` deliberately drops the figures: it feeds the quote and trajectory
    checks, and those must see ONLY what the model wrote, or a figure the ledger
    supplied would be judged as the model's wording. What gets STORED has the
    opposite requirement — "net rates exposure is , and it loses if rates rise"
    is not an answer, and a transcript, an export or a client that predates
    blocks would show exactly that.

    So the figures go back in, from the ledger, at full precision. Not the
    reader-facing rounding: that lives in the renderer with the rest of the
    display conventions, and a second copy here would be two rules about how a
    number looks, disagreeing the first time one of them changed.
    """
    parts: list[str] = []
    for b in rendered_blocks if isinstance(rendered_blocks, list) else []:
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if isinstance(b.get("text"), str):
            parts.append(b["text"])
        if b.get("runs"):
            parts.append("".join(
                r if isinstance(r, str) else _number(r) for r in b["runs"]))
        for row in b.get("rows") or []:
            parts.append(" | ".join(
                c if isinstance(c, str) else _number(c) for c in row))
    return "\n".join(p for p in parts if p)


def _number(run) -> str:
    slot = (run or {}).get("slot") if isinstance(run, dict) else None
    if not slot:
        return ""
    v = slot.get("value")
    if v is None:
        return ""
    # Not %g: a market value goes through it as 1.08663e+07, and this string is
    # the one a transcript or an export shows. Plain decimal, trailing zeros
    # trimmed, so ten million reads as ten million and a ratio keeps its digits.
    return f"{float(v):.10f}".rstrip("0").rstrip(".") if abs(float(v)) < 1e15 else str(v)


def figure_count(blocks) -> int:
    return len(refs_in(blocks)) and sum(
        1
        for b in blocks if isinstance(b, dict)
        for x in list(b.get("runs") or []) + [c for row in (b.get("rows") or []) for c in row]
        if _is_slot(x)
    )


def as_json(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)
