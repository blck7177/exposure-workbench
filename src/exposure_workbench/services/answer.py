"""The answer grammar (V24): an argument in prose, and pointers at facts.

WHY THIS EXISTS. The grammar it replaces (services/answer_blocks.py) had six
block types because every kind of evidence had its own block — a trend
pointed at a series, an absence at a refusal row, an action at a task — and a
figure was a slot naming a quantity by a name the gate had invented from
storage. The kind of a claim was declared twice, once by the block and once by
the row, and each new kind was six edits. Here the kind lives on the FACT
(services/facts.Fact.kind) and the grammar has two layouts and a chart:

    paragraph  {text: "… f_3a1b … f_9c2d@2025-12-31 …", cites?: [fact ids]}
    table      {title?, rows: [[fact id, …], …], cites?}
    chart      {kind: bar|line|waterfall, title?, fact: series fact id}

A paragraph is a SENTENCE, and a fact's id written in it IS the pointer
(V24, measured): the array-of-strings-and-objects shape it replaces was
legal and the model wrote it wrong 28 times in 94 answers, always the same
way — the object serialised into one of the strings. Replaying every stored
answer under this shape turned 22 of those into clean acceptances with no
change in what the reader sees. `cites` stays a FIELD, because the same
replay showed that folding it into the sentence loses a distinction the desk
needs: a fact a paragraph RESTS ON is not a fact it STATES, and a figure
that may not stand alone may still be cited.

`f_…@period` addresses one point of a series. A series is one fact with its
points inline, so without an address the only way to say "it rose from X to
Y" was to invent ids for the points, which is what the model did.

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

_TEXT = {"type": "string", "minLength": 1,
         "description": "the sentence. A figure is the FACT'S ID written in it (f_3a1b…) — the reader is "
                        "shown the fact's value with what it is and as of when; one point of a series is "
                        "f_3a1b…@2025-12-31"}
_CITES = {"type": "array", "items": {"type": "string"},
          "description": "fact ids (f_…) the prose of this block rests on but does not state — the "
                         "passages it quotes, the figures it reasons from"}

TABLE_RULE = ("a table cell is a fact id and nothing else; the header comes from the facts' "
              "measures and each row's label from their subject or date — neither is written "
              "by you. One row per thing compared, one column per measure; words go in the title "
              "or a paragraph")


def _block(kind: str, props: dict, required: list[str]) -> dict:
    return {"type": "object",
            "properties": {"type": {"type": "string", "enum": [kind]}, **props},
            "required": ["type", *required], "additionalProperties": False}


BLOCK_SCHEMAS = [
    _block("paragraph", {"text": _TEXT, "cites": _CITES}, ["text"]),
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
            if not isinstance(b.get("text"), str) or not b["text"].strip():
                problems.append({"at": at, "reason": "paragraph_without_text",
                                 "detail": "a paragraph is a sentence; a figure is a fact's id written in it"})
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
        for tok, s, _e in pointers_in(normalise(b.get("text") or "")):
            out.append((f"{at}.text[{s}]", tok, INLINE))
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
        seen.setdefault(split_point(fid)[0], None)
    return list(seen)


def prose_by_block(blocks) -> list[tuple[int, str, list[str]]]:
    """(block index, prose, cites) per block — the gate reads each block's prose
    against its own cites. The prose is normalised with its pointers BLANKED to
    spaces of the same length, so a link's offset holds in the rendered text
    too; a table's title is its prose."""
    out: list[tuple[int, str, list[str]]] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        parts: list[str] = []
        if isinstance(b.get("title"), str):
            parts.append(b["title"])
        if isinstance(b.get("text"), str):
            parts.append(_blank(normalise(b["text"])))
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
# `\d(?:[\d,]*\d)?` and not `\d[\d,]*`: the second swallows the comma that ends
# a clause, so "in 2024, revenue rose" offered the gate the token "2024," —
# which no lookup can resolve, and four of the seven unsourced_figure refusals
# in the whole stored corpus were exactly that (measured 2026-09-05).
_NUM = (r"(?P<num>(?<![\w.])[+\-−]?\$?\d(?:[\d,]*\d)?(?:\.\d+)?%?"
        r"(?:\s?(?:bn|mn|K|M|B|million|billion|thousand|percent|per\s?cent)\b)?)")
TOKEN = re.compile("|".join((_ID, _DATE, _FORM, _NUM)))

# A pointer written in the prose: the fact's id, optionally addressing one
# point of a series. Permissive on the body so a mistyped id is refused as
# `not_on_ledger` (which says what to do about it) rather than read as a word.
POINTER = re.compile(r"\bf_[0-9A-Za-z]{4,}(?:@[0-9A-Za-z:.\-]{1,32})?\b")

# The object decoration the old grammar required, if the model still writes it:
# `{fact:f_3a…}`, `{"fact": "f_3a…"}`. A closed shape carrying a pointer, so it
# is NORMALISED to the pointer rather than refused — 22 of 94 stored answers.
WRAPPED = re.compile(r"\{\s*[\"']?fact[\"']?\s*:\s*[\"']?(f_[0-9A-Za-z]{4,}(?:@[0-9A-Za-z:.\-]{1,32})?)[\"']?\s*\}")


def normalise(text: str) -> str:
    """The prose as everything downstream reads it. Every reader of a paragraph
    (the walkers, the gate, the renderer) calls it, so their offsets agree."""
    return WRAPPED.sub(lambda m: m.group(1), text or "")


def split_point(token: str) -> tuple[str, str | None]:
    """`f_3a1b@2025-12-31` -> ('f_3a1b', '2025-12-31'); a plain id -> (id, None)."""
    base, sep, period = (token or "").partition("@")
    return base, (period if sep and period else None)


def pointers_in(text: str) -> list[tuple[str, int, int]]:
    """(token, start, end) for every pointer in an already-normalised string."""
    return [(m.group(0), m.start(), m.end()) for m in POINTER.finditer(text or "")]


# A pointer with no space before it — "…the book aref_1aa5…". The pointer regex
# needs a word boundary, so this one is found by NEITHER the pointer walk nor
# the id rule, and the id would reach the reader as literal prose. Found by
# replaying the stored corpus; refused rather than guessed at, because a silent
# id in a sentence is the one failure this desk must not have.
GLUED = re.compile(r"(?<=[0-9A-Za-z])f_[0-9A-Za-z]{4,}")


def _blank(text: str) -> str:
    """The prose with its pointers blanked, same length — what the text rules read."""
    out = text
    for _tok, s, e in pointers_in(text):
        out = out[:s] + " " * (e - s) + out[e:]
    return out


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


def _fill_cell(records: dict[str, dict], cell: str) -> dict:
    base, period = split_point(cell)
    rec = records.get(base) or {"id": base}
    return fill_point(rec, period) if period else fill(rec)


def fill_point(rec: dict, period: str) -> dict:
    """One point of a series, as the reader's form of a figure: the point's value
    as of its own date. The id stays the SERIES' id, so the chip opens the series
    in the drawer — the point is an address into it, not a row of its own."""
    value = next((float(p[1]) for p in (rec.get("points") or []) if str(p[0]) == period), None)
    unit = rec.get("unit") or ""
    out = {k: rec.get(k) for k in ("id", "measure", "subject", "unit", "params", "standalone", "sources", "group")}
    out |= {"kind": F.SCALAR, "value": value, "as_of": period, "window": None,
            "display": dc.display(value, unit) if (value is not None and unit) else str(value)}
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
            # The INPUT grammar changed; the OUTPUT shape did not. A rendered
            # paragraph is still `runs` of strings, {fact: …} and {link: …},
            # which is what the page and every stored answer already read.
            nb.pop("text", None)
            nb["runs"] = _paragraph_runs(i, normalise(b.get("text") or ""), records, links)
        elif b.get("type") == "table":
            # A cell may address one point of a series (live: the model tabulated
            # a filed balance's eight instants that way, and the renderer looked
            # the whole token up as an id).
            grid = [[_fill_cell(records, c) for c in row] for row in b["rows"]]
            nb["rows"] = [[{"fact": f} for f in row] for row in grid]
            nb.update(derive_table(grid))
        elif b.get("type") == "chart":
            nb["fact"] = fill(records[b["fact"]])
        if isinstance(b.get("title"), str):
            nb["title"] = b["title"]
        out.append(nb)
    return out


def _paragraph_runs(i: int, text: str, records: dict[str, dict], links: dict) -> list:
    """The sentence, cut at its pointers and at the tokens the gate resolved.

    Both are addressed by offset into the same normalised string — the gate
    read it with the pointers blanked to spaces of equal length, so the two
    sets of offsets live in one coordinate system and cannot overlap."""
    marks: list[tuple[int, int, str, object]] = []
    for tok, s, e in pointers_in(text):
        base, period = split_point(tok)
        marks.append((s, e, "fact", (base, period)))
    for (bi, s), link in links.items():
        if bi == i and link["to"] != "question":     # the user's own number stays unmarked
            marks.append((s, s + len(link["as_written"]), "link", link))
    marks.sort(key=lambda m: m[0])
    out: list = []
    pos = 0
    for s, e, kind, payload in marks:
        if s < pos:
            continue
        if s > pos:
            out.append(text[pos:s])
        if kind == "fact":
            base, period = payload
            rec = records.get(base)
            out.append({"fact": (fill_point(rec, period) if period else fill(rec)) if rec else {"id": base}})
        else:
            out.append({"link": {"to": payload["to"], "ids": payload["ids"], "as_written": text[s:e]}})
        pos = e
    if pos < len(text):
        out.append(text[pos:])
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
                    if f.get("kind") in (F.SCALAR, F.SERIES):
                        s.append(f["display"])
                    elif f.get("kind") == F.PASSAGE:
                        s.append(f"[{_words(f.get('measure') or 'passage')}]")     # a mark, never the passage's text
                    else:
                        s.append(f.get("text") or f.get("display") or "")
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
