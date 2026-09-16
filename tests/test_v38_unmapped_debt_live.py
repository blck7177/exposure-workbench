"""V38/S3 — no debt-like balance tag is left unread without a reason (live).

Run with:  pytest -m live -k unmapped_debt

XOM's term debt sat under a tag no metric claimed, and the desk's "total debt"
for XOM was its current debt alone. An unmapped tag is stored and never read,
so nothing surfaced it; scripts/unmapped_family_concepts.py lists them, and
this goes red on one that nobody has looked at.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

_SPEC = importlib.util.spec_from_file_location(
    "unmapped_family_concepts", Path(__file__).resolve().parents[1] / "scripts" / "unmapped_family_concepts.py")
ufc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ufc)


async def test_every_unread_debt_tag_is_one_somebody_looked_at():
    found = await ufc.unmapped()
    new = [f"{u['ticker']} {u['concept']} (last {u['last']}, {u['max'] / 1e9:,.2f}bn)" for u in found if not u["known"]]
    assert new == [], "debt-like balances this desk does not read — map them, or say why not in KNOWN: " + "; ".join(new)


async def test_xoms_term_debt_is_read():
    found = await ufc.unmapped()
    assert not [u for u in found if u["ticker"] == "XOM" and "LongTermDebtAndCapitalLeaseObligations" in u["concept"]]
