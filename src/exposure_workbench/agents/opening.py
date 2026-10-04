"""`open`: anything already on the turn's record, by id. Reads; pulls nothing new.

    calc_…           an analysis view, whole (this turn's, or an earlier turn's of the conversation)
    f_…              one row of the ledger, with its identity and its kind
    method:<name>    a measure's full registry entry (services/method_index)
    handbook:<x>     a specialist's chapter of the handbook (analytics/handbook)
    tsk_…            a task's record: what it was asked, what it wrote, how it ended
"""

from __future__ import annotations

from exposure_workbench.agents import work_view as wvm
from exposure_workbench.analytics import handbook
from exposure_workbench.analytics import value_semantics as vs
from exposure_workbench.services import analyst_reports, facts as F, ledger as ledger_svc, method_index as mi

PAGE_CHARS = 12_000


def _err(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


def fact_page(rec: dict, offset: int = 0) -> dict:
    identity = {k: rec.get(k) for k in ("id", "kind", "subject", "measure", "unit", "value", "as_of", "window", "sources", "params")}
    out = {"row": F.line(rec), "identity": identity, "semantic": vs.of(rec.get("params")).as_params()}
    text = rec.get("text")
    if isinstance(text, str) and rec.get("kind") == F.PASSAGE:
        offset = max(0, offset)
        page = text[offset:offset + PAGE_CHARS]
        out.update({"text": page, "total": len(text), "shown": [offset, offset + len(page)],
                    "next_offset": offset + len(page) if offset + len(page) < len(text) else None})
    return out


async def open_ref(db_factory, session_id: str, ref: str, *, offset: int = 0, work: wvm.WorkView | None = None) -> dict:
    ref = (ref or "").strip()
    if not ref:
        return _err("no_id", "open takes a view (calc_…), a row (f_…), method:<name>, handbook:<analyst> or a task (tsk_…)")
    if ref.startswith("method:"):
        return mi.detail(ref.partition(":")[2].strip())
    if ref.startswith("handbook:"):
        analyst = ref.partition(":")[2].strip()
        if analyst not in handbook.CHAPTERS:
            return _err("unknown_handbook", f"the handbook has chapters for {', '.join(handbook.CHAPTERS)}")
        return {"chapter": handbook.chapter_text(analyst), "source": "method guidance, not factual evidence"}
    if ref.startswith("calc_"):
        view = work.view_by_id(ref) if work is not None else None
        if view is None:
            async with db_factory() as db:
                view = await wvm.load_view(db, session_id, ref)
        if view is None:
            return _err("unknown_view", f"{ref} is not an analysis view of this conversation")
        if work is not None:
            work.seen_views.add(ref)
        return {"view": view}
    if ref.startswith("tsk_"):
        async with db_factory() as db:
            rep = await analyst_reports.load_by_task(db, session_id, ref)
        if not rep:
            return _err("unknown_task", f"{ref} is not a task of this conversation")
        return {"task": ref, "analyst": rep["domain"], "status": rep["status"], "text": rep["text"],
                "verification": (rep.get("verified") or {}), "brief": rep.get("brief") or {}}
    if ref.startswith(F.PREFIX):
        async with db_factory() as db:
            led = await ledger_svc.load(db, session_id)
        rec = led.by_id.get(ref)
        if rec is None:
            return _err("not_on_the_record", "no such row in this conversation")
        return fact_page(rec, offset)
    return _err("unknown_id", "open takes a view (calc_…), a row (f_…), method:<name>, handbook:<analyst> or a task (tsk_…)")
