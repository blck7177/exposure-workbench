"""The protocol between the lead and the desk's specialists: `ask`, and what a task is.

The lead asks one of three specialists — the issuer analyst (filings), the market
analyst (prices), the portfolio risk manager (the book) — for work that needs an
independent reading: the text of a filing, a method that is not a measure over
subjects, a judgement the lead wants made by the analyst whose evidence it is.
A task is the lead's own words plus a scope; the runtime binds the scope's handle,
so a specialist never receives an internal id to copy.

What a specialist returns is prose, read by the observer and merged into the work
view with its products (the analyses it ran, the rows it read). There is no
submission step and no accounting of task lines: the lead reads what came back
against the original question.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from exposure_workbench.analytics import handbook
from exposure_workbench.llm import client as llm_client
from exposure_workbench.utils.ids import new_id

ASK_TOOL_NAME = "ask"
OPEN_TOOL_NAME = "open"
ANALYSTS: tuple[str, ...] = handbook.ANALYSTS
MAX_TASKS = 3
MAX_LINES = 8

ASK_TOOL = llm_client.function_tool(
    ASK_TOOL_NAME,
    ("Ask a specialist for work that needs its own reading of the evidence: the text of a filing, a method of its "
     "family that is not a measure over subjects, an interpretation you want made by the analyst who holds the data. "
     "Pick the specialist by the family of evidence — the issuer analyst reads filings, the market analyst prices, "
     "the portfolio risk manager the book — give it a scope (subjects, or a book with a sector) and say what you want "
     "to know in short lines, in financial language. The specialist writes back in prose; its analyses and the rows "
     "it read land in the STATE block. Analyses over named measures you can run yourself with `analyze`."),
    {"type": "object", "properties": {
        "tasks": {"type": "array", "minItems": 1, "maxItems": MAX_TASKS, "items": {
            "type": "object", "properties": {
                "analyst": {"type": "string", "enum": list(ANALYSTS)},
                "scope": {"type": "object", "properties": {
                    "subjects": {"type": ["array", "null"], "items": {"type": "string"}},
                    "book": {"type": ["string", "null"]},
                    "sector": {"type": ["string", "null"]},
                    "holdings": {"type": ["string", "null"], "enum": ["all", None]},
                    "expected_count": {"type": ["integer", "null"], "minimum": 1},
                    "basis": {"type": ["string", "null"]}},
                    "additionalProperties": False},
                "lines": {"type": "array", "minItems": 1, "maxItems": MAX_LINES, "items": {"type": "string"}},
                "context": {"type": ["string", "null"], "description": "one sentence on what the answer is for"}},
            "required": ["analyst", "scope", "lines"], "additionalProperties": False}}},
     "required": ["tasks"], "additionalProperties": False})

OPEN_TOOL = llm_client.function_tool(
    OPEN_TOOL_NAME,
    ("Open something already on this turn's record, by id: an analysis view (calc_…), a row of one (f_…), a "
     "measure's full entry (method:<name>), a specialist's chapter of the handbook (handbook:issuer | market | risk), "
     "or a task's log (tsk_…). Reads; it cannot pull a new figure."),
    {"type": "object", "properties": {"id": {"type": "string"},
                                      "offset": {"type": ["integer", "null"], "minimum": 0}},
     "required": ["id"], "additionalProperties": False})


class BadAsk(ValueError):
    """The call was not an ask. Told to the caller, never raised at the turn."""


@dataclass(frozen=True)
class Task:
    task_id: str
    analyst: str
    scope: dict
    lines: tuple[str, ...]
    context: str | None = None

    def as_dict(self) -> dict:
        out: dict = {"task_id": self.task_id, "analyst": self.analyst, "scope": self.scope,
                     "lines": [f"{i}. {w}" for i, w in enumerate(self.lines, 1)]}
        if self.context:
            out["context"] = self.context
        return out


def parse_tasks(args: dict) -> list[Task]:
    """The tasks of one ask. Two tasks for the same specialist over the same scope are
    ONE task: their lines are joined, because the error class "asked twice in one
    call" is removed here rather than refused and explained."""
    if not isinstance(args, dict) or not isinstance(args.get("tasks"), list) or not args["tasks"]:
        raise BadAsk("ask takes {tasks: [{analyst, scope, lines, context?}]}")
    if len(args["tasks"]) > MAX_TASKS:
        raise BadAsk(f"at most {MAX_TASKS} tasks in one call; ask the rest after you read these")
    merged: dict[tuple, dict] = {}
    for i, t in enumerate(args["tasks"]):
        if not isinstance(t, dict):
            raise BadAsk(f"tasks[{i}] is not an object")
        analyst = str(t.get("analyst") or "").strip()
        if analyst not in ANALYSTS:
            raise BadAsk(f"tasks[{i}].analyst {analyst!r} is not one of the desk's specialists: {', '.join(ANALYSTS)}")
        scope = t.get("scope") if isinstance(t.get("scope"), dict) else {}
        scope = {k: v for k, v in scope.items() if v not in (None, [], "")}
        if "subjects" in scope:
            scope["subjects"] = [str(s).strip().upper() for s in scope["subjects"] if str(s).strip()]
        if not scope:
            raise BadAsk(f"tasks[{i}].scope names subjects, or a book with a sector or holdings='all'")
        lines = t.get("lines")
        if isinstance(lines, str):
            lines = [lines]
        lines = [str(w).strip() for w in (lines or []) if str(w).strip()]
        if not lines:
            raise BadAsk(f"tasks[{i}].lines is a non-empty list of things you want to know")
        key = (analyst, tuple(sorted(scope.get("subjects") or [])), scope.get("book"), scope.get("sector"), scope.get("holdings"))
        if key in merged:
            merged[key]["lines"] = list(dict.fromkeys([*merged[key]["lines"], *lines]))[:MAX_LINES]
            merged[key]["context"] = merged[key]["context"] or (t.get("context") or None)
        else:
            merged[key] = {"analyst": analyst, "scope": scope, "lines": lines[:MAX_LINES], "context": t.get("context") or None}
    return [Task(task_id=new_id("tsk_"), analyst=m["analyst"], scope=m["scope"], lines=tuple(m["lines"]),
                 context=m["context"]) for m in merged.values()]


def roster_text() -> str:
    """Who can be asked for what, in a line each — no measure key, no verb."""
    lines = ["THE DESK'S SPECIALISTS (ask)"]
    for c in handbook.CHAPTERS.values():
        absent = "; ".join(what for what, _why in c.absent[:3])
        lines.append(f"- {c.analyst}: {c.answers}." + (f" Absent there: {absent}." if absent else ""))
    return "\n".join(lines)
