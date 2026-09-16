#!/usr/bin/env python3
"""V38/S4 acceptance: round C's briefs refused "measure_mismatch 'net beta'",
re-checked with the facts' identities as the V38 naming rule gives them.

`pick(key='portfolio.integration.net_beta.equity_down')` minted a fact whose
measure was `portfolio.integration.net_beta` and whose subject was `equity_down`;
the handoff check's phrase table then held "net beta" as a measure of its own.
Each such brief is re-checked twice against the ledger it was checked against:
as recorded (must reproduce the recorded problems) and with those facts'
identities rewritten by resources.identity_of.

    python recheck_net_beta.py <db> <round.json> <tag>
"""
import asyncio, json, re, sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
from exposure_workbench.agents import delegation as dl
from exposure_workbench.analytics import resources
from exposure_workbench.services import ledger as ledger_svc

_SPLIT_HEADS = ("portfolio.integration.", "portfolio.")


def rewrite(rec: dict) -> dict:
    """The identity V38 gives a fact the old `_parse_book_name` split."""
    m, s = str(rec.get("measure") or ""), rec.get("subject")
    if not m.startswith("portfolio.") or not isinstance(s, str) or ":" in s or s.startswith(("run_", "calc_", "port_")):
        return rec
    parts = m.split(".")
    if m.startswith("portfolio.integration.") and len(parts) == 3:
        label = f"{m}.{s}"                                   # portfolio.integration.net_beta + equity_down
    elif len(parts) == 2:
        label = f"portfolio.{s}.{parts[1]}"                  # portfolio.X + reconcile
    else:
        return rec
    measure, entity = resources.identity_of(label)
    base = next((x for x in rec.get("sources") or [] if isinstance(x, str) and x.startswith(("run_", "calc_"))), None)
    return {**rec, "measure": measure, "subject": entity or base}


def ledger_before(steps, seq, fix: bool):
    led = ledger_svc.Ledger()
    for st in steps:
        if st["seq"] >= seq or st["status"] != "completed":
            continue
        refs = st["evidence_refs"]
        refs = json.loads(refs) if isinstance(refs, str) else refs
        for rec in ledger_svc.facts_in(refs or []):
            led.add(rewrite(rec) if fix else rec)
    return led


def task_for(steps, seq, domain):
    for st in reversed([s for s in steps if s["seq"] < seq and s["step_type"] == "delegate" and s["status"] == "completed"]):
        for t in (vf._j(st["args"]) or {}).get("tasks") or []:
            if t.get("domain") == domain:
                c = t.get("constraints") or {}
                return dl.Task(task_id=t.get("task_id") or "tsk", domain=domain, subjects=tuple(t.get("subjects") or ()),
                               want_to_know=tuple(re.sub(r"^\d+\.\s*", "", w) for w in t.get("want_to_know") or ()),
                               window=c.get("window"), compare=c.get("compare"), context=t.get("context"))
    return None


def net_beta(problems):
    return sum(1 for p in problems if p.get("reason") == "measure_mismatch" and "net beta" in json.dumps(p))


async def main():
    db, rj, tag = sys.argv[1:4]
    eng = create_async_engine(vf._url(db))
    rec_total = replay_total = fixed_total = 0
    try:
        for conv in json.load(open(rj)):
            steps = await vf._steps(eng, conv["session_id"])
            for st in steps:
                a = vf._j(st["args"]) or {}
                if st["step_type"] != "brief" or net_beta(a.get("problems") or []) == 0:
                    continue
                task = task_for(steps, st["seq"], (st["actor"] or "")[4:])
                brief, report = a.get("brief") or {}, a.get("report") or {}
                recorded = net_beta(a.get("problems") or [])
                again = net_beta(dl.handoff_check(task, brief, report, ledger_before(steps, st["seq"], False)).problems)
                fixed_v = dl.handoff_check(task, brief, report, ledger_before(steps, st["seq"], True))
                fixed = net_beta(fixed_v.problems)
                rec_total, replay_total, fixed_total = rec_total + recorded, replay_total + again, fixed_total + fixed
                print(f"{tag} {conv['tag'][:3]} seq{st['seq']} {st['actor']}: recorded {recorded} (problems list capped at 20), "
                      f"re-checked {again}, with V38 identities {fixed}; other problems now "
                      f"{sorted({p.get('reason') for p in fixed_v.problems})}")
    finally:
        await eng.dispose()
    print(f"{tag}: briefs — net-beta measure_mismatch recorded {rec_total}, re-checked as recorded {replay_total}, "
          f"with V38 identities {fixed_total}")
    # the lead's answers go through the same phrase table
    from exposure_workbench.services import answer_check
    eng = create_async_engine(vf._url(db))
    before = after = 0
    try:
        for conv in json.load(open(rj)):
            steps = await vf._steps(eng, conv["session_id"])
            question = conv["turns"][0].get("q") if conv.get("turns") else None
            for st in steps:
                if st["step_type"] != "answer":
                    continue
                text = (vf._j(st["args"]) or {}).get("text") or ""
                b = net_beta(answer_check.check(text, ledger_before(steps, st["seq"], False), question=question).problems)
                f = net_beta(answer_check.check(text, ledger_before(steps, st["seq"], True), question=question).problems)
                before, after = before + b, after + f
                if b or f:
                    print(f"  {tag} {conv['tag'][:3]} answer seq{st['seq']}: {b} -> {f}")
    finally:
        await eng.dispose()
    print(f"{tag}: answers — net-beta measure_mismatch re-checked {before}, with V38 identities {after}")


asyncio.run(main())
