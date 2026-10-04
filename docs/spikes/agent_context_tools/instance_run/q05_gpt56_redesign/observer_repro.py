"""Read-only reproduction of what the observer did with the Q05 drafts. Changes nothing.

Feeds the specialist's note and the lead's answer, exactly as recorded, back through the same observer with the
same 70 ledger passages the run had (loaded from exposure_dev), and prints:
  1. how the answer tokenizer reads the dollar figures, and what the observer's parser makes of them;
  2. the verdicts again, so they can be compared with the recorded ones;
  3. for every percentage the note's verdict called supported by a passage, the passage text it matched;
  4. the same six-month table row as the model read it and as the ledger keeps it.

    .venv/bin/python <this dir>/observer_repro.py > observer_repro.txt
"""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
os.chdir(ROOT)
load_dotenv(".env", override=True)
sys.path.insert(0, str(ROOT / "src"))
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine   # noqa: E402
from exposure_workbench.auth.context import current_user_ctx                  # noqa: E402
from exposure_workbench.services import ledger as ledger_svc                  # noqa: E402
from exposure_workbench.services import observer as ob                        # noqa: E402

OWNER = "user_3IDBMeAxLTbecvGorzwV7FCeroR"
URL = os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/exposure_dev")


async def main():
    run = json.load(open(HERE / "battery_out.json"))[0]
    turn = run["turns"][0]
    steps = {s["seq"]: s for s in turn["steps"]}
    lead_final = json.loads(steps[20]["args"])["request"]
    state = lead_final["tail"][0]["content"][0]["text"]
    note_rec = json.loads(state.split("\n", 1)[1].rsplit("\n</state>", 1)[0])["notes"][0]
    note, answer = note_rec["text"], turn["answer"]
    current_user_ctx.set(OWNER)
    engine = create_async_engine(URL)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        led = await ledger_svc.load(db, run["session_id"])
    await engine.dispose()
    P = led.passages
    print(f"ledger passages for {run['session_id']}: {len(P)}\n")

    print("1. TOKENIZER vs PARSER on the dollar figures")
    for name, text in (("specialist note", note), ("lead answer", answer)):
        toks = ob.A.tokens_in(text)
        money = [t for t in toks if t["kind"] == "num" and "$" in t["token"]]
        unparsed = [t["token"] for t in money if ob._parse(t["token"]) is None]
        print(f"   {name}: {len(money)} dollar tokens, {len(unparsed)} that the parser returns None for "
              f"(observer.py: `if parsed is None: continue`)")
        print(f"      e.g. tokens_in -> {money[0]['token']!r} (kind {money[0]['kind']}); _parse -> {ob._parse(money[0]['token'])}")

    print("\n2. VERDICTS, re-run with the run's passages")
    print(f"   recorded for the note : {note_rec['verification']}")
    print(f"   re-run on the note    : {ob.observe(note, question=turn['q'], views=[], passages=P).summary()}")
    print(f"   recorded for answer   : {turn['meta']['verified']}")
    print(f"   re-run on the answer  : {ob.observe(answer, question=turn['q'], views=[], passages=P).summary()}")

    print("\n3. WHAT EACH 'SUPPORTED BY A PASSAGE' PERCENTAGE MATCHED (substring search over all passages)")
    v = ob.observe(note, question=turn["q"], views=[], passages=P)
    for p in v.propositions:
        if p.status not in (ob.PASSAGE, ob.UNSUPPORTED):
            continue
        said = note[max(0, p.start - 45):p.end + 3].replace("\n", " ")
        print(f"\n   {p.token!r:7} -> {p.status}{' ' + p.detail if p.detail else ''}")
        print(f"      the note : ...{said}")
        if p.detail in P:
            txt = P[p.detail]
            i = txt.find(p.token.lstrip("+-−$"))
            print(f"      matched  : ...{txt[max(0, i - 75):i + 15]!r}")

    print("\n4. ONE TABLE ROW, AS THE MODEL READ IT AND AS THE LEDGER KEEPS IT")
    seen = json.loads(steps[19]["args"])["request"]["items_appended"]
    shown = False
    for item in seen:
        for row in json.loads(item["output"]).get("rows") or []:
            i = row.find("Greater China20,497")
            if i >= 0 and not shown:
                print(f"   model read  : {row[i:i + 64]!r}")
                shown = True
    for pid, txt in P.items():
        i = (txt or "").find("Greater China20497")
        if i >= 0:
            print(f"   ledger keeps: {txt[i:i + 62]!r}   ({pid})")
            break
    print("   the true source of the note's 'Greater China 33%' is the row above: '33\\xa0%' in the ledger, so the "
          "substring '33%' is not found and the figure was called unsourced")


asyncio.run(main())
