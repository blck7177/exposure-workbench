"""V17 — a company row is born from the listed universe (offline, mocked DB).

WHY THIS FILE. `companies` had one writer: a hand-typed list of eight issuers in
the seed script. Everything else on the desk already worked on the whole listed
universe — the typeahead searched ~13k securities, an upload priced any of them,
an exposure run regressed them — so a reader could hold forty names, click one,
and be told the desk had never heard of it. `company_service.admit` is the
second writer, and these tests hold its three refusals apart and its one write
canonical.

The refusals are three different facts about the world and a reader is owed
which one it is: NOT LISTED (no such active security), NOT INVESTIGABLE (an ETF
files no statements), NOT AN SEC FILER (listed, but no CIK to read filings by).
None of them is retryable, and none of them is the others.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import company_service as cs
from exposure_workbench.utils import cik as cik_util


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _DB:
    """Returns queued results in order, and records every statement executed."""

    def __init__(self, results):
        self._queue = list(results)
        self.statements = []
        self.flushed = 0

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        return _Result(self._queue.pop(0) if self._queue else None)

    async def flush(self):
        self.flushed += 1


class _Company:
    def __init__(self, ticker, is_investigable=True, cik=None):
        self.ticker = ticker
        self.is_investigable = is_investigable
        self.cik = cik


class _Listed:
    def __init__(self, ticker, *, name="A Company", exchange="NASDAQ",
                 is_etf=False, cik="0000320193", status="active"):
        self.ticker, self.name, self.exchange = ticker, name, exchange
        self.is_etf, self.cik, self.status = is_etf, cik, status


def _universe(monkeypatch, row):
    async def get(_db, _ticker):
        return row
    monkeypatch.setattr(cs.sms, "get", get)


# ── the row already exists: admission is a read ──────────────────────────────

async def test_a_company_already_on_the_desk_is_returned_untouched(monkeypatch):
    """Idempotence is the property every caller depends on: ensure_company_ready
    is called on every turn that needs an issuer, and it must not write."""
    existing = _Company("AAPL")
    _universe(monkeypatch, _Listed("AAPL"))
    db = _DB([existing])
    assert await cs.admit(db, "AAPL") is existing
    assert db.flushed == 0
    assert len(db.statements) == 1, "a hit must not reach the universe or the insert"


async def test_an_existing_row_that_is_not_investigable_still_refuses(monkeypatch):
    """TLT is seeded with is_investigable=False. Admission must not quietly
    promote a row somebody deliberately marked."""
    _universe(monkeypatch, _Listed("TLT", is_etf=True))
    with pytest.raises(cs.NotInvestigable):
        await cs.admit(_DB([_Company("TLT", is_investigable=False)]), "TLT")


# ── the three refusals ───────────────────────────────────────────────────────

async def test_a_symbol_outside_the_listed_universe_is_not_found(monkeypatch):
    _universe(monkeypatch, None)
    with pytest.raises(cs.CompanyNotFound):
        await cs.admit(_DB([None]), "ZZZZ")


async def test_a_delisted_security_is_not_admitted(monkeypatch):
    """The universe keeps departures rather than deleting them, so a row exists
    and says `delisted`. Admitting it would start a readiness run against a
    company with no current filings."""
    _universe(monkeypatch, _Listed("XYZ", status="delisted"))
    with pytest.raises(cs.CompanyNotFound):
        await cs.admit(_DB([None]), "XYZ")


async def test_an_etf_is_refused_with_the_reason_a_reader_needs(monkeypatch):
    _universe(monkeypatch, _Listed("HYG", is_etf=True, cik=None))
    with pytest.raises(cs.NotInvestigable) as e:
        await cs.admit(_DB([None]), "HYG")
    assert "10-K" in e.value.reason


@pytest.mark.parametrize("cik", [None, "", "   ", "n/a"])
async def test_listed_with_no_readable_cik_is_its_own_refusal(monkeypatch, cik):
    """Distinct from an ETF: there may well be statements, but not ones this
    desk can reach. Saying "not investigable" would be a claim about the
    company rather than about our reach."""
    _universe(monkeypatch, _Listed("FOO", cik=cik))
    with pytest.raises(cs.NotAnSecFiler):
        await cs.admit(_DB([None]), "FOO")


async def test_a_symbol_too_long_for_the_column_is_refused_not_truncated(monkeypatch):
    """companies.ticker is VARCHAR(16) and the universe's is VARCHAR(20). A
    truncated symbol is a row that resolves to a different security."""
    long_ticker = "A" * 17
    _universe(monkeypatch, _Listed(long_ticker))
    with pytest.raises(cs.NotInvestigable) as e:
        await cs.admit(_DB([None]), long_ticker)
    assert "16" in e.value.reason


# ── the write ────────────────────────────────────────────────────────────────

async def _admitted(monkeypatch, listed) -> tuple[_DB, dict]:
    _universe(monkeypatch, listed)
    created = _Company(listed.ticker)
    db = _DB([None, None, created])
    out = await cs.admit(db, listed.ticker)
    assert out is created
    insert = db.statements[1]
    return db, insert.compile().params


async def test_the_written_row_takes_its_identity_from_the_universe(monkeypatch):
    _, params = await _admitted(monkeypatch, _Listed("TSLA", name="Tesla, Inc.",
                                                     exchange="NASDAQ", cik="0001318605"))
    assert params["ticker"] == "TSLA"
    assert params["name"] == "Tesla, Inc."
    assert params["exchange"] == "NASDAQ"
    assert params["is_investigable"] is True
    assert params["resolved_by"] == "security_master"


async def test_the_id_keeps_the_seeds_convention(monkeypatch):
    """`co_tsla`, the same shape seed_demo_db writes, so an admitted issuer and
    a seeded one are indistinguishable once the row exists."""
    _, params = await _admitted(monkeypatch, _Listed("TSLA"))
    assert params["id"] == "co_tsla"


async def test_the_stored_cik_is_canonical_not_the_universes_padding(monkeypatch):
    """The bug this whole file is downstream of: the universe pads to ten
    digits (SEC's URL form) and edgartools returns it unpadded, so readiness
    step 1 compared "0001318605" with "1318605" and failed every admitted
    issuer with a CIK mismatch."""
    _, params = await _admitted(monkeypatch, _Listed("TSLA", cik="0001318605"))
    assert params["cik"] == "1318605"


async def test_the_row_is_re_read_after_the_insert(monkeypatch):
    """Two admissions of one name race; the row that won is the one every other
    reader will see, so the caller must hold that one and not what it built."""
    db, _ = await _admitted(monkeypatch, _Listed("TSLA"))
    assert db.flushed == 1
    assert len(db.statements) == 3, "lookup, insert, re-read"


# ── the one spelling of a CIK ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0000320193", "320193"), ("320193", "320193"), (320193, "320193"),
    (" 0000320193 ", "320193"), ("0000000001", "1"),
])
def test_canonical_cik_strips_the_padding(raw, expected):
    assert cik_util.canonical(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "CIK0000320193", "12a"])
def test_anything_that_is_not_a_number_is_no_cik_at_all(raw):
    assert cik_util.canonical(raw) is None


def test_two_spellings_of_one_number_are_the_same_cik():
    assert cik_util.same("0000320193", "320193")
    assert cik_util.same(320193, " 320193 ")


def test_two_absent_ciks_do_not_match():
    """`same` is asked whether two identities agree. Neither side having one is
    not agreement, and treating it as such would let readiness accept a company
    it never resolved."""
    assert not cik_util.same(None, None)
    assert not cik_util.same("", None)
    assert not cik_util.same("320193", "789019")
