"""Score the blind readers' plans: every call they wrote, checked against the desk's real schemas and
shape rules (validate_plans.check_call), beside the reference path's verbs. Prints one block a question
and writes blind_scored.json next to this file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from reference_paths import PATHS
from validate_plans import check_call

HERE = Path(__file__).parent


def load(journal: Path) -> list[dict]:
    plans = []
    for line in journal.read_text().splitlines():
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        if j.get("type") == "result" and isinstance(j.get("result"), dict):
            for p in j["result"].get("plans") or []:
                plans.append({**p, "_only_given_files": j["result"].get("read_only_the_given_files")})
    return plans


def main(journal: str) -> None:
    questions = {q["qid"]: q["question"] for q in json.loads((HERE / "questions.json").read_text())}
    plans = sorted(load(Path(journal)), key=lambda p: p["qid"])
    scored, calls, accepted = [], 0, 0
    for p in plans:
        qid = p["qid"]
        rows = []
        for s in p["steps"]:
            try:
                args = json.loads(s["args_json"])
                problems = check_call(s["tool"], args)
            except json.JSONDecodeError as exc:
                args, problems = s["args_json"], [f"args are not JSON: {exc}"]
            rows.append({"tool": s["tool"], "args": args, "problems": problems, "certainty": s.get("certainty"),
                         "repeat": s.get("repeat") or "", "depends_on": s.get("depends_on") or "",
                         "purpose": s.get("purpose"), "basis": s.get("basis")})
            calls += 1
            accepted += int(not problems)
        ref = " → ".join(s["tool"] + (f"×{s['n']}" if s.get("n") else "") for s in PATHS.get(qid, []))
        scored.append({"qid": qid, "question": questions.get(qid), "reading": p.get("reading"), "steps": rows,
                       "reference": ref, "answer_shape": p.get("answer_shape"), "cannot": p.get("cannot") or "",
                       "unclear": p.get("unclear") or [], "only_given_files": p.get("_only_given_files")})
        print(f"\n━━ {qid}  {questions.get(qid)}")
        print(f"   reading: {p.get('reading')}")
        print(f"   reference: {ref}")
        for i, r in enumerate(rows, 1):
            mark = "ok " if not r["problems"] else "REFUSED"
            print(f"   {i}. [{mark}] ({r['certainty']}) {r['tool']} {json.dumps(r['args'], ensure_ascii=False)[:260]}"
                  + (f"   ×{r['repeat']}" if r["repeat"] else ""))
            for prob in r["problems"]:
                print(f"         ✗ {prob}")
        if p.get("cannot"):
            print(f"   cannot: {p['cannot'][:500]}")
        for u in p.get("unclear") or []:
            print(f"   ? {u[:400]}")
        print(f"   answer: {(p.get('answer_shape') or '')[:400]}")
    print(f"\n{len(plans)} plan(s), {calls} call(s) written, {accepted} accepted by schema + shape rules, "
          f"{calls - accepted} refused; all readers kept to the given files: "
          f"{all(p.get('_only_given_files') for p in plans)}")
    (HERE / "blind_scored.json").write_text(json.dumps(scored, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
