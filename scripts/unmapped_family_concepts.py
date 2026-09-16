#!/usr/bin/env python3
"""Debt-like balance tags this desk holds and does not read (V38/S3 instrument).

XOM files all its term debt under `LongTermDebtAndCapitalLeaseObligations`, which
no metric claimed, so its "total debt" was its current debt alone for as long as
anyone looked — and nothing said so, because an unmapped tag is stored with
normalized_metric NULL and is otherwise invisible. This lists them: consolidated
instants whose raw concept looks like debt and that the CURRENT mapping
(concept_mapping.normalize_concept) does not name, per issuer, with their last
date and largest value. `KNOWN` holds the ones already looked at, with why; the
live test (tests/test_v38_unmapped_debt_live.py) goes red on any other.

    python scripts/unmapped_family_concepts.py [--db NAME]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

from exposure_workbench.services.concept_mapping import normalize_concept  # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

LOOKS_LIKE_DEBT = re.compile(r"LongTermDebt|Borrowings|NotesPayable|CommercialPaper|DebtCurrent|DebtNoncurrent")
# a maturity schedule, a rate, a receivable, a fair value, an unused facility, an
# asset pledged: named like debt, not a balance of it
NOT_A_DEBT_BALANCE = re.compile(r"Maturities|InterestRate|Receivable|FairValue|Capacity|Transfers|Proceeds|Repayments")

# (ticker, concept) -> why it is left unread, as of V38 (2026-09-16)
KNOWN: dict[tuple[str, str], str] = {
    ("XOM", "us-gaap:ShortTermBankLoansAndNotesPayable"):
        "a component of the DebtCurrent XOM files beside it; reading it would sum it twice",
    ("LLY", "us-gaap:NotesPayable"): "not yet examined: LLY files LongTermDebt and DebtCurrent beside it",
    ("LLY", "us-gaap:OtherNotesPayable"): "not yet examined (under 0.1bn)",
    ("LLY", "us-gaap:OtherLongTermDebt"): "not yet examined: LLY files LongTermDebt beside it",
    ("KO", "us-gaap:OtherShortTermBorrowings"):
        "not yet examined: KO's ShortTermBorrowings stops in 2022 and this may be its continuation",
}


async def unmapped(db_name: str | None = None) -> list[dict]:
    url = URL.replace("/exposure_workbench", f"/{db_name}") if db_name else URL
    engine = create_async_engine(url)
    try:
        async with engine.connect() as con:
            rows = (await con.execute(text(
                "SELECT c.ticker, f.raw_concept AS rc, max(f.period_end) AS last, max(abs(f.value)) AS v, count(*) AS n "
                "  FROM financial_facts f JOIN companies c ON c.id = f.company_id "
                " WHERE f.dimensions_hash = '' AND f.period_start IS NULL AND f.value IS NOT NULL "
                " GROUP BY 1, 2"))).mappings().all()
    finally:
        await engine.dispose()
    out = []
    for r in rows:
        tag = str(r["rc"]).partition(":")[2] or str(r["rc"])
        if not LOOKS_LIKE_DEBT.search(tag) or NOT_A_DEBT_BALANCE.search(tag):
            continue
        if normalize_concept(r["rc"]) is not None:
            continue
        out.append({"ticker": r["ticker"], "concept": r["rc"], "last": str(r["last"]), "max": float(r["v"]),
                    "facts": int(r["n"]), "known": KNOWN.get((r["ticker"], r["rc"]))})
    return sorted(out, key=lambda x: (x["ticker"], x["concept"]))


async def main(db_name: str | None) -> None:
    for u in await unmapped(db_name):
        flag = "known" if u["known"] else "NEW"
        print(f"{flag:5} {u['ticker']:6} {u['concept']:<60} last {u['last']}  max {u['max'] / 1e9:,.2f}bn  "
              f"({u['facts']} facts){'  — ' + u['known'] if u['known'] else ''}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    asyncio.run(main(ap.parse_args().db))
