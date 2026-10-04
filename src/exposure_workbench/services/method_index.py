"""The measures an analysis may ask for, as the model is told them — short.

One line per measure: its name, what it is, its unit and which comparisons it
takes. The registry (analytics/registry) is the one source; this module only
projects it for a face. The full entry — procedure, authority, when it fails —
is read on demand (`open("method:<name>")`), never pushed whole.

Three families, three comparisons:
    issuer measures (the formula registry) and filed lines   previous_ttm | previous_fy | previous_quarter
    book columns (book.weight, book.market_value)            previous_run
    price statistics                                         none
"""

from __future__ import annotations

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import registry
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS

ISSUER_COMPARES = ("previous_ttm", "previous_fy", "previous_quarter")
BOOK_COMPARES = ("previous_run",)
FILED_LINE = "filed_line"

_BY_FACE: dict[str, tuple[str, ...]] = {
    "issuer": ("formula", "filed_line", "book.column"),
    "risk": ("book.column",),
    "market": ("price",),
}


def family_of(measure: str) -> str | None:
    """formula | filed_line | book.column | price — or None for a name the desk has no measure under."""
    if measure in fm.FORMULAS:
        return "formula"
    if measure in SUPPORTED_METRICS:
        return FILED_LINE
    m = registry.METHODS.get(measure)
    if m is None:
        return None
    if m.executor == "book.column":
        return "book.column"
    if m.executor.startswith("price."):
        return "price"
    return None


def compares_for(measure: str) -> tuple[str, ...]:
    fam = family_of(measure)
    if fam in ("formula", FILED_LINE):
        return ISSUER_COMPARES
    if fam == "book.column":
        return BOOK_COMPARES
    return ()


def measures_for(face: str | None) -> list[str]:
    """Every measure `analyze` accepts on a face; None is the lead's: all of them."""
    families = set(f for fs in _BY_FACE.values() for f in fs) if face is None else set(_BY_FACE[face])
    names: list[str] = []
    if "formula" in families:
        names += [n for n in fm.FORMULAS]
    if "book.column" in families:
        names += [m.name for m in registry.METHODS.values() if m.executor == "book.column"]
    if "price" in families:
        names += [m.name for m in registry.METHODS.values() if m.executor.startswith("price.")]
    if FILED_LINE in families:
        names += sorted(SUPPORTED_METRICS)
    return list(dict.fromkeys(names))


def _unit_word(measure: str) -> str:
    fam = family_of(measure)
    if fam == "formula":
        return fm.FORMULAS[measure].unit_class
    if fam == FILED_LINE:
        return "as filed"
    m = registry.METHODS.get(measure)
    return (m.unit_class or "") if m else ""


def line(measure: str) -> str:
    fam = family_of(measure)
    if fam == "formula":
        f = fm.FORMULAS[measure]
        what = f.expression
    elif fam == FILED_LINE:
        what = "a filed line, as filed"
    else:
        m = registry.METHODS[measure]
        what = m.describes
    compares = compares_for(measure)
    return (f"{measure} — {what}" + (f" [{_unit_word(measure)}]" if _unit_word(measure) else "")
            + (f"; compare: {' | '.join(compares)}" if compares else "; no comparison"))


def index_text(face: str | None) -> str:
    """The catalogue a role reads: formulas and book columns one line each; the
    filed lines named as a family (there are many, and `list(what='fundamentals')`
    says which an issuer files)."""
    names = [n for n in measures_for(face) if family_of(n) != FILED_LINE]
    out = ["MEASURES `analyze` TAKES (by name; the full entry opens with open(\"method:<name>\"))"]
    out += [line(n) for n in names]
    if FILED_LINE in (set(f for fs in _BY_FACE.values() for f in fs) if face is None else set(_BY_FACE[face])):
        out.append("any filed line by its name (operating_cash_flow, net_income, total_debt, …) — the line as the issuer "
                   "filed it, a flow over the window or a balance at its end; compare: " + " | ".join(ISSUER_COMPARES))
    return "\n".join(out)


def detail(measure: str) -> dict:
    """The whole entry, for `open("method:<name>")`."""
    fam = family_of(measure)
    if fam is None:
        return {"error": "unknown_method", "detail": f"{measure} is not a measure this desk has",
                "nearest": registry.nearest(measure)}
    if fam == FILED_LINE:
        return {"measure": measure, "family": fam, "describes": "a filed line, as the issuer filed it",
                "compare": list(ISSUER_COMPARES)}
    m = registry.METHODS[measure]
    out = {"measure": measure, "family": fam, "reads_as": m.reads_as, "describes": m.describes,
           "procedure": m.procedure, "authority": m.authority, "fails_when": m.fails_when,
           "unit": m.unit_class, "compare": list(compares_for(measure))}
    if fam == "formula":
        f = fm.FORMULAS[measure]
        out.update({"expression": f.expression, "inputs": list(f.inputs), "note": f.note,
                    "not_for_financials": f.not_for_financials,
                    "denominator_must_be_positive": f.denominator_must_be_positive or None})
    return out
