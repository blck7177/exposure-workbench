#!/usr/bin/env python3
"""V21-S5 — run the prose critic over stored answers and report what it found.

The gate proves every figure's provenance; it does not read the words beside
the figure (services/prose_critic.py says why, and why the critic stays
outside). This is the critic's offline seat: it reads answers the desk has
already given — a battery's traces file (scripts/agent_battery.py output) or
a session's messages from the database — and reports, per slot in prose,
whether the sentence calls the figure what the desk name says it is.

    # a battery's traces (each entry's meta.blocks, as agent_battery stores them)
    python scripts/critic.py docs/spikes/V15_TRACES.json --out critic.json

    # a live session's answers, from the database
    python scripts/critic.py --session sess_abc123 --out critic.json

    # how many model calls it would make, and no calls
    python scripts/critic.py traces.json --estimate

Costs one completion per paragraph that carries a slot. Findings are
measurements: the summary prints the three counts, and every disagreement
with its sentence, the desk name and what the prose called it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=False)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.services import prose_critic as pc   # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


def _answers_from_traces(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    out = []
    for i, entry in enumerate(data if isinstance(data, list) else data.get("traces", [])):
        blocks = (entry.get("meta") or {}).get("blocks")
        if blocks:
            out.append({"id": entry.get("tag") or entry.get("session_id") or str(i),
                        "question": entry.get("question"), "blocks": blocks})
    return out


async def _answers_from_session(session_id: str) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.db.models import AgentMessage

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    out = []
    async with mk() as db:
        rows = (await db.execute(
            select(AgentMessage).where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at)
        )).scalars().all()
        question = None
        for m in rows:
            if m.role == "user":
                question = m.content
                continue
            blocks = (m.meta or {}).get("blocks")
            if blocks:
                out.append({"id": m.id, "question": question, "blocks": blocks})
    await engine.dispose()
    return out


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="?", help="an agent_battery traces JSON")
    ap.add_argument("--session", action="append", default=[], help="a session id (repeatable)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--estimate", action="store_true", help="count the model calls; make none")
    args = ap.parse_args(argv)
    if not args.traces and not args.session:
        ap.error("give a traces file or --session")

    answers: list[dict] = []
    if args.traces:
        answers += _answers_from_traces(args.traces)
    for sid in args.session:
        answers += await _answers_from_session(sid)

    paragraphs = sum(len(pc.paragraphs(a["blocks"])) for a in answers)
    slots = sum(len(p.slots) for a in answers for p in pc.paragraphs(a["blocks"]))
    print(f"{len(answers)} answer(s), {paragraphs} paragraph(s) with slots, {slots} slot(s) in prose")
    if args.estimate:
        print(f"would make {paragraphs} completion(s)")
        return 0

    from exposure_workbench.llm.client import chat_complete

    report = []
    for a in answers:
        findings = await pc.critique(a["blocks"], chat=chat_complete, model=args.model)
        report.append({"id": a["id"], "question": a["question"],
                       "findings": [f.as_dict() for f in findings]})
        for f in findings:
            if f.verdict == "disagrees":
                print(f"  ✗ {a['id']}: ⟦{f.k}⟧ {f.shown} is `{f.name}`; the prose says "
                      f"\"{f.prose_says}\" — {f.sentence}")

    all_findings = [pc.Finding(**f) for r in report for f in r["findings"]]
    s = pc.summary(all_findings)
    print(f"\nslots in prose {s['slots_in_prose']}: agrees {s['agrees']}, "
          f"disagrees {s['disagrees']}, unclear {s['unclear']}")
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": {k: v for k, v in s.items() if k != 'disagreements'},
                                              "answers": report}, indent=2, ensure_ascii=False))
        print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
