"""M1 company_service — read-path branch tests (offline, mocked DB session)."""

from __future__ import annotations

import pytest

from exposure_workbench.services import company_service as cs


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """Minimal async DB stub: every execute() returns the same fixed row."""

    def __init__(self, obj):
        self._obj = obj

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._obj)


class _Company:
    def __init__(self, ticker, is_investigable):
        self.ticker = ticker
        self.is_investigable = is_investigable


async def test_get_by_ticker_found():
    c = _Company("NVDA", True)
    got = await cs.get_by_ticker(_FakeDB(c), "NVDA")
    assert got is c


async def test_get_by_ticker_missing_raises():
    with pytest.raises(cs.CompanyNotFound):
        await cs.get_by_ticker(_FakeDB(None), "ZZZZ")


async def test_require_investigable_ok():
    c = _Company("AAPL", True)
    got = await cs.require_investigable(_FakeDB(c), "AAPL")
    assert got is c


async def test_require_investigable_missing_raises():
    with pytest.raises(cs.CompanyNotFound):
        await cs.require_investigable(_FakeDB(None), "ZZZZ")


async def test_require_investigable_etf_raises():
    etf = _Company("TLT", False)
    with pytest.raises(cs.NotInvestigable):
        await cs.require_investigable(_FakeDB(etf), "TLT")
