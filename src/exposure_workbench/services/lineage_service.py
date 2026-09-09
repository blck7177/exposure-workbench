"""Supersession between two metric lines, derived from the filings (V31).

An issuer can move a quantity from one XBRL tag to another. NVDA's `revenue`
line stops 2022-01-30; `total_revenues` runs to 2026-07-26; over the year both
were filed the two agree to the dollar. Asked for "the latest twelve months of
revenue", the desk had an answer on the dead line and gave it — 26.9bn against a
303.0bn top line, with no warning (2026-09-09, production).

The knowledge existed. `analytics.formulas.Formula.alternatives` has recorded the
pair since V9, and only `evaluate_formula` could read it, so the scalar formula
path was right all along while the catalogue, the direct read and the series grid
were not. This module is the one home: `derive` writes what the overlap says,
`continuation` is what every consumer asks.

Nothing here is authored. `concept_mapping.SUPERSESSION_CANDIDATES` says which
pairs COULD be one line — a statement about the taxonomy. Whether a pair IS one
line for an issuer is decided from that issuer's own facts and recorded with the
evidence that decided it, so a reader can see why the desk followed it.

Three shapes the data takes, and only one of them is lineage:

  A stopped, B continues, the overlap agrees   → agrees, followed
  A stopped, B continues, overlap disagrees    → row with agrees = FALSE, refused
      or never overlapped                        and the reason stated
  both continue, or only B exists              → no row (two quantities, or a
                                                 plain absence with a stand-in)

Following an agreeing lineage is not a fallback. A fallback is "A is missing, so
quietly give B". This is "the desk recorded, from the filings, that A and B are
one line, so a window A never covered is read on B and the page says which tag
the figure came from". The quantity is never renamed: the Fact says B.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, FinancialFact, MetricLineage
from exposure_workbench.services.concept_mapping import MAPPING_VERSION, SUPERSESSION_CANDIDATES

# How close two tags must be, over the periods both were filed for, to be called
# one line. NVDA's overlap is exactly 0. A pair that disagrees by more than this
# is two quantities however similar their names (XOM files both top lines 5.2%
# apart, and neither stops, so it never reaches this test).
LINEAGE_TOL = 0.005


@dataclass(frozen=True)
class Lineage:
    """One issuer's retired line and what continues it."""
    from_metric: str
    to_metric: str
    from_last_period_end: date
    to_last_period_end: date
    switched_at: date | None
    overlap_periods: int
    overlap_max_rel_diff: float | None
    agrees: bool

    @property
    def statement(self) -> str:
        """Why the desk does or does not follow it, in the desk's own words."""
        if self.agrees:
            return (f"{self.from_metric} was filed under {self.to_metric} from "
                    f"{self.switched_at}; over the {self.overlap_periods} period(s) both were "
                    f"reported they agree, so this desk reads them as one line")
        if not self.overlap_periods:
            return (f"{self.from_metric} ends {self.from_last_period_end} and {self.to_metric} "
                    f"continues past it, but no period was reported under both, so this desk "
                    f"cannot say they are one line")
        return (f"{self.from_metric} and {self.to_metric} were both reported for "
                f"{self.overlap_periods} period(s) and differ by up to "
                f"{self.overlap_max_rel_diff:.1%}, so this desk holds them as two quantities")


async def _periods(db: AsyncSession, company_id: str, metric: str) -> dict[tuple[date, date | None], float]:
    """The issuer's undimensioned facts for one metric, keyed by their period.

    Dimensioned rows are segment breakdowns; comparing a segment against a total
    would manufacture a disagreement out of a difference that is not one.
    """
    rows = (await db.execute(
        select(FinancialFact.period_start, FinancialFact.period_end, FinancialFact.value)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric == metric,
               FinancialFact.dimensions_hash == "",
               FinancialFact.period_end.is_not(None),
               FinancialFact.value.is_not(None))
    )).all()
    out: dict[tuple[date, date | None], float] = {}
    for start, end, value in rows:
        out[(end, start)] = float(value)
    return out


def _judge(a: dict, b: dict) -> tuple[int, float | None, bool]:
    """(overlap periods, largest relative difference, agrees) for two period maps."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return 0, None, False
    worst = max(abs(a[k] - b[k]) / max(1.0, abs(b[k])) for k in shared)
    return len(shared), worst, worst <= LINEAGE_TOL


async def derive(db: AsyncSession, company_id: str) -> list[Lineage]:
    """Recompute this issuer's lineage rows from its facts. Idempotent."""
    out: list[Lineage] = []
    for frm, to in SUPERSESSION_CANDIDATES:
        a = await _periods(db, company_id, frm)
        b = await _periods(db, company_id, to)
        if not a or not b:
            continue
        a_last, b_last = max(k[0] for k in a), max(k[0] for k in b)
        if b_last <= a_last:
            continue                      # nothing stopped; two lines, both current
        n, worst, agrees = _judge(a, b)
        after = [k[0] for k in b if k[0] > a_last]
        lin = Lineage(frm, to, a_last, b_last, min(after) if after else None, n, worst, agrees)
        await db.execute(pg_insert(MetricLineage).values(
            company_id=company_id, from_metric=frm, to_metric=to,
            from_last_period_end=lin.from_last_period_end, to_last_period_end=lin.to_last_period_end,
            switched_at=lin.switched_at, overlap_periods=lin.overlap_periods,
            overlap_max_rel_diff=lin.overlap_max_rel_diff, agrees=lin.agrees,
            mapping_version=MAPPING_VERSION,
        ).on_conflict_do_update(
            index_elements=["company_id", "from_metric", "to_metric"],
            set_={"from_last_period_end": lin.from_last_period_end,
                  "to_last_period_end": lin.to_last_period_end, "switched_at": lin.switched_at,
                  "overlap_periods": lin.overlap_periods, "overlap_max_rel_diff": lin.overlap_max_rel_diff,
                  "agrees": lin.agrees, "mapping_version": MAPPING_VERSION, "derived_at": func.now()},
        ))
        out.append(lin)
    return out



async def continuation(db: AsyncSession, ticker: str, metric: str, *, only_agreeing: bool = True) -> Lineage | None:
    """What continues this issuer's `metric`, if the filings say anything continues it.

    The one question every consumer asks. `only_agreeing=False` is for the
    refusal path, which wants to name a continuation it will not follow.
    """
    row = (await db.execute(
        select(MetricLineage).join(Company, Company.id == MetricLineage.company_id)
        .where(Company.ticker == ticker.upper(), MetricLineage.from_metric == metric)
        .order_by(MetricLineage.agrees.desc(), MetricLineage.to_last_period_end.desc())
    )).scalars().first()
    if row is None or (only_agreeing and not row.agrees):
        return None
    return Lineage(row.from_metric, row.to_metric, row.from_last_period_end, row.to_last_period_end,
                   row.switched_at, row.overlap_periods, row.overlap_max_rel_diff, row.agrees)


async def for_issuer(db: AsyncSession, ticker: str) -> dict[str, Lineage]:
    """Every lineage row this issuer has, by the retired metric — the catalogue's read."""
    rows = (await db.execute(
        select(MetricLineage).join(Company, Company.id == MetricLineage.company_id)
        .where(Company.ticker == ticker.upper())
    )).scalars().all()
    return {r.from_metric: Lineage(r.from_metric, r.to_metric, r.from_last_period_end, r.to_last_period_end,
                                   r.switched_at, r.overlap_periods, r.overlap_max_rel_diff, r.agrees)
            for r in rows}
