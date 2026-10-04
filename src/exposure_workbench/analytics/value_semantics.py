"""What KIND of number a figure is: a level, an absolute change or a relative change.

A ratio of 0.6966 and a difference of two ratios of -0.1930 are both dimensionless,
and until this module both were displayed by the percent rule, so a cash conversion
that fell from 88.96% to 69.66% was shown as "-19.3%" — a relative decline of 19.3%
to any reader, when the figure is 19.3 percentage POINTS. The kind travels with the
figure: on the ledger row (`params.result_type.semantic`), on the Fact
(`params.semantic`) and into every display and check that reads either.

The three kinds and how a dimensionless one displays:
    level             0.6966     -> 69.7%
    absolute_change  -0.1930     -> -19.3 pp
    relative_change  -0.2169     -> -21.7%

Nothing here decides a kind from a number. The producer that knows what it
computed states it (typed_calculator.change, analysis_execution); a reader that
finds none reads a level, because every row written before this module was one.
"""

from __future__ import annotations

from dataclasses import dataclass

LEVEL = "level"
ABSOLUTE_CHANGE = "absolute_change"
RELATIVE_CHANGE = "relative_change"
KINDS = (LEVEL, ABSOLUTE_CHANGE, RELATIVE_CHANGE)
CHANGES = (ABSOLUTE_CHANGE, RELATIVE_CHANGE)

KEY = "semantic"       # the params key both the Fact and the ledger row carry it under


@dataclass(frozen=True)
class Semantics:
    kind: str = LEVEL
    measure: str | None = None            # the measure both endpoints of a change are a level of
    current: str | None = None            # the ref (calc_/f_/run named) of the later reading
    baseline: str | None = None           # the ref of the earlier reading
    current_period: dict | None = None    # {"start","end"} | {"instant"} | {"run","as_of"}
    baseline_period: dict | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"semantic kind {self.kind!r} is not one of {KINDS}")

    @property
    def is_change(self) -> bool:
        return self.kind in CHANGES

    def as_params(self) -> dict:
        out: dict = {"kind": self.kind}
        for key in ("measure", "current", "baseline", "current_period", "baseline_period"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def of(params: dict | None) -> Semantics:
    """The semantics a params blob carries; a level when it carries none."""
    raw = (params or {}).get(KEY)
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return Semantics()
    return Semantics(kind=raw["kind"], measure=raw.get("measure"), current=raw.get("current"),
                     baseline=raw.get("baseline"), current_period=raw.get("current_period"),
                     baseline_period=raw.get("baseline_period"))


def kind_of(params: dict | None) -> str:
    return of(params).kind


def period_words(period: dict | None) -> str:
    """One endpoint of a change, as words: a window's two dates, an instant, a run."""
    if not isinstance(period, dict):
        return ""
    if period.get("start") and period.get("end"):
        return f"{period['start']}..{period['end']}"
    if period.get("instant"):
        return f"as of {period['instant']}"
    if period.get("run"):
        return f"run {period['run']}" + (f" ({period['as_of']})" if period.get("as_of") else "")
    return ""
