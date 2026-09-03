"""V3-D2 — faithfulness of what this system has already said (run it directly).

Three metrics, all deterministic. No LLM judge: rules-based verification is the
stronger instrument wherever it reaches, and reaching for a judge before the
deterministic checks are exhausted would mean grading our own homework with a
second, less reliable copy of the thing being graded.

  1. citation resolution — every cited id resolves. The gate already guarantees
     this at write time; here it is checked at READ time, which is different:
     evidence is append-only, but a citation that stopped resolving would mean
     that promise had been broken somewhere.
  2. numeric verification — every stated number matches a value the evidence
     cited FOR IT actually holds. This is A1's verify(), reused rather than
     reimplemented, so the eval cannot drift from the gate.

     V15-S0: a BLOCK answer (V14-C) is measured as a block answer. Its figures
     were never written into prose — they are slots the gate resolved against
     the rows they name — and the stored `content` is those rows' values put
     back for readers with no renderer. Re-extracting numbers from that string
     measures the RENDERER, not the model: it shredded `1.08663e+07` into a
     mantissa and a bare `07`, and refused weights that were EQUAL to the row
     they came from because the written precision had changed. 27 of one
     message's figures were counted as refusals that way, and the ceiling was
     raised to hold them. So a v2 message is checked on its slots — does the
     ref still resolve, does the row still hold that value — and on its text
     runs, which must carry no figures at all. Both are real read-time checks;
     neither judges the model for the renderer's spelling.
  3. number-bearing answers with no citations at all — must be zero after A0-1.

It replays the corpus already in the database rather than generating fresh
answers. That is the point, not a shortcut: an answer produced after A1 has by
construction already passed A1, so it can only ever score 100% and measures
nothing. The pre-A1 text is the only sample that can say what the new rules
actually refuse — which is the evidence 拍板点 1 (full-strict numeric matching)
gets re-argued on.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env", override=True)

from exposure_workbench.analytics import withheld as wh  # noqa: E402
from exposure_workbench.db.models import AgentMessage, ExposureMetrics, IssuerBrief, StressResult  # noqa: E402
from exposure_workbench.services import answer_blocks as ab  # noqa: E402
from exposure_workbench.services import numeric_verification as nv  # noqa: E402
from exposure_workbench.services import quantities as qn  # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
# open_questions is measured too, against the union of the brief's citations —
# the same rule submit_brief enforces (V3-R5), and the honest one for a block
# that carries no citations of its own. Leaving it out of the metric was how the
# gap stayed invisible: the eval and the gate agreed, and both were looking away.
BLOCKS = ("financial_summary", "key_changes", "management_explanation",
          "market_context", "portfolio_implications", "open_questions")


# An id token in a text run. V14-C answers wrote "Evidence ids: run_… / alert_…"
# into runs because a passage- or run-backed claim had no block of its own;
# V15-S3 gives every claim a shape and the exit refuses digits in text, so this
# is a class the corpus carries and nothing written after S3 can add to. It is
# counted under its own key, not as an unverified figure: no magnitude was
# stated, so there is nothing for the evidence to fail to support.
_ID_TOKEN = re.compile(r"\b(?:fact|chunk|calc|src|co|rrun|run|filing|alert|brief|msg|sess|task|pack|"
                       r"step|port|pos|report)_[A-Za-z0-9_]{3,}")


def _only_ids(text: str) -> bool:
    """Every flagged digit run sits inside an id token: with the tokens taken
    out, the exit's own rule finds nothing."""
    return bool(_ID_TOKEN.search(text)) and not ab.figures_in_text(_ID_TOKEN.sub(" ", text))


async def _check_blocks(db, blocks) -> tuple[int, list[dict], list[dict]]:
    """A block answer, checked as one: slots against their rows, text against
    the rule that it carries no figures.

    A slot is stored already resolved — {ref, label, value, unit_class} — so the
    read-time question is whether the row it names still holds that value. That
    is the same promise citation resolution makes one level up, and it is the
    only thing about a slot that can decay: the model never wrote the figure, so
    there is nothing here it could have written wrongly.

    Text runs are held to the exit's own rule (answer_blocks.figures_in_text):
    no digits but the closed non-measurement classes. The prose extractor is
    not used here — it reads magnitudes out of sentences, which is the v1
    instrument, and a block answer has no magnitudes in its text by construction.

    Returns (slots, problems, ids_in_text): the third is the V14-C class above,
    reported beside the metrics rather than inside `unverified`.
    """
    slots: list[dict] = []
    text_problems: list[dict] = []
    ids_in_text: list[dict] = []
    for i, b in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(b, dict):
            continue
        runs = list(b.get("runs") or [])
        for row in b.get("rows") or []:
            runs.extend(row if isinstance(row, list) else [])
        for j, r in enumerate(runs):
            if isinstance(r, dict) and isinstance(r.get("slot"), dict):
                slots.append(r["slot"])
            elif isinstance(r, str):
                figures = ab.figures_in_text(r)
                if figures and _only_ids(r):
                    ids_in_text.append({
                        "reason": "id_written_as_text", "at": f"blocks[{i}].runs[{j}]",
                        "ids": _ID_TOKEN.findall(r)})
                elif figures:
                    text_problems.append({
                        "reason": "figure_written_as_text", "at": f"blocks[{i}].runs[{j}]",
                        "numbers": figures, "text": r[:120]})

    refs = sorted({s["ref"] for s in slots if isinstance(s.get("ref"), str)})
    values, _quoted = await nv.resolve_cited_values(db, refs) if refs else ([], set())
    by_ref: dict[str, list] = {}
    for v in values:
        by_ref.setdefault(v.source_id, []).append(v)

    problems = list(text_problems)
    for s in slots:
        ref, want = s.get("ref"), s.get("value")
        if not isinstance(want, (int, float)):
            continue
        holds = by_ref.get(ref, [])
        atol = 0.5 * (10 ** -_decimals_of(float(want)))
        if not any(abs(v.value - float(want)) <= atol for v in holds):
            # V20. A slot on a measure the desk has since withheld was right
            # when written and is not on the table now: its own class, so the
            # replay says "withheld", not "no longer held".
            label = s.get("label")
            problems.append({
                "reason": ("withheld" if isinstance(label, str) and wh.is_withheld_name(label)
                           else "slot_no_longer_held" if holds else "slot_ref_holds_nothing"),
                "ref": ref, "label": label, "number": want})
    return len(slots), problems, ids_in_text


async def _withheld_values(db, refs: list[str]) -> list[float]:
    """The numbers a withheld measure held for the cited runs — read from the
    stored rows, which withholding did not touch — so a prose answer written
    before V20 that quoted a VaR or a stress loss is classified as `withheld`
    rather than as unverified (V20)."""
    runs = [r for r in refs if r.startswith("run_")]
    if not runs:
        return []
    out: list[float] = []
    for m in (await db.execute(select(ExposureMetrics).where(ExposureMetrics.run_id.in_(runs)))).scalars():
        for col in wh.WITHHELD_METRICS:
            v = getattr(m, col, None)
            if v is not None:
                out.append(float(v))
    if "stress_results" in wh.WITHHELD_TABLES:
        rows = list((await db.execute(select(StressResult).where(StressResult.run_id.in_(runs)))).scalars())
        for r in rows:
            for v in (r.loss_pct, r.loss_usd):
                if v is not None:
                    out.append(float(v))
        by_run: dict[str, int] = {}
        for r in rows:
            by_run[r.run_id] = by_run.get(r.run_id, 0) + 1
        out.extend(float(n) for n in by_run.values())
    # The counts an old answer stated over ALL alerts or checks of a run: the
    # published count is smaller now by the withheld checks' rows.
    from exposure_workbench.db.models import LimitCheck, RiskAlert
    for model in (RiskAlert, LimitCheck):
        rows = list((await db.execute(select(model).where(model.run_id.in_(runs)))).scalars())
        by_run = {}
        for r in rows:
            by_run[r.run_id] = by_run.get(r.run_id, 0) + 1
        out.extend(float(n) for n in by_run.values())
    return out


def _decimals_of(x: float) -> int:
    """Decimal places the stored value carries. A V15 slot stores the row's own
    value, so this is exact; a V14-C slot stored the value at the precision the
    model wrote it, and half an ulp of that is the honest read-time tolerance."""
    s = repr(float(x))
    if "e" in s or "E" in s:
        return 12
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


async def _resolves(db, ids) -> tuple[int, list[str]]:
    """A citation resolves when the namer can place it on a row (V15: the one
    existence check is `quantities.of_ref`, whose kind is None for nothing)."""
    dangling = [i for i in ids if (await qn.of_ref(db, i)).kind is None]
    return len(ids), dangling


async def evaluate() -> dict:
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {"chat": {}, "briefs": {}, "refusals": []}
    try:
        async with mk() as db:
            # ── chat ────────────────────────────────────────────────────────
            msgs = (await db.execute(
                select(AgentMessage).where(AgentMessage.role == "assistant")
            )).scalars().all()
            numbers = bad = cited = dangling_total = uncited_with_numbers = 0
            withheld_total = 0
            v2_messages = v2_slots = 0
            id_text_runs, id_text_messages = 0, set()
            for m in msgs:
                blocks = (m.meta or {}).get("blocks") if isinstance(m.meta, dict) else None
                if blocks:
                    v2_messages += 1
                    n_slots, problems, ids_in_text = await _check_blocks(db, blocks)
                    v2_slots += n_slots
                    numbers += n_slots
                    # V20: a withheld slot is its own class, not an unverified one.
                    withheld_here = sum(1 for p in problems if p.get("reason") == "withheld")
                    withheld_total += withheld_here
                    bad += len(problems) - withheld_here
                    for p in problems:
                        out["refusals"].append({"where": m.id, **p})
                    for p in ids_in_text:
                        id_text_runs += 1
                        id_text_messages.add(m.id)
                        out["refusals"].append({"where": m.id, **p})
                    ids = list(m.citations or [])
                    n, dangling = await _resolves(db, ids)
                    cited += n
                    dangling_total += len(dangling)
                    continue
                stated = nv.extract_numbers(m.content or "")
                ids = list(m.citations or [])
                if stated and not ids:
                    uncited_with_numbers += 1
                    out["refusals"].append({"where": m.id, "reason": "numbers_without_citations",
                                            "numbers": nv.raw_forms(stated)})
                    continue
                n, dangling = await _resolves(db, ids)
                cited += n
                dangling_total += len(dangling)
                if not stated:
                    continue
                values, quoted = await nv.resolve_cited_values(db, ids)
                problems = nv.verify(stated, values, quoted)
                numbers += len(stated)
                # V20. A refused number that equals a withheld measure of a
                # cited run is `withheld`, counted apart from `unverified`.
                held_back = await _withheld_values(db, ids)
                by_surface = {n.surface: n for n in stated}
                for p in problems:
                    n = by_surface.get(p.get("number"))
                    # `reason` after **p: the verifier's own reason is kept as
                    # `verifier_reason`, and the replay's class is the one read.
                    if n is not None and any(abs(v - n.value) <= n.atol for v in held_back):
                        withheld_total += 1
                        out["refusals"].append({"where": m.id, **p, "verifier_reason": p.get("reason"),
                                                "reason": "withheld"})
                    else:
                        bad += 1
                        # As before V20: the verifier's own reason is the class read.
                        out["refusals"].append({"where": m.id, "reason": "unverified_number", **p})
            out["chat"] = {"messages": len(msgs), "numbers": numbers, "unverified": bad,
                           "withheld": withheld_total,
                           "citations": cited, "dangling_citations": dangling_total,
                           "number_bearing_uncited": uncited_with_numbers,
                           "block_messages": v2_messages, "block_slots": v2_slots,
                           "id_in_text_runs": id_text_runs,
                           "id_in_text_messages": len(id_text_messages)}

            # ── briefs (per block, against that block's own citations) ──────
            briefs = (await db.execute(select(IssuerBrief))).scalars().all()
            b_numbers = b_bad = b_cited = b_dangling = 0
            for b in briefs:
                per_block = b.block_citations or {}
                for name in BLOCKS:
                    text = getattr(b, name) or ""
                    stated = nv.extract_numbers(text)
                    if not stated:
                        continue
                    # Briefs written before V3 kept only a flat list; measuring
                    # them against it is the honest reading of what they carry.
                    # open_questions has no list of its own by design and is
                    # measured against the union, which is the flat list.
                    ids = (list(b.citations or []) if name == "open_questions"
                           else per_block.get(name) or list(b.citations or []))
                    n, dangling = await _resolves(db, ids)
                    b_cited += n
                    b_dangling += len(dangling)
                    values, quoted = await nv.resolve_cited_values(db, ids)
                    problems = nv.verify(stated, values, quoted)
                    b_numbers += len(stated)
                    b_bad += len(problems)
                    for p in problems:
                        out["refusals"].append({"where": f"{b.id}:{name}",
                                                "reason": "unverified_number", **p})
            out["briefs"] = {"briefs": len(briefs), "numbers": b_numbers, "unverified": b_bad,
                             "citations": b_cited, "dangling_citations": b_dangling,
                             "with_block_citations": sum(1 for b in briefs if b.block_citations)}
    finally:
        await engine.dispose()
    return out


def main() -> None:
    r = asyncio.run(evaluate())
    print(json.dumps({k: v for k, v in r.items() if k != "refusals"}, indent=2))
    print(f"\n{len(r['refusals'])} refusals:")
    for x in r["refusals"][:40]:
        near = x.get("nearest")
        near_s = f" nearest={near['value']:.6g} ({near['label']})" if near else ""
        print(f"  {x['where']:38s} {x['reason']:24s} {x.get('number', '')}{near_s}")


if __name__ == "__main__":
    main()
