"""The scope of an analysis: WHICH subjects, bound by the runtime from the desk's books.

The lead chooses a scope in business terms — the Technology holdings of a book,
five named issuers, every holding — and this module turns that into subject ids,
runs and a status. It never widens or narrows a choice in silence: a scope asked
for as five names that the book resolves to three is `mismatch`, and the three
are analysed under that word. Nothing here reads a figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import IssuerExposure
from exposure_workbench.services import book_columns, company_service, portfolio_service

MAX_SUBJECTS = 32
RESOLVED, MISMATCH = "resolved", "mismatch"


@dataclass(frozen=True)
class Scope:
    subjects: tuple[str, ...]
    book: str | None                       # the portfolio the subjects were taken from, if a book was named
    runs: dict = field(default_factory=dict)       # {"latest": {"id","as_of"}, "prev": {...}} of that book
    basis: str = ""                        # how the subjects were chosen, in the caller's words
    expected_count: int | None = None
    sectors: dict = field(default_factory=dict)    # subject -> sector, as the book says
    status: str = RESOLVED

    @property
    def resolved_count(self) -> int:
        return len(self.subjects)

    def as_dict(self) -> dict:
        out: dict = {"subjects": list(self.subjects), "resolved_count": self.resolved_count, "status": self.status}
        if self.book:
            out["book"] = self.book
            out["runs"] = self.runs
        if self.basis:
            out["basis"] = self.basis
        if self.expected_count is not None:
            out["expected_count"] = self.expected_count
        if self.sectors:
            out["sectors"] = self.sectors
        return out


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


async def _runs(db: AsyncSession, portfolio_id: str) -> dict:
    runs = await book_columns.runs_of(db, portfolio_id, n=2)
    out: dict = {}
    if runs:
        out["latest"] = {"id": runs[0].id, "as_of": runs[0].as_of_date.isoformat()}
    if len(runs) > 1:
        out["prev"] = {"id": runs[1].id, "as_of": runs[1].as_of_date.isoformat()}
    return out


async def _holdings(db: AsyncSession, run_id: str) -> list[IssuerExposure]:
    return list((await db.execute(select(IssuerExposure).where(IssuerExposure.run_id == run_id)
                                  .order_by(IssuerExposure.weight.desc()))).scalars().all())


async def catalogue(db: AsyncSession) -> dict:
    """What the desk holds, by name: every active book with its two latest runs and
    its holdings (ticker, sector), and the issuers that can be analysed. Names and
    dates only — a figure the model has not asked for is a figure nothing stands behind."""
    books = []
    for p in await portfolio_service.list_portfolios(db, active_only=True):
        runs = await _runs(db, p.id)
        holdings = await _holdings(db, runs["latest"]["id"]) if runs.get("latest") else []
        books.append({"portfolio_id": p.id, "name": p.name, "runs": runs,
                      "holdings": [{"ticker": h.ticker, "sector": h.sector} for h in holdings]})
    companies = await company_service.list_companies(db, investigable_only=True)
    ready = await company_service.ready_company_ids(db, [c.id for c in companies])
    return {"books": books,
            "issuers_on_desk": sorted(c.ticker for c in companies if c.id in ready),
            "issuers_preparing": sorted(c.ticker for c in companies if c.id not in ready)}


async def bind(db: AsyncSession, spec: dict | None) -> Scope | dict:
    """Subjects from a scope specification.

        {"subjects": ["AAPL", "MSFT"]}                     named issuers
        {"book": "port_001", "sector": "Technology"}       a book's holdings in one sector
        {"book": "port_001", "holdings": "all"}            every holding of a book
    plus `expected_count` (what the question said there were) and `basis` (why
    these). A book may be omitted when the desk has exactly one.
    """
    spec = dict(spec or {})
    expected = spec.get("expected_count")
    if expected is not None and (not isinstance(expected, int) or expected < 1):
        return _err("invalid_scope", "expected_count is a positive integer")
    book = spec.get("book")
    if book is None and (spec.get("sector") or spec.get("holdings")):
        portfolios = await portfolio_service.list_portfolios(db, active_only=True)
        if len(portfolios) != 1:
            return _err("ambiguous_book", f"the desk has {len(portfolios)} books; name one with `book`")
        book = portfolios[0].id
    runs: dict = {}
    sectors: dict = {}
    subjects: list[str] = []
    basis = str(spec.get("basis") or "")
    if book is not None:
        if await portfolio_service.get_portfolio(db, book) is None:
            return _err("unknown_book", f"{book} is not a book on this desk")
        runs = await _runs(db, book)
        if not runs.get("latest"):
            return _err("no_completed_run", f"{book} has no completed run to take holdings from")
        held = await _holdings(db, runs["latest"]["id"])
        sectors = {h.ticker: h.sector for h in held}
        if spec.get("sector"):
            want = str(spec["sector"]).strip().lower()
            subjects = [h.ticker for h in held if (h.sector or "").strip().lower() == want]
            basis = basis or f"holdings of {book} in sector {spec['sector']}"
            if not subjects:
                return _err("scope_unresolved", f"{book} holds no position in sector {spec['sector']!r}",
                            sectors=sorted({h.sector for h in held if h.sector}))
        elif spec.get("holdings") == "all":
            subjects = [h.ticker for h in held]
            basis = basis or f"every holding of {book}"
    if spec.get("subjects"):
        named = [str(t).strip().upper() for t in spec["subjects"] if str(t).strip()]
        subjects = list(dict.fromkeys([*subjects, *named])) if subjects else named
        basis = basis or "the subjects named"
    if not subjects:
        return _err("scope_unresolved", "a scope names subjects, or a book with a sector or holdings='all'")
    if len(subjects) > MAX_SUBJECTS:
        return _err("scope_too_large", f"{len(subjects)} subjects; the analysis takes at most {MAX_SUBJECTS} — "
                                       f"narrow the scope or split it", subjects=len(subjects))
    status = RESOLVED if expected is None or expected == len(subjects) else MISMATCH
    return Scope(subjects=tuple(subjects), book=book, runs=runs, basis=basis, expected_count=expected,
                 sectors={t: sectors.get(t) for t in subjects if t in sectors}, status=status)
