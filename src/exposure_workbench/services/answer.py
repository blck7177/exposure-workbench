"""The answer grammar (V24): an argument in prose, and pointers at facts.

WHY THIS EXISTS. The grammar it replaces (services/answer_blocks.py) had six
block types because every kind of evidence had its own block — a trend
pointed at a series, an absence at a refusal row, an action at a task — and a
figure was a slot naming a quantity by a name the gate had invented from
storage. The kind of a claim was declared twice, once by the block and once by
the row, and each new kind was six edits. Here the kind lives on the FACT
(services/facts.Fact.kind) and the grammar has two layouts and a chart:

    paragraph  {runs: [str | {fact: id}], cites?: [passage fact ids]}
    table      {title?, rows: [[fact id, …], …], cites?}
    chart      {kind: bar|line|waterfall, title?, fact: series fact id}

A trend is a paragraph pointing at a series fact; an absence is a paragraph
pointing at an absence fact; work started is a paragraph pointing at a task
fact. The renderer shows each kind in its own form because it reads the fact.

WHAT THIS MODULE DOES NOT DO. It does not decide what a digit in prose equals
— the gate does (services/gate.py), by lookup against the ledger. This module
FINDS tokens (`tokens_in`) and shapes the answer for the reader (`rendered`,
`prose_of`); the only rule of its own is structural.
"""

from __future__ import annotations

import json
import re
from typing import Any

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.services import facts as F

BLOCK_TYPES = ("paragraph", "table", "chart")
CHART_KINDS = ("bar", "line", "waterfall")

# ── schema (Law B: the grammar is the tool's argument schema) ─────────────────

_FACT_REF = {"type": "object",
             "description": "one fact, by the id a tool result's `facts` gave it, e.g. {fact: 'f_3a1b…'}; "
                            "the reader is shown the fact's own value with what it is and as of when",
             "properties": {"fact": {"type": "string"}},
             "required": ["fact"], "additionalProperties": False}
_RUN = {"anyOf": [{"type": "string"}, _FACT_REF]}
_CITES = {"type": "array", "items": {"type": "string"},
          "description": "passage fact ids (f_…) the prose of this block rests on"}

TABLE_RULE = ("a table cell is a fact id and nothing else; the header comes from the facts' "
              "measures and each row's label from their subject or date — neither is written "
              "by you. One row per thing compared, one column per measure; words go in the title "
              "or a paragraph")


def _block(kind: str, props: dict, required: list[str]) -> dict:
    return {"type": "object",
            "properties": {"type": {"type": "string", "enum": [kind]}, **props},
            "required": ["type", *required], "additionalProperties": False}


BLOCK_SCHEMAS = [
    _block("paragraph", {"runs": {"type": "array", "minItems": 1, "items": _RUN,
                                  "description": "strings and fact refs, in reading order"},
                         "cites": _CITES}, ["runs"]),
    _block("table", {"title": {"type": "string"},
                     "rows": {"type": "array", "minItems": 1, "description": TABLE_RULE,
                              "items": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
                     "cites": _CITES}, ["rows"]),
    _block("chart", {"kind": {"type": "string", "enum": list(CHART_KINDS)},
                     "title": {"type": "string"},
                     "fact": {"type": "string", "description": "a series fact id"}},
           ["kind", "fact"]),
]

ANSWER_SCHEMA = {"type": "object", "properties": {
    "blocks": {"type": "array", "minItems": 1, "description": "the answer, in reading order",
               "items": {"oneOf": BLOCK_SCHEMAS}},
}, "required": ["blocks"], "additionalProperties": False}


# ── structure (for callers that bypass the schema) ────────────────────────────

def _is_ref(x: Any) -> bool:
    return isinstance(x, dict) and isinstance(x.get("fact"), str) and bool(x.get("fact"))


def validate_shape(blocks) -> list[dict]:
    """Structural problems only, all at once. The text and pointer rules are the
    gate's; this says whether the answer can be walked."""
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
            problems.append({"at": at, "reason": "unknown_block_type", "type": repr(kind), "allowed": list(BLOCK_TYPES)})
            continue
        cites = b.get("cites")
        if cites is not None and not (isinstance(cites, list) and all(isinstance(c, str) for c in cites)):
            problems.append({"at": f"{at}.cites", "reason": "cites_not_a_list_of_ids"})
        if kind == "paragraph":
            runs = b.get("runs")
            if not isinstance(runs, list) or not runs:
                problems.append({"at": at, "reason": "paragraph_without_runs"})
                continue
            for j, r in enumerate(runs):
                if isinstance(r, str) or _is_ref(r):
                    continue
                if isinstance(r, dict):
                    problems.append({"at": f"{at}.runs[{j}]", "reason": "ref_without_fact",
                                     "detail": "a figure in prose is {fact: id}; a name or a value is not a pointer"})
                else:
                    problems.append({"at": f"{at}.runs[{j}]", "reason": "run_not_text_or_fact"})
        elif kind == "table":
            rows = b.get("rows")
            if not isinstance(rows, list) or not rows:
                problems.append({"at": at, "reason": "table_without_rows"})
                continue
            width = len(rows[0]) if isinstance(rows[0], list) else None
            for j, row in enumerate(rows):
                if not isinstance(row, list) or not row or len(row) != width:
                    problems.append({"at": f"{at}.rows[{j}]", "reason": "row_width_mismatch", "columns": width,
                                     "cells": len(row) if isinstance(row, list) else None})
                    continue
                for k, cell in enumerate(row):
                    if not isinstance(cell, str) or not cell:
                        problems.append({"at": f"{at}.rows[{j}][{k}]", "reason": "cell_not_a_fact_id", "detail": TABLE_RULE})
        elif kind == "chart":
            if b.get("kind") not in CHART_KINDS:
                problems.append({"at": at, "reason": "unknown_chart_kind", "allowed": list(CHART_KINDS)})
            if not isinstance(b.get("fact"), str) or not b["fact"]:
                problems.append({"at": at, "reason": "chart_without_fact"})
    return problems


# ── walking ───────────────────────────────────────────────────────────────────

INLINE, CELL, CHART, CITE = "inline", "cell", "chart", "cite"


def refs_in(blocks) -> list[tuple[str, str, str]]:
    """(address, fact id, role) for every pointer, in reading order."""
    out: list[tuple[str, str, str]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        at = f"blocks[{i}]"
        for j, r in enumerate(b.get("runs") or []):
            if _is_ref(r):
                out.append((f"{at}.runs[{j}]", r["fact"], INLINE))
        for j, row in enumerate(b.get("rows") or []):
            for k, cell in enumerate(row if isinstance(row, list) else []):
                if isinstance(cell, str):
                    out.append((f"{at}.rows[{j}][{k}]", cell, CELL))
        if b.get("type") == "chart" and isinstance(b.get("fact"), str):
            out.append((at, b["fact"], CHART))
        for c in b.get("cites") or []:
            if isinstance(c, str):
                out.append((f"{at}.cites", c, CITE))
    return out


def ids_in(blocks) -> list[str]:
    seen: dict[str, None] = {}
    for _, fid, _ in refs_in(blocks):
        seen.setdefault(fid, None)
    return list(seen)


# The separator between a paragraph's string runs when they are read as one
# text: a fact stood between them, so two strings must not fuse into one token.
_GAP = " ⁣ "     # invisible separator, whitespace on both sides


def prose_by_block(blocks) -> list[tuple[int, str, list[str]]]:
    """(block index, prose, cites) per block — the gate reads each block's prose
    against its own cites. A table's title is its prose."""
    out: list[tuple[int, str, list[str]]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        parts: list[str] = []
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if b.get("runs"):
            parts.append(_GAP.join(r for r in b["runs"] if isinstance(r, str)))
        cites = [c for c in (b.get("cites") or []) if isinstance(c, str)]
        out.append((i, "\n".join(parts), cites))
    return out


# ── tokens: what the gate resolves ────────────────────────────────────────────
# One finder, no judgement. An id is one token; a date is one token; a form
# name is one token; a number carries its sign, currency, thousands separators,
# decimals, percent sign and a scale word when one follows.

ID_PREFIXES = ("f_", "fact_", "calc_", "chunk_", "src_", "run_", "alert_", "pos_", "task_", "rrun_", "brief_", "sess_", "msg_")
_ID = r"(?P<id>\b(?:" + "|".join(p[:-1] for p in ID_PREFIXES) + r")_[A-Za-z0-9]{4,}\b)"
_DATE = r"(?P<date>\b\d{4}-\d{2}-\d{2}\b)"
_FORM = r"(?P<form>\b\d{1,2}-[KQF](?:/A)?\b|\b[SF]-[13]\b|\bDEF\s?14A\b)"
_NUM = (r"(?P<num>(?<![\w.])[+\-−]?\$?\d[\d,]*(?:\.\d+)?%?"
        r"(?:\s?(?:bn|mn|K|M|B|million|billion|thousand|percent|per\s?cent)\b)?)")
TOKEN = re.compile("|".join((_ID, _DATE, _FORM, _NUM)))

# A fact ref serialised into a string: `{fact:f_3a…}`, `{"fact": "f_3a…"}`,
# `{fact: 'f_3a…'}` — braces around the word fact and an id. Closed shape.
SERIALISED_REF = re.compile(r"\{\s*[\"']?fact[\"']?\s*:\s*[\"']?f_[A-Za-z0-9]{4,}[\"']?\s*\}")


def tokens_in(text: str) -> list[dict]:
    """[{token, kind, start, end}] for every id, date, form name and number."""
    out: list[dict] = []
    for m in TOKEN.finditer(text or ""):
        kind = m.lastgroup
        tok = m.group(0)
        if kind == "num" and tok.strip().endswith(("percent", "per cent")):
            tok = re.sub(r"\s?per\s?cent$", "%", tok.strip())
        out.append({"token": tok.strip(), "kind": kind, "start": m.start(), "end": m.end()})
    return out


# ── rendering ─────────────────────────────────────────────────────────────────

def _words(s: str) -> str:
    return re.sub(r"[._]", " ", s or "").replace(":", " ").strip()


def _series_summary(rec: dict) -> dict | None:
    pts = rec.get("points") or []
    if len(pts) < 2:
        return None
    pts = sorted((str(p[0]), float(p[1])) for p in pts)
    (p0, v0), (p1, v1) = pts[0], pts[-1]
    return {"label": _words(rec.get("measure") or ""), "unit_class": rec.get("unit") or "", "n": len(pts),
            "from": {"period": p0, "value": v0}, "to": {"period": p1, "value": v1},
            "direction": "up" if v1 > v0 else "down" if v1 < v0 else "flat"}


def fill(rec: dict) -> dict:
    """The reader's form of one fact: the record plus its display string, a
    series' own summary, a passage's text."""
    unit = rec.get("unit") or ""
    out = {k: rec.get(k) for k in ("id", "kind", "measure", "subject", "unit", "value", "as_of", "window",
                                   "params", "standalone", "sources", "group")}
    if rec.get("kind") == F.SCALAR and isinstance(rec.get("value"), (int, float)):
        out["display"] = dc.display(rec["value"], unit) if unit else str(rec["value"])
    elif rec.get("kind") == F.SERIES:
        out["series"] = _series_summary(rec)
        out["display"] = (f"{dc.display(out['series']['to']['value'], unit)} ({out['series']['to']['period']})"
                          if out["series"] and unit else _words(rec.get("measure") or ""))
    else:
        out["text"] = rec.get("text")
        out["display"] = {F.ABSENCE: "not held", F.TASK: "started", F.PASSAGE: "passage"}.get(rec.get("kind"), "")
    return out


def derive_table(cells: list[list[dict]]) -> dict:
    """header / labels / explicit from the facts in a grid.

    A column whose facts share one measure is headed by it; one whose facts
    differ says each cell's own measure (explicit). A row is labelled by what
    varies across rows — the subject when subjects differ, the date when only
    dates do, the first cell's measure when nothing else does."""
    if not cells or not cells[0]:
        return {"header": [], "labels": [], "explicit": []}
    width = len(cells[0])
    header, explicit = [], []
    for j in range(width):
        measures = {c.get("measure") for c in (row[j] for row in cells if j < len(row))}
        if len(measures) == 1:
            header.append(_words(next(iter(measures)) or ""))
            explicit.append(False)
        else:
            header.append("")
            explicit.append(True)
    subjects = [row[0].get("subject") for row in cells]
    dates = [row[0].get("as_of") for row in cells]
    if len(set(subjects)) > 1 or len(cells) == 1 and subjects[0]:
        labels = [s or "" for s in subjects]
    elif len(set(dates)) > 1:
        labels = [d or "" for d in dates]
    else:
        labels = [_words(row[0].get("measure") or "") for row in cells]
    return {"header": header, "labels": labels, "explicit": explicit}


def rendered(blocks, records: dict[str, dict], links: dict[tuple[int, int], dict] | None = None) -> list[dict]:
    """The answer as stored and shown: every pointer carrying its fact; every
    prose token the gate resolved carrying what it resolved to.

    `records` is id -> fact record (the ledger's). `links` is
    (block index, token start) -> {"to": "fact"|"passage", "ids": [...]} for the
    tokens of each block's prose, addressed on the block's prose as
    prose_by_block builds it."""
    links = links or {}
    out: list[dict] = []
    for i, b in enumerate(blocks):
        nb = dict(b)
        if b.get("type") == "paragraph":
            nb["runs"] = _split_runs(i, b.get("runs") or [], records, links)
        elif b.get("type") == "table":
            grid = [[fill(records[c]) for c in row] for row in b["rows"]]
            nb["rows"] = [[{"fact": f} for f in row] for row in grid]
            nb.update(derive_table(grid))
        elif b.get("type") == "chart":
            nb["fact"] = fill(records[b["fact"]])
        if isinstance(b.get("title"), str):
            nb["title"] = b["title"]
        out.append(nb)
    return out


def _split_runs(i: int, runs: list, records: dict[str, dict], links: dict) -> list:
    """String runs split at their resolved tokens; fact refs filled."""
    out: list = []
    # offsets into the block's prose as prose_by_block built it (title first)
    offset = 0
    for r in runs:
        if _is_ref(r):
            out.append({"fact": fill(records[r["fact"]])})
            continue
        if not isinstance(r, str):
            continue
        pieces = sorted(((s, l) for (bi, s), l in links.items() if bi == i and offset <= s < offset + len(r)),
                        key=lambda x: x[0])
        pos = 0
        for start, link in pieces:
            if link["to"] == "question":
                continue                          # the user's own number stays in its sentence, unmarked
            local = start - offset
            if local < pos:
                continue
            if local > pos:
                out.append(r[pos:local])
            end = local + len(link["as_written"])
            out.append({"link": {"to": link["to"], "ids": link["ids"], "as_written": r[local:end]}})
            pos = end
        if pos < len(r):
            out.append(r[pos:])
        offset += len(r) + len(_GAP)
    return out


def prose_of(rendered_blocks) -> str:
    """The answer as sentences, figures at reader precision."""
    parts: list[str] = []
    for b in rendered_blocks if isinstance(rendered_blocks, list) else []:
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if b.get("type") == "paragraph":
            s = []
            for r in b.get("runs") or []:
                if isinstance(r, str):
                    s.append(r)
                elif isinstance(r, dict) and "fact" in r:
                    f = r["fact"]
                    s.append(f["display"] if f.get("kind") in (F.SCALAR, F.SERIES) else (f.get("text") or f.get("display") or ""))
                elif isinstance(r, dict) and "link" in r:
                    s.append(r["link"]["as_written"])
            parts.append("".join(s))
        elif b.get("type") == "table":
            header = b.get("header") or []
            if any(header):
                parts.append(" | ".join(["", *header]))
            for lab, row in zip(b.get("labels") or [], b.get("rows") or []):
                cells = [lab]
                for k, c in enumerate(row):
                    f = c["fact"]
                    words = _words(f.get("measure") or "")
                    if lab and words.lower().startswith(lab.lower()):
                        words = words[len(lab):].strip()          # "AAPL beta contrib" under the AAPL row reads "beta contrib"
                    cells.append((f"{words}: " if (b.get("explicit") or [False] * 99)[k] and words else "") + str(f.get("display") or ""))
                parts.append(" | ".join(cells))
        elif b.get("type") == "chart":
            f = b.get("fact") or {}
            parts.append(f"[chart: {_words(f.get('measure') or '')} {f.get('display') or ''}]")
    return "\n".join(p for p in parts if p)


def as_json(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)
