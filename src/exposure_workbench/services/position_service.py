"""A name's place in the desk's books (V1): the one figure family an issuer
analyst needs from the book, asked for BY NAME.

WHY THIS EXISTS. The issuer analyst reads filings; it never reads a run's
tables (tools/faces: `book_read` is the risk manager's). But "how much of this
name do we hold" is part of an issuer reading — the old issuer domains closed
with "if held, the position's weight" and had to reach across for it. A
cross-resource need is met by a MEASURE on the registry, not by widening a face:
`book.position` is on the issuer analyst's metric list and yields exactly the
name's own rows of the latest completed run of each book that holds it.

Every figure here is the run's own (no arithmetic): it resolves through the run
id under the name the run gives it, and a check's row says where the check
stands, so the figures of it carry that word (analytics/registry.words_beside).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import catalogue_service
from exposure_workbench.services import quantities as qn

_POSITION_COLUMNS = ("weight", "market_value", "contribution")
_CHECK_COLUMNS = ("current_value", "warning_level", "breach_level")


def _figure(q, run_id: str, quantity: str) -> dict:
    return {"value": q.value, "ref": f"{run_id}:{q.label}", "quantity": quantity, "unit_class": q.unit_class}


async def position(db: AsyncSession, ticker: str, book: str | None = None) -> dict:
    tk = ticker.upper()
    held = ((await catalogue_service.in_book(db, tk)) or {}).get("held_in") or []
    if book:
        held = [h for h in held if book in (h["portfolio_id"], h["run_id"])]
    if not held:
        where = f"book {book}" if book else "any book on this desk"
        return {"error": "not_held", "ticker": tk,
                "detail": f"{tk} is not a position of the latest completed run of {where}"}
    results = []
    for h in held:
        resolved = await qn.of_ref(db, h["run_id"])
        by_label = {q.label: q for q in resolved.quantities if q.not_alone is None}
        out: dict = {"subject": tk, "ticker": tk, "run_id": h["run_id"], "portfolio_id": h["portfolio_id"],
                     "as_of": h["as_of"], "position": {}, "checks": []}
        for col in _POSITION_COLUMNS:
            q = by_label.get(f"issuer_exposures.{tk}.{col}")
            if q is not None:
                out["position"][col] = _figure(q, h["run_id"], f"issuer_exposures.{col}")
        for c in h.get("checks") or []:
            label = c["name"].removeprefix("limit_checks.").removesuffix(".current_value")
            row: dict = {"label": label, "status": c.get("status")}
            for col in _CHECK_COLUMNS:
                q = by_label.get(f"limit_checks.{label}.{col}")
                if q is not None:
                    row[col] = _figure(q, h["run_id"], f"limit_checks.{col}")
            out["checks"].append(row)
        results.append(out)
    return results[0] if len(results) == 1 else {"results": results, "count": len(results)}
