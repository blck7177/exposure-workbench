"""The evidence broker (V33): where tool and skill are operated, on the analyst's behalf.

It takes the analyst's request items and comes back with facts and boundaries.
Nothing else: it does not interpret a figure and it writes no sentence a reader
sees. Three kinds of item map straight to a tool (prepare → start, filings: →
read_filings, news: → search_web); every other kind is compiled by
services/program_builder into a program and run; what the builder cannot say
goes, with the analyst's own words, to a program writer that reads the
language's signatures and gets the executor's type report back — a loop the
analyst never sees.

It runs INSIDE the analyst's turn: the same session, the same message, the same
tool-face token. That is what puts its facts on the ledger the answer check
reads. A broker in a session of its own would leave the analyst unable to cite
anything it fetched.

The digest it returns shows every figure as the reader will see it (display
value, unit, subject, measure, as-of) with its id, and every value in it is a
fact on the ledger — the round's Q14 was a date shown to the model with no id
behind it, and the model was refused for writing it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.services import claims, program_builder as pb, program_service as ps, trace_service
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

PASSAGE_CHARS = 6_000          # of a passage's text the digest carries; the fact holds it whole
WRITER_ATTEMPTS = 3
# The digest is the only thing the analyst reads, so the digest owns the budget:
# `_fit` trims rows and says what it held back. It must stay UNDER the loop's
# message cap (meta_agent.TOOL_RESULT_LIMIT, 28 000), or that cap drops a whole
# request's answer with no idea which — V33D lost the 30 betas a question asked
# for and the analyst wrote "the desk truncated both requests".
DIGEST_CHAR_LIMIT = 24_000

WRITER_SYSTEM = ("You write programs for a portfolio risk desk's calculator. You are given one evidence request and the "
                 "language below; call run_program once with a program that produces exactly the figures asked for, "
                 "over the subjects named, and nothing else. If the executor returns type_errors, fix every problem it "
                 "lists and call again. You never state results and never invent a name: names come from the request and "
                 "the briefing.\n\n" + ps.signature_text())

WRITER_TOOL = {"type": "function", "function": {
    "name": "run_program", "description": "Execute one analysis program.",
    "parameters": {"type": "object", "properties": {"program": ps.schema()}, "required": ["program"], "additionalProperties": False}}}

HOW_TO_CITE = ("Write each figure exactly as its `value` reads here — that form is unique on this desk, so it needs no "
               "pointer of any kind. Where a `value` carries a date in brackets, another reading of the same figure reads "
               "the same and the date is what tells them apart: keep it in your sentence. "
               "A series shows its points as [date, value]: write a point's value as shown and name its date. "
               "[table: <node>] or [chart: <node>] shows a node's figures. Quote a passage's words verbatim inside quotation marks. "
               "A boundary is something the desk could not do or does not hold: say so in your own words.")


def _kind_of(item: dict) -> str:
    first = (item.get("want") or [""])[0].lower()
    if first == "prepare":
        return "prepare"
    if first.startswith("filings:"):
        return "filings"
    if first.startswith("news:"):
        return "news"
    return "program"


def _want_kind(w: str) -> str:
    lw = str(w).strip().lower()
    if lw == "prepare":
        return "prepare"
    if lw.startswith("filings:"):
        return "filings"
    if lw.startswith("news:"):
        return "news"
    return "program"


def _split(item: dict) -> list[tuple[str, dict]]:
    """One request item by the kind of each want: the analyst asks for margins
    and the Item 7 passage in one breath (V33C Q04), and each kind has its
    own door. Order: what the tools read first, then the program."""
    groups: dict[str, list[str]] = {}
    for w in item.get("want") or []:
        groups.setdefault(_want_kind(w), []).append(w)
    order = ("prepare", "filings", "news", "program")
    # a derivation is arithmetic over the program's own names; the tool doors take none
    return [(k, {**item, "want": groups[k], **({} if k == "program" else {"derive": None})}) for k in order if k in groups]


def _reading_of(fig: dict) -> tuple:
    return (fig.get("subject"), fig.get("measure"), fig.get("as_of"), str(fig.get("value")))


def _tell_apart(items: list[dict]) -> None:
    """A — SHOWN UNIQUENESS. Across the whole digest: one reading is shown once,
    and two readings never read alike.

    The analyst writes what it is shown, so what it is shown has to be enough to
    tell apart. V33D refused 240 figures over the same series fetched twice and
    V33E 38 over one holding in two runs; both collisions were the desk's own.
    A duplicate reading collapses to one entry naming the other ids (they are the
    same figure); a genuine pair that reads alike takes its date into the value,
    so copying it puts the discriminator in the sentence."""
    figures = [f for e in items for f in (e.get("figures") or [])]
    seen: dict[tuple, dict] = {}
    for e in items:
        kept = []
        for f in e.get("figures") or []:
            key = _reading_of(f)
            first = seen.get(key)
            if first is None:
                seen[key] = f
                kept.append(f)
            else:
                first.setdefault("also", []).append(f["id"])    # the same reading, fetched twice
        e["figures"] = kept
    figures = [f for e in items for f in (e.get("figures") or [])]
    by_written: dict[tuple, list[dict]] = {}
    for f in figures:
        by_written.setdefault((f.get("subject"), f.get("measure"), str(f.get("value"))), []).append(f)
    for group in by_written.values():
        if len(group) > 1 and len({f.get("as_of") for f in group}) > 1:
            for f in group:
                if f.get("as_of"):
                    f["value"] = f"{f['value']} ({f['as_of']})"
                    f["reads_alike"] = "another reading of this figure reads the same; its date tells them apart"


def _fit(digest: dict, limit: int) -> dict:
    """The digest within its cap by holding back the TAIL ROWS of the largest
    figure list, then trimming passage texts — never a whole item. V33D: two
    items of 96 and 30 figures ran past the cap, dumps_capped dropped an item
    whole, and the analyst wrote 'the desk truncated both requests'."""
    def size() -> int:
        return len(ejson.dumps(digest))
    items = digest.get("items") or []
    guard = 0
    while size() > limit and guard < 200:
        guard += 1
        biggest = max(items, key=lambda e: len(e.get("figures") or []), default=None)
        if biggest is None or len(biggest.get("figures") or []) <= 5:
            break
        figs = biggest["figures"]
        cut = max(1, len(figs) // 10)
        dropped, biggest["figures"] = figs[-cut:], figs[:-cut]
        note = next((b for b in biggest["boundaries"] if b.get("class") == "held_back" and b.get("by") == "digest"), None)
        if note is None:
            note = {"class": "held_back", "by": "digest", "count": 0, "measures": [],
                    "text": "figures computed and on the ledger but not shown here: the request was too wide for one "
                            "digest; ask again for the names you need"}
            biggest["boundaries"].append(note)
        note["count"] += len(dropped)
        note["measures"] = sorted({f"{f.get('subject')}:{f.get('measure')}" for f in dropped} | set(note["measures"]))[:30]
    guard = 0
    while size() > limit and guard < 50:
        guard += 1
        longest = max((p for e in items for p in (e.get("passages") or [])), key=lambda p: len(p.get("text") or ""), default=None)
        if longest is None or len(longest.get("text") or "") <= 800:
            break
        longest["text"] = longest["text"][: max(800, len(longest["text"]) // 2)]
        longest["shown_chars"] = len(longest["text"])
    return digest


def _merge(into: dict, part: dict) -> dict:
    for k in ("figures", "series", "passages", "started", "boundaries"):
        into[k] = list(into.get(k) or []) + list(part.get(k) or [])
    for k in ("program", "nodes"):
        if part.get(k) is not None:
            into[k] = part[k]
    return into


def _display(value: Any, unit: str | None) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return dc.display(float(value), unit) if unit else value
        except Exception:  # noqa: BLE001 — a unit display has no business failing a digest
            return value
    return value


class Broker:
    def __init__(self, tools_session, llm, db_factory, session_id: str, message_id: str | None, briefing: dict | None,
                 examples: list | None = None):
        self._tools = tools_session
        self._llm = llm
        self._db_factory = db_factory
        self._session_id = session_id
        self._message_id = message_id
        self._briefing = briefing or {}
        # the skill's worked programs for the question's domains: the writer's
        # reference for a shape the builder cannot compile (V33D Q14 wrote
        # explain_episode seven ways; the skill has the program)
        self._examples = list(examples or [])[:4]
        self._pool_empty = False
        self.writer_calls = 0

    # ── the entry ────────────────────────────────────────────────────────────
    async def fulfil(self, items: list[dict]) -> dict:
        await self._record("request", {"items": items}, f"{len(items)} item(s): " + ", ".join(_kind_of(i) for i in items))
        out: list[dict] = []
        for i, item in enumerate(items):
            if self._pool_empty:
                out.append({"i": i, "request": item, "figures": [], "series": [], "passages": [], "started": [],
                            "boundaries": [{"class": "budget", "text": "this turn's evidence budget is spent; answer with what you have"}]})
                continue
            entry = _empty(item)
            for kind, part in _split(item):
                try:
                    if kind == "prepare":
                        got = await self._prepare(part)
                    elif kind == "filings":
                        got = await self._filings(part)
                    elif kind == "news":
                        got = await self._news(part)
                    else:
                        got = await self._program(part)
                except Exception as exc:  # noqa: BLE001 — one part's failure is one boundary, never a lost turn
                    logger.exception("broker item %d (%s) failed", i, kind)
                    got = {"boundaries": [{"class": "error", "text": f"the desk could not fulfil {', '.join(part['want'])} ({type(exc).__name__})"}]}
                entry = _merge(entry, got)
            entry["i"] = i
            out.append(entry)
        _tell_apart(out)
        digest = _fit({"items": out, "how_to_cite": HOW_TO_CITE}, DIGEST_CHAR_LIMIT)
        summary = "; ".join(f"item {e['i']}: {len(e.get('figures', []))} figures, {len(e.get('series', []))} series, "
                            f"{len(e.get('passages', []))} passages, {len(e.get('boundaries', []))} boundaries" for e in out)
        await self._record("digest", {"items": len(items), "writer_calls": self.writer_calls}, summary)
        return digest

    # ── the three tool-shaped items ──────────────────────────────────────────
    async def _prepare(self, item: dict) -> dict:
        entry = _empty(item)
        # The catalogue's own answer to "is this issuer ready", read here because
        # `start` does not refuse a company it has already prepared. When it does,
        # this drops (§6).
        desk = self._briefing.get("desk") or {}
        on_desk = {t.upper() for t in (desk.get("issuers_on_desk") or [])}
        preparing = {t.upper() for t in (desk.get("issuers_preparing") or [])}
        for t in item["subjects"]:
            tk = t.upper()
            if tk in on_desk:
                # V33C Q12: readiness was started for JPM, which was on the desk all along
                entry["boundaries"].append({"class": "note", "subject": tk, "text": f"{tk} is already on the desk: ask for its figures by name"})
                continue
            if tk in preparing:
                entry["boundaries"].append({"class": "note", "subject": tk, "text": f"{tk} is being prepared; its figures arrive in the background"})
                continue
            res = await self._call("start", {"kind": "readiness", "subject": tk,
                                             "reason": item.get("ask") or "the question needs this issuer on the desk"})
            self._absorb(entry, res, subject=tk)
        return entry

    async def _filings(self, item: dict) -> dict:
        entry = _empty(item)
        spec = item["want"][0].split(":", 1)[1].strip()
        import re
        m = re.fullmatch(r"(?:item\s*)?(\d{1,2}[A-C]?)", spec, flags=re.IGNORECASE)
        for t in item["subjects"]:
            args = {"ticker": t.upper()}
            if m:
                args["item"] = m.group(1).upper()
            else:
                args["query"] = spec or (item.get("ask") or "")
                args["k"] = 5
            self._absorb(entry, await self._call("read_filings", args), subject=t.upper())
        return entry

    async def _news(self, item: dict) -> dict:
        entry = _empty(item)
        query = item["want"][0].split(":", 1)[1].strip() or (item.get("ask") or "material news")
        days = pb.parse_window(item.get("window")).days or 14
        for t in item["subjects"]:
            self._absorb(entry, await self._call("search_web", {"ticker": t.upper(), "query": query, "days": days,
                                                                "reason": item.get("ask") or "the question asks what happened recently"}),
                         subject=t.upper())
        return entry

    # ── programs ─────────────────────────────────────────────────────────────
    async def _program(self, item: dict) -> dict:
        entry = _empty(item)
        hint: dict | None = None
        held_in = {tk: [h.get("portfolio_id") for h in (d.get("held_in") or []) if isinstance(h, dict) and h.get("portfolio_id")]
                   for tk, d in (self._briefing.get("issuers") or {}).items() if isinstance(d, dict)}
        skipped: list[dict] = []
        try:
            program = pb.build(item, held_in=held_in, skipped=skipped)
        except pb.NotExpressible as e:
            program, hint = None, {"builder": e.reason, "nearest": e.nearest}
        for sk in skipped:
            # what the desk could not say, said — one name, not the whole request
            entry["boundaries"].append({"class": "boundary", "want": sk["want"], "text": sk["reason"],
                                        **({"nearest": sk["nearest"][:4]} if sk.get("nearest") else {})})
        res = None
        if program is not None:
            res = await self._call("run", {"program": program})
            if res.get("error") in ("type_errors", "malformed_program"):
                hint = {"builder": "the compiled program was refused", "problems": res.get("problems")}
                res = None
        if res is None:
            if self._llm is None:
                entry["boundaries"].append({"class": "boundary", "text": _boundary_text(item, hint)})
                return entry
            program, res = await self._write(item, hint)
            if res is None:
                entry["boundaries"].append({"class": "boundary", "text": _boundary_text(item, hint)})
                return entry
        entry["program"] = program
        self._absorb(entry, res)
        return entry

    async def _write(self, item: dict, hint: dict | None) -> tuple[dict | None, dict | None]:
        """The program writer: the request, the hint, the briefing's names for its
        subjects; the language in its system prompt; the executor's type report
        as the tool result. Up to WRITER_ATTEMPTS programs. Reached only when the
        builder could compile NOTHING — a request the language can express is
        compiled, never written twice."""
        excerpt = {s: (self._briefing.get("issuers", {}).get(s) or self._briefing.get("portfolios", {}).get(s))
                   for s in item.get("subjects", [])}
        for v in excerpt.values():
            if isinstance(v, dict):
                v.pop("items_indexed", None)
                v.pop("held_in", None)
        user: dict = {"request": item, "hint": hint, "subjects": excerpt}
        if self._examples:
            user["worked_examples"] = [{"title": t, "program": (json.loads(pr) if isinstance(pr, str) else pr)}
                                       for t, pr in self._examples if pr]
        messages = [{"role": "system", "content": WRITER_SYSTEM},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)[:16_000]}]
        last: dict | None = None
        for _ in range(WRITER_ATTEMPTS):
            self.writer_calls += 1
            content, tool_calls = await self._llm.chat(messages=messages, tools=[WRITER_TOOL], temperature=0.0)
            msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)
            if not tool_calls:
                messages.append({"role": "user", "content": "Call run_program with the program."})
                continue
            tc = tool_calls[0]
            try:
                program = json.loads(tc["function"].get("arguments") or "{}").get("program")
            except (json.JSONDecodeError, AttributeError, TypeError):
                program = None
            if not isinstance(program, dict):
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps({"error": "malformed_program", "detail": "program is {let: [...]}"})})
                continue
            res = await self._call("run", {"program": program})
            last = res
            if res.get("error") in ("type_errors", "malformed_program"):
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": ejson.dumps_capped(res, 12_000)})
                continue
            return program, res
        return None, None if (last is None or last.get("error")) else last

    # ── plumbing ─────────────────────────────────────────────────────────────
    async def _call(self, name: str, args: dict) -> dict:
        res = await self._tools.call(name, args)
        if isinstance(res, dict) and res.get("error") == "budget_exceeded" and res.get("kind") in ("turn_tool", "tool"):
            self._pool_empty = True
        return res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}

    def _absorb(self, entry: dict, res: dict, subject: str | None = None) -> None:
        """A tool result into the digest: figures, series, passages, tasks and
        boundaries — every one from the result's facts block, so every value
        the analyst reads is on the ledger."""
        if not isinstance(res, dict):
            return
        if res.get("error") and "facts" not in res:
            cls = {"budget_exceeded": "budget", "type_errors": "type", "malformed_program": "type",
                   "not_prepared": "data_absent", "company_not_found": "data_absent", "not_listed": "data_absent",
                   "not_indexed": "data_absent", "active_run_exists": "data_absent", "not_investigable": "data_absent",
                   "not_an_sec_filer": "data_absent"}.get(res["error"], "error")
            text = res.get("detail") or res["error"]
            if res.get("problems"):
                text += " — " + "; ".join((p.get("fix") or p.get("detail") or p.get("reason", "")) for p in res["problems"][:3] if isinstance(p, dict))
            entry["boundaries"].append({"class": cls, "code": res["error"], "text": str(text)[:600], **({"subject": subject} if subject else {})})
            return
        if res.get("enqueued"):
            entry["started"].append({"kind": res.get("kind"), "subject": res.get("ticker") or res.get("portfolio_id") or subject,
                                     "task": res.get("task_id") or res.get("run_id")})
        block = res.get("facts") or {}
        cols, rows = block.get("columns") or [], block.get("rows") or []
        for row in rows:
            rec = dict(zip(cols, row))
            params = rec.get("params") or {}
            kind = rec.get("kind")
            if kind == "scalar":
                fig = {"id": rec["id"], "subject": rec.get("subject"), "measure": rec.get("measure"),
                       "value": _display(rec.get("value"), rec.get("unit")), "unit": rec.get("unit"), "as_of": rec.get("as_of")}
                if rec.get("window"):
                    fig["window"] = rec["window"]
                for k in ("node", "rank", "op", "label", "method"):
                    if params.get(k) is not None:
                        fig[k] = params[k]
                entry["figures"].append(fig)
            elif kind == "series":
                val = rec.get("value") or {}
                pts = val.get("points") if isinstance(val, dict) else None
                s = {"id": rec["id"], "subject": rec.get("subject"), "measure": rec.get("measure"), "unit": rec.get("unit"),
                     "n": (val.get("n") if isinstance(val, dict) else None), "node": params.get("node")}
                if pts:
                    s["first"], s["last"] = [pts[0][0], _display(pts[0][1], rec.get("unit"))], [pts[-1][0], _display(pts[-1][1], rec.get("unit"))]
                    if len(pts) <= 12:
                        s["points"] = [[p, _display(v, rec.get("unit"))] for p, v in pts]
                entry["series"].append(s)
            elif kind == "passage":
                val = rec.get("value")
                text = val.get("text") if isinstance(val, dict) else (val if isinstance(val, str) else "")
                entry["passages"].append({"id": rec["id"], "subject": rec.get("subject"), "title": rec.get("measure"),
                                          "text": (text or "")[:PASSAGE_CHARS], "chars": len(text or ""),
                                          **({k: v for k, v in params.items() if k in ("item", "form_type", "accession", "url", "source_url")})})
            elif kind == "absence":
                err = params.get("error") or ((params.get("root") or {}).get("error") if isinstance(params.get("root"), dict) else None)
                if params.get("reason") in ("not_held", "cannot"):
                    cls = "data_absent"
                else:
                    cls = "type" if err in claims.SPELLING_REFUSALS else "data_absent"
                entry["boundaries"].append({"class": cls, "fact": rec["id"], "node": params.get("node"), "code": err,
                                            "text": str(rec.get("value") or "")[:400]})
            elif kind == "task":
                entry["started"].append({"task": rec["id"], "text": str(rec.get("value") or "")[:200]})
        nodes = res.get("nodes")
        if isinstance(nodes, dict):
            entry["nodes"] = [n for n in nodes if not str(n).startswith("_")]
        if res.get("held_back"):
            entry["boundaries"].append({"class": "held_back", "text": f"{res['held_back'].get('count')} more figures were computed and not shown; "
                                                                      f"request fewer names, or name the ones you need", "measures": res["held_back"].get("measures", [])[:20]})

    async def _record(self, step_type: str, args: dict, summary: str) -> None:
        try:
            async with self._db_factory() as db:
                await trace_service.record_step(db, self._session_id, step_type=step_type, tool_name=step_type, args=args,
                                                result_summary=summary, evidence_refs=[], message_id=self._message_id)
                await db.commit()
        except Exception:  # noqa: BLE001 — a hole in the audit trail beats a lost turn
            logger.exception("could not record %s step for session %s", step_type, self._session_id)


def _empty(item: dict) -> dict:
    return {"request": {k: item.get(k) for k in ("subjects", "want", "window", "compare", "derive", "ask") if item.get(k)},
            "figures": [], "series": [], "passages": [], "started": [], "boundaries": []}


def _boundary_text(item: dict, hint: dict | None) -> str:
    want = ", ".join(item.get("want") or [])
    reason = (hint or {}).get("builder") or "the desk could not express this request"
    near = (hint or {}).get("nearest") or []
    near_txt = ""
    if near:
        names = [n if isinstance(n, str) else (n.get("fix") or n.get("detail") or n.get("name") or "") for n in near]
        near_txt = " Nearest: " + "; ".join(str(x) for x in names[:3] if x)
    return f"the desk could not compute {want} as asked: {reason}.{near_txt}"


