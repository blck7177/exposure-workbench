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
# A per-share figure reads like a share price: dollars and cents, never the
# K/M/B compression that only makes sense for market values ("$2.18", not
# "$2.18" scaled). The class exists in analytics/units.py (V16).
MONEY_PER_SHARE_DIGITS = 2

# Decimal places kept in the model-facing table, per unit class.
MODEL_DECIMALS = {"RATIO": 4, "PERCENT": 4, "MONEY": 0, "MONEY_PER_SHARE": 2,
                  "MULTIPLE": 3, "COUNT": 2, "MONEY_PER_DAY": 0, "COUNT_PER_DAY": 0}


def reader_value(value: float, unit_class: str) -> float | int:
    """The figure as the model's table shows it: rounded to the unit's precision."""
    places = MODEL_DECIMALS.get(unit_class, 4)
    if unit_class == "COUNT" and 0 < abs(float(value)) < 0.01:
        places = 4                       # a fraction of a day survives the table
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
    if unit_class in ("MONEY", "MONEY_PER_DAY"):
        scale, suffix = 1.0, ""
        for s, name in MONEY_SCALES:
            if abs(v) >= s:
                scale, suffix = s, name
                break
        scaled = v / scale
        digits = MONEY_DIGITS["ge100"] if abs(scaled) >= 100 else MONEY_DIGITS["lt100"]
        # A flow says its period: dollars a day is not dollars.
        return f"${scaled:.{digits}f}{suffix}" + ("/day" if unit_class == "MONEY_PER_DAY" else "")
    if unit_class == "MONEY_PER_SHARE":
        return f"${v:.{MONEY_PER_SHARE_DIGITS}f}"
    if unit_class == "MULTIPLE":
        return f"{v:.{MULTIPLE_DIGITS}f}×"
    if unit_class == "COUNT":
        if v.is_integer():
            return str(int(v))
        # A fraction of a day — a position that clears in 0.0001 sessions — is
        # not "0.00": below a hundredth the count keeps four places.
        return f"{v:.2f}" if abs(v) >= 0.01 else f"{v:.4f}"
    if unit_class == "COUNT_PER_DAY":
        return f"{int(round(v)):,}/day"
    return str(value)
