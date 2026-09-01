"""V15-S3. The exit's grammar: an answer is blocks, and every claim names its evidence.

WHY THIS EXISTS. Until V14 the model wrote prose with numbers in it and the gate
read the numbers back out. V14-C made a figure a SLOT — but a slot could still
be authored as `{ref, value}`, and the gate then went looking for which of the
ref's figures the value was. Measured on 442 bad slots: values do not carry
intent (the same 0.06 is TLT's weight and a stress warning level on one run),
and a resolver that guesses from a value hands the reader the wrong identity
with the gate's blessing.

So a slot is `{ref, name}` and nothing else. The name is one the table showed
the model (services/table.py), and resolving it is a dictionary lookup. There
is no value form, because the value form is the one channel through which a
figure could arrive without its identity.

CLAIM TYPES. Each kind of claim has one shape and one evidence predicate, and
the set is closed — a claim with no shape here has nowhere to be written, which
is the point (the model used to write "Evidence ids: chunk_…" into a sentence
because a passage-backed claim had no slot):

    paragraph     text runs and slots; `cites` names the passages the prose
                  rests on (chunk_/src_) — checked for membership, and any
                  quotation marks in the text are checked against them
    metric_table  cells are text or slots; `cites` as above
    chart         kind + series_ref → the ref must be a series row
    trend         text + series_ref → a claim about a sequence rests on one
    absence       text + absence_ref → a claim that something was not reported
                  rests on the row the refused read minted
    action        text + task_ref → work this turn started, by its id

Text carries no digits (dates and the handful of non-measurement token classes
below excepted). Shape is the JSON Schema's job (tools/meta_tools.py); what is
here is the one text rule and the renderers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import table as tb

BLOCK_TYPES = ("paragraph", "metric_table", "chart", "trend", "absence", "action")
CHART_KINDS = ("bar", "line", "waterfall")

# Rows an assertion block may point at, by kind (services/quantities.py,
# services/table.py).
SERIES_KINDS = ("series",)
ABSENCE_KINDS = ("absence",)
TASK_KINDS = ("task",)


@dataclass(frozen=True)
class Resolved:
    """One slot, after the table has been consulted."""

    ref: str
    label: str
    value: float
    unit_class: str


# ── the one text rule ─────────────────────────────────────────────────────────
# Digits that are not measurements. Closed and short: a date, a year, a filing
# form, a fiscal period label, a regulation reference, and a product designator
# written attached to its digits (H200). Everything else with a digit in it is a
# figure typed as text, which this exit does not accept. Adding a class is an
# edit here plus a case in test_output_grammar.
_NOT_A_FIGURE = tuple(re.compile(p, f) for p, f in (
    (r"\b\d{4}-\d{2}-\d{2}\b", 0),                                             # 2026-03-31
    (r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b(?:,\s*\d{4}\b)?", 0),
    (r"(?<![\d.$])\b(?:19|20)\d{2}\b(?![\d%])(?!\.\d)", 0),                    # 2026
    (r"\b(?:10-[KQ]|8-K|20-F|6-K|S-[13]|DEF\s?14A)(?:/A)?\b", 0),              # 10-K
    (r"\b(?:[QH][1-4]|FY\d{2,4}|CY\d{2,4})\b", 0),                             # Q4, FY2025
    (r"\b(?:C&DI|Item|Rule|Reg(?:ulation)?|Section|§|ASC|ASU|IFRS|IAS|SFAS)\s*"
     r"\d+[0-9A-Za-z]*(?:[.\-][0-9A-Za-z]+)*\b", re.IGNORECASE),               # Item 1A
    (r"\b[A-Z][A-Za-z&.]{0,14}\d{2,4}\b(?!\s*%)", 0),                          # H200, GB200
    # A window label is the NAME of a measure, not its value: "30-day rolling
    # volatility", "60d", "the last 3 years". The exposure report's own headings
    # are written this way, and three stored block answers tripped on it.
    (r"\b\d{1,3}(?:[-\s]?(?:day|week|month|quarter|year|session|trading day)s?|[dwmy])\b(?!\s*%)", re.IGNORECASE),
    # A confidence level is a PARAMETER of the measure, not a measurement:
    # "VaR (95%)", "95% VaR", "1-day 95 VaR". The first V15 battery spent eight
    # of one turn's nine attempts on this one token. Anchored to the measure's
    # name, like the V3 gate's own class: a bare "95%" elsewhere is a figure.
    (r"\b(?:90|95|97\.5|99)\s*%?\s*(?:VaR|ES|CVaR|confidence|CI)\b"
     r"|\b(?:VaR|ES|CVaR)\s*\(?\s*(?:90|95|97\.5|99)\s*%?", re.IGNORECASE),
))
_DIGIT_RUN = re.compile(r"[+\-−]?\$?\d[\d,]*(?:\.\d+)?%?")
# An evidence id written into text is refused as a whole token, not as the
# fragments of digits inside it: "run_d1bbfadbbb7e" is what the model wrote,
# and a refusal naming '1' and '7' is a refusal it cannot act on. Ids belong in
# a slot's ref or a block's cites — the reason it is a refusal at all.
#
# The prefixes are built, not hand-written (V16): the citable ones are owned by
# quantities.SOURCES and the task ones by table._TASK_PREFIXES — the two tables
# the rest of the desk already resolves by, so a prefix added there is refused
# in text from the same commit. What remains is the desk's OTHER ids: minted
# and shown to the model (a brief, a session, a message id) but resolvable by
# nothing, so writing one into text is refused the same way — an id has no
# legal place in prose whether or not something can be cited by it.
_REJECT_ONLY_PREFIXES: tuple[str, ...] = ("brief_", "sess_", "msg_")
_ID_PREFIXES: tuple[str, ...] = tuple(dict.fromkeys(
    qn.CITABLE_PREFIXES + tb._TASK_PREFIXES + _REJECT_ONLY_PREFIXES))
_ID_TOKEN = re.compile(
    r"\b(?:" + "|".join(re.escape(p[:-1]) for p in _ID_PREFIXES) + r")_[A-Za-z0-9_]{4,}\b")


def figures_in_text(text: str) -> list[str]:
    """Every digit run in `text` that is not one of the non-measurement classes,
    plus every evidence id written as text — whole."""
    if not text:
        return []
    out: list[str] = []
    taken: list[tuple[int, int]] = []
    for m in _ID_TOKEN.finditer(text):
        out.append(m.group(0))
        taken.append((m.start(), m.end()))
    exempt: list[tuple[int, int]] = list(taken)
    for pattern in _NOT_A_FIGURE:
        exempt.extend((m.start(), m.end()) for m in pattern.finditer(text))
    for m in _DIGIT_RUN.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in exempt):
            continue
        out.append(m.group(0).strip())
    return out


def _is_slot(x) -> bool:
    return isinstance(x, dict)


def _text_problems(text: str, at: str) -> list[dict]:
    figures = figures_in_text(text)
    if not figures:
        return []
    ids = [f for f in figures if _ID_TOKEN.fullmatch(f)]
    numbers = [f for f in figures if f not in ids]
    detail = []
    if numbers:
        detail.append("text carries no figures — put each one in a slot {ref, name} using a "
                      "name from the table a tool returned (counts too: count.* names)")
    if ids:
        detail.append("an id is never written into text — a figure points at it through a "
                      "slot, a passage through the block's `cites`; a run or alert the prose "
                      "rests on goes in `cites` as well, and the reader follows it from there")
    return [{"at": at, "reason": "digits_in_text", "figures": figures, "detail": "; ".join(detail)}]


def _slot_problem(slot: dict, at: str) -> dict | None:
    if not isinstance(slot.get("ref"), str) or not slot["ref"]:
        return {"at": at, "reason": "slot_without_ref"}
    if not isinstance(slot.get("name"), str) or not slot["name"]:
        return {"at": at, "ref": slot["ref"], "reason": "slot_without_name",
                "detail": "a slot is {ref, name}: the id and the name the table gave the figure"}
    return None


def validate_shape(blocks) -> list[dict]:
    """The text rule, plus enough structure to walk without crashing.

    The schema on `respond` refuses malformed blocks before this runs; a direct
    caller (a test, the brief gate) gets the same answers here, one list, all
    problems at once.
    """
    problems: list[dict] = []
    if not isinstance(blocks, list) or not blocks:
        return [{"at": "blocks", "reason": "no_blocks", "detail": "an answer is a non-empty list of blocks"}]
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
        if isinstance(b.get("title"), str):
            problems += _text_problems(b["title"], f"{at}.title")
        if isinstance(b.get("text"), str):
            problems += _text_problems(b["text"], f"{at}.text")
        if kind == "paragraph":
            runs = b.get("runs")
            if not isinstance(runs, list) or not runs:
                problems.append({"at": at, "reason": "paragraph_without_runs"})
                continue
            # The text rule reads the paragraph's prose as ONE string, with the
            # slots lifted out. Checked run by run, "VaR (" + slot + ") at 95%"
            # shows the rule a bare "95%" with the measure's name in another
            # run, and refuses the confidence level it would have recognised.
            problems += _text_problems("".join(r for r in runs if isinstance(r, str)), f"{at}.runs")
            for j, r in enumerate(runs):
                if isinstance(r, str):
                    continue
                elif _is_slot(r):
                    p = _slot_problem(r, f"{at}.runs[{j}]")
                    if p:
                        problems.append(p)
                else:
                    problems.append({"at": f"{at}.runs[{j}]", "reason": "run_not_text_or_slot"})
        elif kind == "metric_table":
            cols, rows = b.get("columns"), b.get("rows")
            if not isinstance(cols, list) or not cols or not all(isinstance(c, str) for c in cols):
                problems.append({"at": at, "reason": "table_without_columns"})
                continue
            if not isinstance(rows, list) or not rows:
                problems.append({"at": at, "reason": "table_without_rows"})
                continue
            for j, row in enumerate(rows):
                if not isinstance(row, list) or len(row) != len(cols):
                    problems.append({"at": f"{at}.rows[{j}]", "reason": "row_width_mismatch",
                                     "columns": len(cols),
                                     "cells": len(row) if isinstance(row, list) else None})
                    continue
                for k, cell in enumerate(row):
                    if isinstance(cell, str):
                        problems += _text_problems(cell, f"{at}.rows[{j}][{k}]")
                    elif _is_slot(cell):
                        p = _slot_problem(cell, f"{at}.rows[{j}][{k}]")
                        if p:
                            problems.append(p)
                    else:
                        problems.append({"at": f"{at}.rows[{j}][{k}]", "reason": "cell_not_text_or_slot"})
        elif kind == "chart":
            if b.get("kind") not in CHART_KINDS:
                problems.append({"at": at, "reason": "unknown_chart_kind", "allowed": list(CHART_KINDS)})
            if not isinstance(b.get("series_ref"), str) or not b["series_ref"]:
                problems.append({"at": at, "reason": "chart_without_series"})
        elif kind == "trend":
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "trend_without_text"})
            if not isinstance(b.get("series_ref"), str) or not b["series_ref"]:
                problems.append({"at": at, "reason": "trend_without_series"})
        elif kind == "absence":
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "absence_without_text"})
            if not isinstance(b.get("absence_ref"), str) or not b["absence_ref"]:
                problems.append({"at": at, "reason": "absence_without_ref"})
        elif kind == "action":
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "action_without_text"})
            if not isinstance(b.get("task_ref"), str) or not b["task_ref"]:
                problems.append({"at": at, "reason": "action_without_task"})
        cites = b.get("cites")
        if cites is not None and (not isinstance(cites, list)
                                  or not all(isinstance(c, str) and c for c in cites)):
            problems.append({"at": f"{at}.cites", "reason": "cites_not_a_list_of_ids"})
    return problems


# ── walking ───────────────────────────────────────────────────────────────────

def slots_in(blocks) -> list[tuple[str, dict]]:
    """Every slot with its address, in reading order."""
    out: list[tuple[str, dict]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        at = f"blocks[{i}]"
        for j, r in enumerate(b.get("runs") or []):
            if _is_slot(r):
                out.append((f"{at}.runs[{j}]", r))
        for j, row in enumerate(b.get("rows") or []):
            for k, cell in enumerate(row if isinstance(row, list) else []):
                if _is_slot(cell):
                    out.append((f"{at}.rows[{j}][{k}]", cell))
    return out


def cites_in(blocks) -> list[tuple[str, str]]:
    """Every passage citation with its block address."""
    out: list[tuple[str, str]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if isinstance(b, dict):
            for c in b.get("cites") or []:
                if isinstance(c, str):
                    out.append((f"blocks[{i}]", c))
    return out


def assertions_in(blocks) -> list[tuple[str, str, str]]:
    """(address, kind, ref) for every trend / chart / absence / action block."""
    out: list[tuple[str, str, str]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        at = f"blocks[{i}]"
        t = b.get("type")
        if t in ("trend", "chart") and isinstance(b.get("series_ref"), str):
            out.append((at, "series", b["series_ref"]))
        elif t == "absence" and isinstance(b.get("absence_ref"), str):
            out.append((at, "absence", b["absence_ref"]))
        elif t == "action" and isinstance(b.get("task_ref"), str):
            out.append((at, "task", b["task_ref"]))
    return out


def refs_in(blocks) -> list[str]:
    """Every id the answer leans on — slots, cites and block-level refs alike."""
    out: list[str] = []
    for _, s in slots_in(blocks):
        if isinstance(s.get("ref"), str):
            out.append(s["ref"])
    for _, c in cites_in(blocks):
        out.append(c)
    for _, _, r in assertions_in(blocks):
        out.append(r)
    seen, uniq = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def text_of(blocks) -> str:
    """The answer's prose, for the checks that read sentences. Slots contribute nothing."""
    parts: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if isinstance(b.get("text"), str):
            parts.append(b["text"])
        if b.get("runs"):
            parts.append("".join(r for r in b["runs"] if isinstance(r, str)))
        for row in b.get("rows") or []:
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, str):
                    parts.append(cell)
    return "\n".join(parts)


def text_by_block(blocks) -> list[tuple[str, str]]:
    """(address, prose) per block — the quote rule reads each block against ITS cites."""
    out: list[tuple[str, str]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        parts = []
        for key in ("title", "text"):
            if isinstance(b.get(key), str):
                parts.append(b[key])
        if b.get("runs"):
            parts.append("".join(r for r in b["runs"] if isinstance(r, str)))
        for row in b.get("rows") or []:
            parts.extend(c for c in (row if isinstance(row, list) else []) if isinstance(c, str))
        out.append((f"blocks[{i}]", "\n".join(parts)))
    return out


# ── rendering ─────────────────────────────────────────────────────────────────

def rendered(blocks, resolved: list[Resolved]) -> list[dict]:
    """The answer as stored and shown: every slot carrying the table's figure.

    `resolved` is in `slots_in` order. The model's slot ({ref, name}) becomes
    {slot: {ref, label, value, unit_class}} — `label` is the name, kept under
    the key the renderer has read since V14.
    """
    it = iter(resolved)
    out: list[dict] = []

    def fill(x):
        if _is_slot(x):
            r = next(it)
            return {"slot": {"ref": r.ref, "label": r.label, "value": r.value, "unit_class": r.unit_class}}
        return x

    for b in blocks:
        nb = dict(b)
        if b.get("runs"):
            nb["runs"] = [fill(r) for r in b["runs"]]
        if b.get("rows"):
            nb["rows"] = [[fill(c) for c in row] for row in b["rows"]]
        out.append(nb)
    return out


def _number(run) -> str:
    slot = (run or {}).get("slot") if isinstance(run, dict) else None
    if not slot or slot.get("value") is None:
        return ""
    return dc.display(slot["value"], slot.get("unit_class") or "")


def prose_of(rendered_blocks) -> str:
    """The answer as complete sentences, with figures at reader precision.

    One rule for how a number looks (analytics/display_conventions), so the
    transcript, the export and the rubric read what the renderer shows.
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
            parts.append("".join(r if isinstance(r, str) else _number(r) for r in b["runs"]))
        for row in b.get("rows") or []:
            parts.append(" | ".join(c if isinstance(c, str) else _number(c) for c in row))
    return "\n".join(p for p in parts if p)


def figure_count(blocks) -> int:
    return len(slots_in(blocks))


def as_json(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)
