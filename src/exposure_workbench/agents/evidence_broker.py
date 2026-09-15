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

from exposure_workbench.services import digest as dg, facts as F, ledger as ledger_svc, program_builder as pb, program_service as ps, trace_service
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

WRITER_ATTEMPTS = 3
# The rendering moved to services/digest in V36, where its reader stopped being
# the lead analyst. These names stay as they were read from here.
PASSAGE_CHARS = dg.PASSAGE_CHARS
DIGEST_CHAR_LIMIT = dg.DIGEST_CHAR_LIMIT

WRITER_SYSTEM = ("You write programs for a portfolio risk desk's calculator. You are given one evidence request and the "
                 "language below; call run_program once with a program that produces exactly the figures asked for, "
                 "over the subjects named, and nothing else. If the executor returns type_errors, fix every problem it "
                 "lists and call again. You never state results and never invent a name: names come from the request and "
                 "the briefing.\n\n" + ps.signature_text())

WRITER_TOOL = {"type": "function", "function": {
    "name": "run_program", "description": "Execute one analysis program.",
    "parameters": {"type": "object", "properties": {"program": ps.schema()}, "required": ["program"], "additionalProperties": False}}}

HOW_TO_CITE = dg.HOW_TO_CITE


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


_reading_of = dg._reading_of
_tell_apart = dg.tell_apart
_fit = dg.fit
_merge = dg.merge
_cited = dg.cited
_stamp_ids = dg.stamp_ids
_display = dg.display


class Broker:
    def __init__(self, tools_session, llm, db_factory, session_id: str, message_id: str | None, briefing: dict | None,
                 examples: list | None = None):
        self._tools = tools_session
        self._minted: list[F.Fact] = []           # the boundaries this digest states, as facts
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
                            "boundaries": [self._boundary("this turn's evidence budget is spent; answer with what you have",
                                                          want=item.get("want"), cls="budget")]})
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
                    got = {"boundaries": [self._boundary(f"the desk could not fulfil {', '.join(part['want'])} ({type(exc).__name__})",
                                                         want=part.get("want"), cls="error")]}
                entry = _merge(entry, got)
            entry["i"] = i
            out.append(entry)
        _tell_apart(out)
        _stamp_ids(out)
        digest = _fit({"items": out, "how_to_cite": HOW_TO_CITE}, DIGEST_CHAR_LIMIT, mint=self._boundary)
        summary = "; ".join(f"item {e['i']}: {len(e.get('figures', []))} figures, {len(e.get('series', []))} series, "
                            f"{len(e.get('passages', []))} passages, {len(e.get('boundaries', []))} boundaries" for e in out)
        minted, self._minted = self._minted, []
        await self._record("digest", {"items": len(items), "writer_calls": self.writer_calls}, summary, facts=minted)
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
            entry["boundaries"].append(self._boundary(sk["reason"], want=sk["want"], subject=(item.get("subjects") or [None])[0],
                                                      nearest=sk.get("nearest")))
        res = None
        if program is not None:
            res = await self._call("run", {"program": program})
            if res.get("error") in ("type_errors", "malformed_program"):
                hint = {"builder": "the compiled program was refused", "problems": res.get("problems")}
                res = None
        if res is None:
            if self._llm is None:
                entry["boundaries"].append(self._boundary(_boundary_text(item, hint), want=item.get("want"),
                                                          subject=(item.get("subjects") or [None])[0]))
                return entry
            program, res = await self._write(item, hint)
            if res is None:
                entry["boundaries"].append(self._boundary(_boundary_text(item, hint), want=item.get("want"),
                                                          subject=(item.get("subjects") or [None])[0]))
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
        dg.absorb(entry, res, subject=subject, mint=self._boundary)

    def _boundary(self, text: str, *, want: Any = None, subject: str | None = None, cls: str = "boundary",
                  code: str | None = None, nearest: list | None = None) -> dict:
        """A boundary minted and kept, so the digest step records it (services/digest)."""
        entry, fact = dg.boundary(text, want=want, subject=subject, cls=cls, code=code, nearest=nearest)
        self._minted.append(fact)
        return entry

    async def _record(self, step_type: str, args: dict, summary: str, facts: list | None = None) -> None:
        try:
            async with self._db_factory() as db:
                step_id = await trace_service.record_step(db, self._session_id, step_type=step_type, tool_name=step_type, args=args,
                                                          result_summary=summary,
                                                          evidence_refs=[ledger_svc.step_entry(facts)] if facts else [],
                                                          message_id=self._message_id)
                for row in ledger_svc.rows_for(facts or [], session_id=self._session_id, step_id=step_id, message_id=self._message_id):
                    db.add(row)
                await db.commit()
        except Exception:  # noqa: BLE001 — a hole in the audit trail beats a lost turn
            logger.exception("could not record %s step for session %s", step_type, self._session_id)


def _empty(item: dict) -> dict:
    return dg.empty(item)


def _boundary_text(item: dict, hint: dict | None) -> str:
    want = ", ".join(item.get("want") or [])
    reason = (hint or {}).get("builder") or "the desk could not express this request"
    near = (hint or {}).get("nearest") or []
    near_txt = ""
    if near:
        names = [n if isinstance(n, str) else (n.get("fix") or n.get("detail") or n.get("name") or "") for n in near]
        near_txt = " Nearest: " + "; ".join(str(x) for x in names[:3] if x)
    return f"the desk could not compute {want} as asked: {reason}.{near_txt}"


