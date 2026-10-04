"""One name's own column of a book, read off a completed run — as a MEASURE.

The risk manager's `book_read` reads a whole table, a column or a cell by
coordinates; an analysis asks for a name's weight the way it asks for its net
margin: by measure, over subjects, at the latest run or the one before. This is
the service behind `book.weight` and `book.market_value` on the registry
(executor `book.column`): no arithmetic, the run's own figure under the name the
run gives it, with the ref the typed calculator already resolves
(`<run_id>:issuer_exposures.<T>.<column>`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ExposureRun, IssuerExposure
from exposure_workbench.services import catalogue_service, run_reads_service

COLUMNS: dict[str, str] = {"weight": "RATIO", "market_value": "MONEY", "contribution": "RATIO"}
WHICH = ("latest", "prior")


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


async def runs_of(db: AsyncSession, portfolio_id: str, n: int = 2) -> list[ExposureRun]:
    """The book's completed runs, newest first."""
    return list((await db.execute(
        select(ExposureRun).where(ExposureRun.portfolio_id == portfolio_id, ExposureRun.status == "completed")
        .order_by(ExposureRun.as_of_date.desc(), ExposureRun.created_at.desc()).limit(n))).scalars().all())


async def resolve_run(db: AsyncSession, book: str | None, which: str, ticker: str | None = None) -> ExposureRun | dict:
    """The run a book word names: a port_ id's latest or prior completed run, a run_
    id itself (loaded through the one door, run_reads_service); no book, the one
    book holding the name."""
    if which not in WHICH:
        return _err("invalid_params", f"which is one of {', '.join(WHICH)}")
    if book is None:
        if ticker is None:
            return _err("invalid_params", "name the book, or the ticker whose book is meant")
        held = ((await catalogue_service.in_book(db, ticker.upper())) or {}).get("held_in") or []
        books = sorted({h["portfolio_id"] for h in held})
        if len(books) != 1:
            return _err("not_held" if not books else "ambiguous_book",
                        f"{ticker.upper()} is a position of {len(books)} books on this desk; name one"
                        if books else f"{ticker.upper()} is not a position of any completed run on this desk")
        book = books[0]
    if book.startswith("run_"):
        run = await run_reads_service.completed_run(db, book)
        if isinstance(run, dict):
            return run
        if which == "prior":
            earlier = [r for r in await runs_of(db, run.portfolio_id, n=50) if r.as_of_date < run.as_of_date]
            if not earlier:
                return _err("no_prior_run", f"{book} has no completed run before it")
            return earlier[0]
        return run
    runs = await runs_of(db, book)
    if not runs:
        return _err("no_completed_run", f"{book} has no completed run")
    if which == "prior":
        if len(runs) < 2:
            return _err("no_prior_run", f"{book} has one completed run; there is no run before {runs[0].id}")
        return runs[1]
    return runs[0]


async def read_column(db: AsyncSession, ticker: str, column: str, book: str | None = None,
                      which: str = "latest") -> dict:
    """One name's `column` on the run `book`/`which` names."""
    if column not in COLUMNS:
        return _err("invalid_params", f"column is one of {', '.join(COLUMNS)}")
    tk = ticker.upper()
    run = await resolve_run(db, book, which, tk)
    if isinstance(run, dict):
        return run
    row = (await db.execute(select(IssuerExposure).where(IssuerExposure.run_id == run.id,
                                                          IssuerExposure.ticker == tk))).scalar_one_or_none()
    if row is None or getattr(row, column) is None:
        return _err("not_held", f"{tk} is not a position of {run.id} ({run.as_of_date.isoformat()})",
                    run_id=run.id, as_of=run.as_of_date.isoformat())
    return {"subject": tk, "ticker": tk, "run_id": run.id, "portfolio_id": run.portfolio_id,
            "as_of": run.as_of_date.isoformat(), "which": which, "column": column,
            "value": float(getattr(row, column)), "unit_class": COLUMNS[column],
            "quantity": f"issuer_exposures.{column}", "sector": row.sector,
            "ref": f"{run.id}:issuer_exposures.{tk}.{column}",
            "basis": f"the run's own {column} of {tk}, {run.id} as of {run.as_of_date.isoformat()}"}
