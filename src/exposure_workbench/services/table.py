"""The table (V15-S2a): everything a turn may point at, built once.

WHY THIS EXISTS. What the model saw and what the gate allowed were built by two
mechanisms. The context held tool results as `dumps_capped` left them; the trail
held whatever a walker found id-shaped in the UNcapped result, provided the
result did not look like an error. Nothing tied the two sets together — so a
refused read's `absence_id` never reached the trail (it sat under an `error`
key), a payload cut for size still had every one of its ids citable, and 189 of
191 "unknown" ids in one battery were real rows the gate's set simply did not
hold.

Now there is one set. A tool DECLARES what its result puts on the table
(`declare`); the wrapper BUILDS the table slice from that declaration — the
same names, the same reader-precision values, the same passages — and hands the
slice to the model as `result["table"]` while recording the declaration as the
step's evidence; the gate LOADS the session's table from those declarations and
resolves against it. Names come from services/quantities.py, the one namer, so
the slice the model reads and the set the gate holds cannot differ in spelling.

What is on the table is citable and nothing else is. A collinear coefficient is
not on it (projection, not verification): the model never sees it, so it cannot
name it.

SCOPE. A run holds 235 quantities across seven child tables; a tool that read
one of them should not put all seven on the table, and a payload has a size
cap. A run entry therefore carries the child tables it declares (`scope`) or
the exact names it read (`names`). When the slice would exceed the cap, whole
tables come off the tail of the scope and the declaration shrinks with the
payload — what is stored is what was shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.db.models import AgentStep
from exposure_workbench.services import quantities as qn

# Ids a result can put on the table, and the type each is recorded under.
_PREFIX_TYPE = {
    "fact_": "fact", "chunk_": "chunk", "calc_": "calc", "src_": "source",
    "alert_": "alert", "run_": "run", "pos_": "position",
}
# Delegated work: a row of kind `task`, which an `action` block may point at.
_TASK_PREFIXES = ("task_", "rrun_", "run_")

KIND_TASK = "task"

# Characters of serialized table one tool result may carry. Derived: the
# context soft limit is 80k tokens over at most 15 evidence calls a turn; a
# whole run's quantities at reader precision serialise to ~11k characters
# (~3k tokens) and the run's derived row (net betas, distances to each tier)
# adds ~2.5k, so 16k lets one run arrive whole with its analysis and two
# would not — which is what scope is for.
TABLE_CHAR_LIMIT = 16_000


def _looks_like_id(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(tuple(_PREFIX_TYPE))


def _ids_in(node: Any, out: list[str], seen: set[str]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            _ids_in(v, out, seen)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _ids_in(v, out, seen)
    elif _looks_like_id(node) and node not in seen:
        seen.add(node)
        out.append(node)


def declare(result: dict, *, scope: Sequence[str] | None = None,
            names: Sequence[str] | None = None, tasks: Iterable[str] = ()) -> dict:
    """Mark what this result puts on the table. Returns `result`, with `evidence`.

    Every id-shaped string in the result is declared — this is the tool saying
    "what I returned is what I retrieved", and a refusal that minted an absence
    row declares it the same way a success declares its calc id. A run id is
    declared with the child tables (`scope`) or the exact names (`names`) the
    tool read; a run id with neither is not put on the table at all, because a
    run is not evidence for anything until a child of it has been read.

    `tasks` are ids of delegated work; they go on the table as rows of kind
    `task`, which is what an `action` block points at.
    """
    ids: list[str] = []
    _ids_in(result, ids, set())
    entries: list[dict] = []
    for rid in ids:
        prefix = next(p for p in _PREFIX_TYPE if rid.startswith(p))
        if prefix == "run_":
            if names:
                entries.append({"type": "run", "id": rid, "names": list(names)})
            elif scope:
                entries.append({"type": "run", "id": rid, "scope": list(scope)})
            continue
        entries.append({"type": _PREFIX_TYPE[prefix], "id": rid})
    for tid in tasks:
        if isinstance(tid, str) and tid.startswith(_TASK_PREFIXES):
            entries.append({"type": "task", "id": tid, "kind": KIND_TASK})
    result["evidence"] = entries
    return result


@dataclass
class Table:
    """What a session may point at, resolved."""

    quantities: dict[str, dict[str, qn.Quantity]] = field(default_factory=dict)   # ref -> name -> quantity
    passages: dict[str, str] = field(default_factory=dict)                        # chunk_/src_ -> text
    rows: dict[str, str] = field(default_factory=dict)                            # id -> kind
    refs: set[str] = field(default_factory=set)

    def holds(self, ref: str) -> bool:
        return ref in self.refs

    def names(self, ref: str) -> list[str]:
        return sorted(self.quantities.get(ref, {}))

    def quantity(self, ref: str, name: str) -> qn.Quantity | None:
        return self.quantities.get(ref, {}).get(name)

    def kind(self, ref: str) -> str | None:
        return self.rows.get(ref)


def _filter_run(quantities: Iterable[qn.Quantity], entry: dict) -> list[qn.Quantity]:
    if "names" in entry:
        wanted = set(entry["names"])
        return [q for q in quantities if q.label in wanted]
    scope = entry.get("scope")
    if scope is None:
        # A legacy entry ({type, id}) from before declarations carried scope:
        # the whole run, which is what the old trail let it cite.
        return list(quantities)
    allowed = set(scope)
    return [q for q in quantities if q.table in allowed]


async def _place(db: AsyncSession, table: Table, entry: dict) -> None:
    """Resolve one declared entry onto `table`."""
    rid = entry.get("id")
    if not isinstance(rid, str):
        return
    if entry.get("type") == "task":
        table.rows[rid] = KIND_TASK
        table.refs.add(rid)
        return
    r = await qn.of_ref(db, rid)
    if r.kind is None:
        return
    qs = list(r.quantities)
    if r.kind == "run":
        qs = _filter_run(qs, entry)
    # Projection: a quantity the row says may not stand alone is not on the
    # table. The sum the regression does determine is a separate quantity.
    qs = [q for q in qs if q.not_alone is None]
    table.refs.add(rid)
    table.rows[rid] = r.kind
    if qs:
        slot = table.quantities.setdefault(rid, {})
        for q in qs:
            slot.setdefault(q.label, q)
    if r.text is not None:
        table.passages[rid] = r.text


def _payload(table: Table, order: list[str]) -> dict:
    """The slice as the model reads it: names to reader-precision values."""
    out: dict = {}
    qs = {ref: {name: dc.reader_value(q.value, q.unit_class) for name, q in table.quantities[ref].items()}
          for ref in order if ref in table.quantities}
    if qs:
        out["quantities"] = qs
    passages = [ref for ref in order if ref in table.passages]
    if passages:
        out["passages"] = passages
    rows = {ref: kind for ref in order if (kind := table.rows.get(ref)) in (qn.KIND_SERIES, qn.KIND_ABSENCE, KIND_TASK)}
    if rows:
        out["rows"] = rows
    return out


async def build(db: AsyncSession, declared: list[dict] | None,
                limit: int = TABLE_CHAR_LIMIT) -> tuple[list[dict], dict]:
    """The slice for one tool result: (declaration as stored, payload as shown).

    When the slice is over `limit`, run scopes lose tables off their tail until
    it fits; the returned declaration is the narrowed one, so the record and the
    payload say the same thing. A slice that cannot fit at all is declared
    empty rather than cut mid-quantity.
    """
    declared = [dict(e) for e in (declared or [])]
    if not declared:
        return [], {}
    while True:
        table = Table()
        for entry in declared:
            await _place(db, table, entry)
        order = [e["id"] for e in declared if isinstance(e.get("id"), str)]
        payload = _payload(table, order)
        if len(json.dumps(payload)) <= limit:
            return declared, payload
        # Narrow: the last run entry with a scope still holding tables loses its
        # last table. Names are exact reads and are not narrowed.
        narrowed = False
        for entry in reversed(declared):
            if entry.get("type") == "run" and entry.get("scope"):
                dropped = entry["scope"].pop()
                entry.setdefault("truncated", []).append(dropped)
                narrowed = True
                break
        if not narrowed:
            return [], {"truncated": {"detail": "the result's evidence did not fit the "
                                                "message size limit; request it by name"}}


async def load(db: AsyncSession, session_id: str) -> Table:
    """The session's whole table: the union of every completed step's declaration.

    Session-scoped by construction — an id retrieved four turns ago is on this
    turn's table (V15 §6). Session boundaries are tenant and audit boundaries,
    and nothing from another session is here.
    """
    rows = (await db.execute(
        select(AgentStep.evidence_refs).where(
            AgentStep.session_id == session_id, AgentStep.status == "completed"))).all()
    table = Table()
    for (refs,) in rows:
        for entry in refs or []:
            if isinstance(entry, dict):
                await _place(db, table, entry)
    return table


def ids_of(table: Table) -> list[str]:
    return sorted(table.refs)
