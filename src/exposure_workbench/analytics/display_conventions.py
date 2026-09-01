"""How a number looks to a reader, decided once (V15-S6).

Three surfaces show the same figure: the answer renderer, the stored prose of a
block answer, and the table the model reads. Each used to round on its own —
AnswerBlocks.tsx had one rule, prose_of printed every digit, the rubric judged
the second and scored "ledger precision" against answers whose readers saw the
first. Two rules about how a number looks disagree the first time one changes.

So the rule is data here, and the web mirror (apps/web/lib/display.ts) is held
to the same cases by tests/fixtures/display_cases.json: the Python test and the
vitest suite read one file and must both agree with it.

`reader_value` is the numeric form the MODEL is shown — rounded so it reads as a
figure rather than a float dump, and never authored back by the model (the exit
takes names, not values). `display` is the string a person reads.
"""

from __future__ import annotations

PERCENT_DIGITS = {"ge10": 1, "lt10": 2}
MONEY_SCALES = ((1e9, "B"), (1e6, "M"), (1e3, "K"))
MONEY_DIGITS = {"ge100": 0, "lt100": 2}
MULTIPLE_DIGITS = 2

# Decimal places kept in the model-facing table, per unit class.
MODEL_DECIMALS = {"RATIO": 4, "PERCENT": 4, "MONEY": 0, "MULTIPLE": 3, "COUNT": 2}


def reader_value(value: float, unit_class: str) -> float | int:
    """The figure as the model's table shows it: rounded to the unit's precision."""
    places = MODEL_DECIMALS.get(unit_class, 4)
    v = round(float(value), places)
    if places == 0 or (unit_class == "COUNT" and float(v).is_integer()):
        return int(v)
    return v


def display(value: float, unit_class: str) -> str:
    """What a reader sees. Mirrors apps/web/lib/display.ts exactly."""
    v = float(value)
    if unit_class in ("RATIO", "PERCENT"):
        pct = v * 100
        digits = PERCENT_DIGITS["ge10"] if abs(pct) >= 10 else PERCENT_DIGITS["lt10"]
        return f"{pct:.{digits}f}%"
    if unit_class == "MONEY":
        scale, suffix = 1.0, ""
        for s, name in MONEY_SCALES:
            if abs(v) >= s:
                scale, suffix = s, name
                break
        scaled = v / scale
        digits = MONEY_DIGITS["ge100"] if abs(scaled) >= 100 else MONEY_DIGITS["lt100"]
        return f"${scaled:.{digits}f}{suffix}"
    if unit_class == "MULTIPLE":
        return f"{v:.{MULTIPLE_DIGITS}f}×"
    if unit_class == "COUNT":
        return str(int(v)) if v.is_integer() else f"{v:.2f}"
    return str(value)
