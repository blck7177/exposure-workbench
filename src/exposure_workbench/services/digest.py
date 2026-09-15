"""The digest (V36): a tool's result as an analyst reads it.

Every figure shown the way the reader will see it — display value, unit,
subject, measure, as-of, and its place in any ordering the desk built — each
carrying the id it is shown under, as one string: `16.0% [f_2592baab170e]`.
Writing a figure as shown is therefore writing it pointed, and the answer check
is a lookup rather than a guess about which fact a number meant.

Two rules this module exists to keep:

  EVERY VALUE SHOWN IS A FACT ON THE LEDGER. A date shown with no id behind it
  was written by the model and refused (V33 Q14); the desk's own words for what
  it could not do were quoted and refused, because they had been shown and never
  recorded (round G). So a boundary is minted as an absence fact here, and the
  caller puts what `Minter` collected on the ledger.

  ONE READING IS SHOWN ONCE. A reading fetched twice collapses to one entry
  naming the other ids (V33D: one series asked for twice, 240 refusals). The
  caller carries `seen` across a session's calls, so the collapse spans the
  whole of what one analyst has been shown rather than one call.

It was `agents/evidence_broker` until V36, where the reader of a digest stopped
being the lead analyst and became the domain analyst that asked for it. Nothing
about the rendering changed with the move except that `place` and `of` are now
shown: the broker computed an ordering, put it on the ledger, and did not show
it, so a superlative the evidence already settled had no visible support (V33J
Q11 called MSFT "closest" and was refused for it).
"""

from __future__ import annotations

import logging
from typing import Any

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.services import claims, facts as F
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# Of a passage's text the digest carries; the fact holds it whole.
PASSAGE_CHARS = 6_000

# The digest owns the reader's budget, so it must stay UNDER the loop's own
# message cap — a loop-level cap drops a whole result with no idea which part
# mattered (V33D lost the 30 betas a question asked for, and the analyst wrote
# "the desk truncated both requests"). `fit` trims rows instead and says what it
# held back, as a fact.
DIGEST_CHAR_LIMIT = 24_000

HOW_TO_CITE = (
    "Write each figure exactly as its `value` reads here, bracket included: the bracket is the desk's id for "
    "that reading, it is what lets the reader open the figure, and a figure written without it is refused. "
    "A series shows its points as [date, value]: write a point's value as shown, bracket included — the bracket names the point's date. "
    "A bracket after a quotation or a name cites that fact. "
    "`place` is the figure's rank among the entries of its node, `of` how many there are: a superlative rests on that. "
    "[table: <node>] or [chart: <node>] shows a node's figures. Quote a passage's words verbatim inside quotation marks; "
    "a boundary is the desk's own words for what it could not do — quote it the same way, or say it in yours.")

# What a figure carries besides its value and identity: the node it came from,
# its place in that node's ordering, the operation that made it, its label and
# method. `place`/`of` are V36 — see the module docstring.
_FIGURE_PARAMS = ("node", "rank", "place", "of", "op", "label", "method")

_REQUEST_KEYS = ("subjects", "want", "window", "compare", "derive", "ask")


def empty(request: dict | None = None) -> dict:
    """A blank entry, echoing the request that will fill it."""
    req = {k: (request or {}).get(k) for k in _REQUEST_KEYS if (request or {}).get(k)}
    return {"request": req, "figures": [], "series": [], "passages": [], "started": [], "boundaries": []}


def cited(shown: Any, fid: str) -> str:
    """The form the analyst copies: the figure as displayed, then the id it is
    shown under. One string, so writing it as shown is writing it pointed."""
    return f"{shown} [{fid}]"


def display(value: Any, unit: str | None) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return dc.display(float(value), unit) if unit else value
        except Exception:  # noqa: BLE001 — a unit display has no business failing a digest
            return value
    return value


def boundary(text: str, *, want: Any = None, subject: str | None = None, cls: str = "boundary",
             code: str | None = None, nearest: list | None = None) -> tuple[dict, F.Fact]:
    """WHAT THE DESK COULD NOT DO, AS A FACT.

    Minted here and recorded by the caller with the step, so the words an
    analyst reads are on the ledger like any other text the turn holds:
    quotable, openable, checkable. Round G refused an analyst for quoting a
    boundary verbatim, because the boundary had been shown and never recorded
    (ACCEPTANCE_V33 §14.3)."""
    measure = want if isinstance(want, str) else (", ".join(str(w) for w in (want or [])) or "request")
    params: dict = {"reason": "cannot", "class": cls}
    if code:
        params["code"] = code
    if want:
        params["want"] = want
    fact = F.fact(F.ABSENCE, measure[:200], subject=subject, text=(text or "the desk could not fulfil this")[:600],
                  as_of="n/a", params=params, standalone=False, group="boundary")
    entry = {"class": cls, "fact": fact.id, "text": fact.text}
    if code:
        entry["code"] = code
    if want:
        entry["want"] = want
    if nearest:
        entry["nearest"] = nearest[:4]
    if subject:
        entry["subject"] = subject
    return entry, fact


class Minter:
    """Collects the boundary facts one analyst's digests mint.

    The facts have to reach the ledger in the caller's step, and passing a list
    around by hand is the kind of bookkeeping that gets dropped in the branch
    nobody tests — which is exactly how a boundary came to be shown and not
    recorded."""

    def __init__(self) -> None:
        self.facts: list[F.Fact] = []

    def __call__(self, text: str, **kw) -> dict:
        entry, fact = boundary(text, **kw)
        self.facts.append(fact)
        return entry

    def take(self) -> list[F.Fact]:
        """The facts minted since the last take; the caller records them."""
        out, self.facts = self.facts, []
        return out


def _call_text(call: dict | None) -> str:
    """The call a boundary answers, as a clause: `read_filings(ticker='MSFT', item='7')`.
    The desk's words for what it could not do have to say what was asked, or
    they are a code and not a sentence — and a sentence is what the lead is
    allowed to quote (V36A: `not_indexed` was the whole text of one boundary)."""
    if not isinstance(call, dict) or not call.get("tool"):
        return ""
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    inner = ", ".join(f"{k}={v!r}" for k, v in args.items() if v is not None and k != "program")
    return f"{call['tool']}({inner[:140]})"


def _problem_text(p: dict) -> str:
    """One problem of a refusal, whichever shape wrote it. The registry's
    argument check writes {field, problem, value}; the program typecheck and
    the answer check write {reason, fix, detail}. Round A rendered sixteen
    read_filings refusals as "invalid_arguments — ; " because this read only the
    second shape, and one analyst sent the same call six times on that."""
    what = p.get("fix") or p.get("detail") or p.get("problem") or p.get("reason") or ""
    field = p.get("field") or p.get("arg") or p.get("at")
    return f"{field}: {what}" if field and what else str(what or field or "")


def absorb(entry: dict, res: dict, subject: str | None = None, mint=None, call: dict | None = None) -> dict:
    """A tool result into an entry: figures, series, passages, tasks and
    boundaries — every one from the result's facts block, so every value the
    analyst reads is on the ledger."""
    if not isinstance(res, dict):
        return entry
    mint = mint or (lambda text, **kw: boundary(text, **kw)[0])
    if res.get("error") and "facts" not in res:
        cls = {"budget_exceeded": "budget", "type_errors": "type", "malformed_program": "type",
               "not_prepared": "data_absent", "company_not_found": "data_absent", "not_listed": "data_absent",
               "not_indexed": "data_absent", "active_run_exists": "data_absent", "not_investigable": "data_absent",
               "not_an_sec_filer": "data_absent"}.get(res["error"], "error")
        text = res.get("detail") or res["error"]
        if res.get("problems"):
            text += " — " + "; ".join(_problem_text(p) for p in res["problems"][:3] if isinstance(p, dict))
        if isinstance(res.get("route"), dict) and res["route"]:
            text += " — " + "; ".join(f"{k}: {ejson.dumps(v)[:120]}" for k, v in list(res["route"].items())[:2])
        # the desk's words name the call they answer, so they read as a sentence
        # and not as a code: "read_filings(ticker='MSFT', item='7'): not_indexed"
        head = _call_text(call)
        entry["boundaries"].append(mint((f"{head}: {text}" if head else str(text)), cls=cls, code=res["error"],
                                        subject=subject))
        return entry
    if res.get("enqueued"):
        entry["started"].append({"kind": res.get("kind"),
                                 "subject": res.get("ticker") or res.get("portfolio_id") or subject,
                                 "task": res.get("task_id") or res.get("run_id")})
    block = res.get("facts") or {}
    cols, rows = block.get("columns") or [], block.get("rows") or []
    for row in rows:
        rec = dict(zip(cols, row))
        params = rec.get("params") or {}
        kind = rec.get("kind")
        if kind == "scalar":
            fig = {"id": rec["id"], "subject": rec.get("subject"), "measure": rec.get("measure"),
                   "value": display(rec.get("value"), rec.get("unit")), "unit": rec.get("unit"),
                   "as_of": rec.get("as_of")}
            if rec.get("window"):
                fig["window"] = rec["window"]
            for k in _FIGURE_PARAMS:
                if params.get(k) is not None:
                    fig[k] = params[k]
            entry["figures"].append(fig)
        elif kind == "series":
            val = rec.get("value") or {}
            pts = val.get("points") if isinstance(val, dict) else None
            s = {"id": rec["id"], "subject": rec.get("subject"), "measure": rec.get("measure"), "unit": rec.get("unit"),
                 "n": (val.get("n") if isinstance(val, dict) else None), "node": params.get("node")}
            if pts:
                s["first"] = [pts[0][0], display(pts[0][1], rec.get("unit"))]
                s["last"] = [pts[-1][0], display(pts[-1][1], rec.get("unit"))]
                if len(pts) <= 12:
                    s["points"] = [[p, display(v, rec.get("unit"))] for p, v in pts]
            entry["series"].append(s)
        elif kind == "passage":
            val = rec.get("value")
            text = val.get("text") if isinstance(val, dict) else (val if isinstance(val, str) else "")
            entry["passages"].append({"id": rec["id"], "subject": rec.get("subject"), "title": rec.get("measure"),
                                      "text": (text or "")[:PASSAGE_CHARS], "chars": len(text or ""),
                                      **{k: v for k, v in params.items()
                                         if k in ("item", "form_type", "accession", "url", "source_url")}})
        elif kind == "absence":
            err = params.get("error") or ((params.get("root") or {}).get("error")
                                          if isinstance(params.get("root"), dict) else None)
            if params.get("reason") in ("not_held", "cannot"):
                cls = "data_absent"
            else:
                cls = "type" if err in claims.SPELLING_REFUSALS else "data_absent"
            # the fact's own sentence ("over_8pct was not computed — no_entry_satisfies:
            # no entry of $issuer_weights is > 8"). A model-facing row carries it
            # as the value (facts.row_for_model); a record-form row, which the
            # forensics rebuild feeds, carries it as `text` — read both, so a
            # rebuilt digest reads as the live one did (V36A §3.4's "" was that).
            entry["boundaries"].append({"class": cls, "fact": rec["id"], "node": params.get("node"), "code": err,
                                        "text": str(rec.get("text") or rec.get("value") or "")[:400]})
        elif kind == "task":
            entry["started"].append({"task": rec["id"], "text": str(rec.get("value") or "")[:200]})
    nodes = res.get("nodes")
    if isinstance(nodes, dict):
        entry["nodes"] = [n for n in nodes if not str(n).startswith("_")]
        # the books this program built, by the id another program — another
        # analyst's — reads where a run goes (V36.1, round A's Q13)
        made = [{"node": n, "id": d["ref"], "kind": "scenario"} for n, d in nodes.items()
                if isinstance(d, dict) and d.get("kind") == "table" and str(d.get("ref") or "").startswith("calc_")
                and not str(n).startswith("_")]
        if made:
            entry["made"] = made
    if res.get("held_back"):
        entry["boundaries"].append({
            **mint(f"{res['held_back'].get('count')} more figures were computed and not shown; "
                   f"request fewer names, or name the ones you need", cls="held_back"),
            "measures": res["held_back"].get("measures", [])[:20]})
    return entry


def _reading_of(fig: dict) -> tuple:
    return (fig.get("subject"), fig.get("measure"), fig.get("as_of"), str(fig.get("value")))


def tell_apart(items: list[dict], seen: dict | None = None) -> None:
    """ONE READING IS SHOWN ONCE. A reading fetched twice collapses to one entry
    naming the other ids: they are the same figure.

    What tells two readings apart is the id each is shown under, which the
    analyst writes after the figure. V34 put a date into the shown value when
    two readings of one subject read alike, and round G showed the collision
    that matters is two SUBJECTS reading alike (nine issuers share a 15.0%
    warning tier): no suffix short of the id itself tells those apart.

    `seen` carried in by the caller makes the collapse span everything one
    analyst has been shown, not one call."""
    seen = {} if seen is None else seen
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


def stamp_ids(items: list[dict]) -> None:
    """Every shown figure ends with the id it is shown under — a scalar's value,
    a series' points (the series' one id on each). After the collapse, so the
    collapse compares readings and not brackets."""
    for e in items:
        for f in e.get("figures") or []:
            f["value"] = cited(f["value"], f["id"])
        for sr in e.get("series") or []:
            # a series has one id; its bracket names the point: `[f_…@2025-12-31]`
            for key in ("first", "last"):
                if isinstance(sr.get(key), list) and len(sr[key]) == 2:
                    sr[key] = [sr[key][0], cited(sr[key][1], f"{sr['id']}@{sr[key][0]}")]
            if sr.get("points"):
                sr["points"] = [[p, cited(v, f"{sr['id']}@{p}")] for p, v in sr["points"]]


def fit(digest: dict, limit: int, mint=None) -> dict:
    """The digest within its cap by holding back the TAIL ROWS of the largest
    figure list, then trimming passage texts — never a whole item."""
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
            text = ("figures computed and on the ledger but not shown here: the request was too wide for one "
                    "digest; ask again for the names you need")
            # a fact, like every other text the analyst reads (round H refused its quotation)
            note = mint(text, cls="held_back") if mint else {"class": "held_back", "text": text}
            note.update({"by": "digest", "count": 0, "measures": []})
            biggest["boundaries"].append(note)
        note["count"] += len(dropped)
        note["measures"] = sorted({f"{f.get('subject')}:{f.get('measure')}" for f in dropped} | set(note["measures"]))[:30]
    guard = 0
    while size() > limit and guard < 50:
        guard += 1
        longest = max((p for e in items for p in (e.get("passages") or [])),
                      key=lambda p: len(p.get("text") or ""), default=None)
        if longest is None or len(longest.get("text") or "") <= 800:
            break
        longest["text"] = longest["text"][: max(800, len(longest["text"]) // 2)]
        longest["shown_chars"] = len(longest["text"])
    return digest


def merge(into: dict, part: dict) -> dict:
    for k in ("figures", "series", "passages", "started", "boundaries"):
        into[k] = list(into.get(k) or []) + list(part.get(k) or [])
    for k in ("program", "nodes"):
        if part.get(k) is not None:
            into[k] = part[k]
    return into


def render(res: dict, *, request: dict | None = None, subject: str | None = None,
           mint=None, seen: dict | None = None, cap: int = DIGEST_CHAR_LIMIT, call: dict | None = None) -> dict:
    """One tool result, as the analyst reads it: absorbed, collapsed, stamped
    and fitted. The one entry point a sub-analyst needs. `call` is the tool and
    arguments the result answers, so a boundary can say what was asked."""
    entry = absorb(empty(request), res, subject=subject, mint=mint, call=call)
    items = [entry]
    tell_apart(items, seen)
    stamp_ids(items)
    fit({"items": items}, cap, mint=mint)
    return {**entry, "how_to_cite": HOW_TO_CITE}
