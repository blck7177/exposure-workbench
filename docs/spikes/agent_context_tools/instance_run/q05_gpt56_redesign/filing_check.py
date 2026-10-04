"""Every figure of the Q05 answer and note, checked by hand against Apple's filing text in exposure_dev. Read-only.

The dollar figures are written in billions with three decimals; the filing tables are in millions. Each is looked
up as the filing writes it (142.263 billion -> "142,263") in the 10-Q / 10-K sections the desk holds. The growth
rates are looked up in the 10-Q MD&A table row of their own line. Then the shares the answer did not state, and
the revenue totals the desk does hold as figures.

    .venv/bin/python <this dir>/filing_check.py > filing_check.txt
"""
import asyncio, os, re, sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
os.chdir(ROOT)
load_dotenv(".env", override=True)
from sqlalchemy import text                                                    # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine                         # noqa: E402

URL = os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/exposure_dev")
SIX_MONTHS = {"iPhone": "142,263", "Services": "60,989", "Wearables, Home and Accessories": "19,394", "Mac": "16,785",
              "iPad": "15,509", "Total net sales": "254,940", "Americas": "103,622", "Europe": "66,201",
              "Greater China": "46,023", "Rest of Asia Pacific": "21,280", "Japan": "17,814"}
FY2025 = {"iPhone": "209,586", "Total net sales": "416,161", "Americas": "178,353", "Europe": "111,032",
          "Greater China": "64,377", "Rest of Asia Pacific": "33,696", "Japan": "28,703"}
GROWTH = {"iPhone": "23", "Services": "15", "iPad": "7", "Wearables, Home and Accessories": "1", "Mac": "(1)",
          "Americas": "11", "Europe": "14", "Greater China": "33", "Rest of Asia Pacific": "21", "Japan": "9"}


async def main():
    engine = create_async_engine(URL)
    async with engine.connect() as c:
        rows = (await c.execute(text(
            "select f.form_type, f.accession_number, f.period_end, s.item_code, s.text from filing_sections s "
            "join filings f on f.id = s.filing_id where f.company_id = 'co_aapl'"))).all()
        revenue = (await c.execute(text(
            "select period_start, period_end, value from financial_facts where company_id = 'co_aapl' "
            "and normalized_metric = 'revenue' and period_end in ('2025-09-27', '2026-03-28', '2025-12-27') "
            "order by period_end, period_start"))).all()
    await engine.dispose()
    secs = {f"{r.form_type} {r.item_code} ({r.accession_number}, period {r.period_end})": r.text for r in rows}
    mdna = next(t for k, t in secs.items() if k.startswith("10-Q Part I, Item 2"))

    def where(v):
        return [k.split(" (")[0] for k, t in secs.items() if v in t] or ["NOT FOUND"]

    print("DOLLAR FIGURES (answer in $ billions, filing in $ millions)")
    for period, figs in (("six months to 2026-03-28, 10-Q", SIX_MONTHS), ("FY2025, 10-K", FY2025)):
        for line, v in figs.items():
            print(f"   {period:32} {line:32} {v:>8}  in {', '.join(where(v))}")
    print("\nGROWTH RATES (six months, the 10-Q MD&A table: three months, three months prior, change, six months, "
          "six months prior, change)")
    for line, g in GROWTH.items():
        m = re.search(re.escape(line) + r"\$?([\d,]+)\xa0\$?([\d,]+)\xa0(\(?\d+\)?)\xa0?%\$?([\d,]+)\xa0\$?([\d,]+)\xa0(\(?\d+\)?)\xa0?%", mdna)
        got = m.group(6) if m else None
        print(f"   {line:32} said {g:>4}%   filing row: {m.group(0)[len(line):]!r}   six-month change {got}% "
              f"{'OK' if got == g else 'DIFFERS'}" if m else f"   {line:32} row not found")
    print("\nSHARES OF SIX-MONTH NET SALES THE ANSWER DID NOT STATE")
    total = 254940
    for group in (("iPhone", "Services", "Wearables, Home and Accessories", "Mac", "iPad"),
                  ("Americas", "Europe", "Greater China", "Rest of Asia Pacific", "Japan")):
        vals = {k: int(SIX_MONTHS[k].replace(",", "")) for k in group}
        assert sum(vals.values()) == total
        print("   " + ", ".join(f"{k} {100 * v / total:.1f}%" for k, v in vals.items()))
    print(f"   FY2025 iPhone share: {100 * 209586 / 416161:.1f}%")
    print("\nREVENUE THE DESK HOLDS AS FIGURES (financial_facts, normalized_metric = revenue)")
    for r in revenue:
        print(f"   {r.period_start} .. {r.period_end}: {float(r.value) / 1e6:,.0f} million")
    print("   no AAPL fact carries dimensions, so no product or geographic split is held as a figure")


asyncio.run(main())
