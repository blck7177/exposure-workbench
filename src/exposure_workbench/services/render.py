"""The renderer: the answer as the page shows it, built from the draft and the observer's verdict.

The model wrote prose; the observer matched its figures to the cells of the
analysis views. This module puts each supported figure's fact where the number
stands — the chip the reader hovers and opens — and appends every view the answer
drew on as a table, so the reader sees the whole analysis and not only the
sentences written about it. Nothing here changes a word the model wrote.
"""

from __future__ import annotations

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.analytics import registry
from exposure_workbench.analytics import value_semantics as vs
from exposure_workbench.services import observer as ob


def fill(rec: dict) -> dict:
    """The reader's form of one fact: the record plus its display string."""
    unit = rec.get("unit") or ""
    out = {k: rec.get(k) for k in ("id", "kind", "measure", "subject", "unit", "value", "as_of", "window",
                                   "params", "standalone", "sources", "group")}
    said = registry.means_words(rec)
    if said:
        out["means"] = said
    if isinstance(rec.get("value"), (int, float)) and unit:
        out["display"] = dc.display(float(rec["value"]), unit, vs.kind_of(rec.get("params")))
    elif rec.get("kind") == "passage":
        out["text"] = rec.get("text")
        out["display"] = "passage"
    else:
        out["display"] = str(rec.get("value") if rec.get("value") is not None else rec.get("text") or "")
    return out


def _paragraphs(text: str) -> list[tuple[int, int]]:
    out, start = [], 0
    for i, ch in enumerate(text):
        if ch == "\n":
            if i > start and text[start:i].strip():
                out.append((start, i))
            start = i + 1
    if start < len(text) and text[start:].strip():
        out.append((start, len(text)))
    return out


def _runs(text: str, start: int, end: int, marks: list[tuple[int, int, dict]]) -> list:
    out: list = []
    pos = start
    for s, e, payload in sorted(marks, key=lambda m: m[0]):
        if s < pos or e > end:
            continue
        if s > pos:
            out.append(text[pos:s])
        out.append({"fact": payload})
        pos = e
    if pos < end:
        out.append(text[pos:end])
    return out


def _table_block(view: dict, facts_by_ref: dict[str, dict]) -> dict | None:
    columns = view.get("columns") or []
    rows = view.get("rows") or []
    if not columns or not rows:
        return None
    grid, labels = [], []
    for row in rows:
        cells = []
        for col in columns:
            cell = (row.get("cells") or {}).get(col["key"]) or {}
            rec = facts_by_ref.get(cell.get("ref")) if cell.get("ref") else None
            if rec is not None:
                cells.append({"fact": fill(rec)})
            else:
                cells.append({"fact": {"id": None, "kind": "absence", "measure": col["key"], "subject": row.get("subject"),
                                       "display": "not held", "text": str(cell.get("missing") or "not read")}})
        grid.append(cells)
        labels.append(str(row.get("subject") or ""))
    scope = view.get("scope") or {}
    title = ", ".join(registry.reads_as(r["measure"]) for r in view.get("requests") or []) or "analysis"
    if scope.get("basis"):
        title += f" — {scope['basis']}"
    return {"type": "table", "title": title, "header": [c["label"] for c in columns], "labels": labels,
            "explicit": [False for _ in columns], "rows": grid, "view": view.get("view"),
            **({"limitations": view["limitations"]} if view.get("limitations") else {})}


def render(draft: str, verdict: ob.Verdict, views: list[dict], facts_by_ref: dict[str, dict]) -> dict:
    """blocks, citations and the verification record for one answer."""
    marks: list[tuple[int, int, dict]] = []
    for p in verdict.propositions:
        if p.status == ob.SUPPORTED and p.cell and p.cell.ref in facts_by_ref:
            marks.append((p.start, p.end, fill(facts_by_ref[p.cell.ref])))
    blocks: list[dict] = []
    for s, e in _paragraphs(draft or ""):
        blocks.append({"type": "paragraph", "runs": _runs(draft, s, e, marks)})
    cited_views = {p.cell.view for p in verdict.propositions if p.status == ob.SUPPORTED and p.cell}
    for view in views:
        if view.get("view") in cited_views:
            tb = _table_block(view, facts_by_ref)
            if tb:
                blocks.append(tb)
    return {"text": draft, "blocks": blocks, "citations": verdict.citations, "verified": verdict.summary(),
            "validation": verdict.as_dict()}
