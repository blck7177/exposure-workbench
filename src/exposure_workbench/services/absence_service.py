"""An absence is a fact about the filings, and it gets an id like any other.

V11-A (gap G1). This desk's claim is that every number is traceable, and until
now that held only for numbers it produced. A refusal — "EBITDA is unavailable",
"the last four quarters cannot be derived" — was an error dict with no evidence
row behind it, and three consequences followed, all measured in the agent
battery over 43 real sessions:

  * The citation gate demands ids, and a refusal had none to offer. Every
    "cannot be produced" answer in the battery hit invalid_citations — three for
    three — and the model worked up through citing tool names, then the company
    id `co_jpm`, then an invented `run_?`, before landing on the empty list that
    had been correct all along.

  * With no statement to relay, the model wrote its own, and twice out of three
    it relocated the absence: "capex is not reported" for LLY, whose capex is
    filed every quarter under a tag this desk has not mapped, and "not reported
    as such in the model" for MSFT, which files depreciation every quarter and
    simply not the combined D&A line EBITDA needs. Our coverage gap, described
    to the user as the issuer's disclosure gap.

  * A refusal that carries only what is missing gives nothing to do next. The
    one refusal in the battery that WAS relayed well — the typed calculator's
    double-count — is the one whose payload named both operands.

So the statement is composed here, from facts, and the model transcribes it
rather than authoring it. The row resolves through the ordinary `calc_` prefix,
and it deliberately holds NO numeric `value`: an absence supports the sentence
that something could not be produced, and never a figure.

What this does not do: guess. `neighbours` carries the registry's declared
alternatives and the per-metric coverage the corpus actually has. It will not
propose that MSFT's `depreciation` stands in for `depreciation_amortization` —
that is a claim about accounting nobody validated, and inventing it here is the
failure mode the whole design exists to remove.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import calc_service as cs

OP_ABSENCE = "absence"


def superseded_by(metric: str) -> tuple[str, ...]:
    """Metrics the registry names as stand-ins for this one, deduped in order.

    The knowledge already exists as data — Formula.alternatives, added when
    NVDA's revenue moved to total_revenues and LLY's interest expense to its
    non-operating tag. It was readable only by evaluate_formula, so a direct
    get_flow refusal could not mention it and the model reported an absence that
    was one argument away from an answer.
    """
    out: list[str] = []
    for f in fm.FORMULAS.values():
        for alt in f.alternatives.get(metric, ()):
            if alt not in out:
                out.append(alt)
    return tuple(out)


async def coverage(db: AsyncSession, ticker: str, metrics: tuple[str, ...]) -> dict[str, dict]:
    """What this desk holds for each named metric: how many periods, through when."""
    have = {m["metric"]: m for m in
            (await cs.list_available_metrics(db, ticker.upper()))["metrics"]}
    return {m: ({"periods": have[m]["periods"], "through": have[m]["latest_period_end"]}
                if m in have else None)
            for m in metrics}


async def issuer_latest(db: AsyncSession, ticker: str) -> str | None:
    """The most recent period end this desk holds for the issuer, over all metrics."""
    rows = (await cs.list_available_metrics(db, ticker.upper()))["metrics"]
    return max((r["latest_period_end"] for r in rows), default=None)


async def record(
    db: AsyncSession,
    *,
    kind: str,
    ticker: str | None,
    statement: str,
    tried: dict,
    stopped_at: dict | None = None,
    neighbours: dict | None = None,
    invoked_by: str = "agent",
) -> str:
    """One append-only row for a thing that could not be produced. Returns its id."""
    return await cs._record(
        db, ticker, f"{OP_ABSENCE}.{kind}",
        {"tried": tried,
         "stopped_at": stopped_at or {},
         "neighbours": neighbours or {},
         # No result_type: nothing here is a quantity, and the resolver must not
         # find one. A number cited only to an absence is refused, correctly.
         },
        {"statement": statement}, [], {}, invoked_by,
    )


async def refuse(
    db: AsyncSession,
    error: str,
    *,
    kind: str,
    ticker: str | None,
    statement: str,
    tried: dict,
    stopped_at: dict | None = None,
    neighbours: dict | None = None,
    invoked_by: str = "agent",
    **extra: object,
) -> dict:
    """The error dict a tool returns, with an id and a sentence the model can quote."""
    absence_id = await record(db, kind=kind, ticker=ticker, statement=statement,
                              tried=tried, stopped_at=stopped_at,
                              neighbours=neighbours, invoked_by=invoked_by)
    return {"error": error, "absence_id": absence_id, "statement": statement,
            **({"ticker": ticker} if ticker else {}), **extra}
