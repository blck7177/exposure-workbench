"""Re-run the answer gate (services/fact_boundary.check_text, the function the lead's reply went through) on
the recorded draft and on two variants, against this turn's ledger rebuilt from the exported steps
(battery_out.json: every fact of every completed step). Offline: no database, no provider, nothing written.

  A  the recorded first draft, as sent                      -> must reproduce the recorded refusal
  B  A with the pointer the refusal named after '+0.5'      -> what the gate says to following its own hint
  C  the recorded accepted repair                           -> must reproduce the recorded acceptance
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/ubuntu/exposure-workbench")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "src"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env", override=True)

from exposure_workbench.services import fact_boundary  # noqa: E402
from exposure_workbench.services.ledger import Ledger, facts_in  # noqa: E402

turn = json.loads((HERE / "battery_out.json").read_text())[0]["turns"][0]
steps = turn["steps"]
recs = []
for s in steps:
    if s["status"] == "completed":
        refs = s["evidence_refs"]
        recs += facts_in(json.loads(refs) if isinstance(refs, str) else refs)
ledger = Ledger.of(recs)
answers = [s for s in steps if s["step_type"] == "answer"]
draft = json.loads(answers[0]["args"])["text"]
repaired = json.loads(answers[1]["args"])["text"]
hinted = draft.replace("a +0.5 percentage point move", "a +0.5 [f_26fd824a1dcb] percentage point move")
assert hinted != draft

for tag, text in (("A recorded draft", draft), ("B draft + the hinted pointer", hinted), ("C recorded repair", repaired)):
    v = fact_boundary.check_text("answer", text, ledger, question=turn["q"])
    print(f"=== {tag}: ok={v.ok}")
    for p in getattr(v, "problems", []) or []:
        print("   ", p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, default=str)[:400])
    if not getattr(v, "problems", None):
        print("   ", str(v)[:600])
