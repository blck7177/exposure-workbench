"""V30 Phase 0 — gold figures for the battery, derived by the desk's own services.

A quantitative turn has a right answer the desk can compute without a model:
the top-five share IS the sum of the five largest weights on the latest run of
the fixture; a drawdown's depth IS what drawdown_service reports. Until now the
battery scored these with an LLM judge reading prose. Here each turn that has a
computable answer states it as data, derived by a small function over the
fixture database (scripts/battery_fixture.sh), and the rubric checks the
rendered figures against it deterministically (rubric_battery.py: figures_*).

A derivation is `async def (db) -> Gold`. It calls the same services the tools
call — never the model, never a tool — so the gold is the desk's own answer.
Register one per turn tag in the set's module (scripts/gold/v24.py etc.). A
turn with no computable figure states `skip` with the reason; it is still
scored by the judge on its other criteria.

    python scripts/gold_derive.py v24 [--only N06-top-five#t1]  -> tests/battery/gold_v24.json
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Figure:
    key: str                 # what the figure answers, in the analyst's words: "top_five_share"
    value: float
    unit: str                # RATIO | MONEY | COUNT | MULTIPLE | MONEY_PER_SHARE | MONEY_PER_DAY | COUNT_PER_DAY
    subject: str | None = None
    must: bool = True        # an answer that lacks it has not answered the question
    note: str = ""           # how it was derived, for a reader of the gold file


@dataclass
class Gold:
    figures: list[Figure] = field(default_factory=list)
    identity: list[str] = field(default_factory=list)   # dates / labels legitimately in prose
    derived_by: str = ""
    skip: str | None = None                             # reason this turn has no gold

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def skip(reason: str) -> Gold:
    return Gold(skip=reason)
