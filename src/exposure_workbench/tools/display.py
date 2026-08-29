"""One tool call, in the words a person watching would use (V13-S4).

The activity panel rendered `get_portfolio_snapshot`, `evaluate_formula` and
`respond`, plus `gpt-5.4-mini-2026-03-17: 1 tool call` and `8963 in / 412 out`.
All of it true, none of it addressed to the reader — every one of those is a
fact about how this system is built, and the person watching wants to know what
is being done on their question.

The phrase lives beside the tool, in its registration, because that is where
somebody adding a tool is already deciding what it is called and what it is for.
A central mapping would be a second list to keep in step with the first, and the
list that goes stale is always the one that is not where the work happens.

WHY THE ARGUMENTS ARE IN IT. "Reading a filing" is a caption; "Searching AAPL's
filings for “tariff”" is the answer to what the turn is doing. The arguments are
already recorded on the step — redacted and bounded by trace_service — so this
composes what is there rather than asking for anything new.

WHAT THIS IS NOT. Not the model's `description`, which says what a tool is FOR
and is written for the model. Two sentences, two readers; a slice of one is not
the other.
"""

from __future__ import annotations

import re
import string
from functools import lru_cache

# Placeholders a template may name. Derived, not declared: they are read out of
# the template itself and checked against the tool's own schema by
# tests/test_tool_display.py, so a phrase cannot name an argument the tool does
# not require.
_FIELDS = re.compile(r"\{([a-z_]+)\}")


def placeholders(template: str) -> set[str]:
    return set(_FIELDS.findall(template or ""))


# Fields whose VALUE is one of this system's identifiers rather than something a
# person typed. Caught by the guard the moment the first phrase was rendered:
# "Evaluating total_debt for AAPL" has a clean template and an identifier in it,
# which is the same defect one level down.
_IDENTIFIER_FIELDS = frozenset({"metric", "name", "formula", "op", "item_code", "kind"})


def _humanise(field: str, value: object) -> object:
    """A metric's caption where there is one, its own words otherwise.

    display_names is asked first because `operating_cash_flow` is "Cash from
    operations" and no amount of underscore-replacing gets there. Where it has
    nothing — a formula name, an operator — the identifier's own words are the
    right answer: `total_debt` IS "total debt", and inventing a table of formula
    captions to say so would be a second place for the same fact to live.
    """
    if field not in _IDENTIFIER_FIELDS or not isinstance(value, str):
        return value
    from exposure_workbench.analytics import display_names as dn

    # A formula name first for the fields that carry one: `debt_to_ebitda` is
    # "debt / EBITDA", and the metric table has never heard of it.
    if field in ("name", "formula"):
        formula = dn.FORMULA.get(value)
        if formula:
            return formula

    named = dn.METRIC.get(value)
    if named:
        # Captions are written sentence-case for a table heading; inside a
        # sentence they are mid-clause, so the first letter drops — except for an
        # acronym, where "eBITDA" would be worse than the problem.
        return named if named[:2].isupper() else named[0].lower() + named[1:]
    return value.replace("_", " ")


def _one_line(value: object, limit: int = 60) -> str:
    """An argument as it should read inside a sentence.

    Bounded because a step's args can carry a pasted paragraph: the sentence is
    a progress line, not a transcript, and the whole argument is on the step
    itself for anyone who needs it.
    """
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(template: str, args: dict | None, *, tool_name: str = "") -> str:
    """The phrase for one call, or a plain-English name when it cannot be built.

    A missing placeholder should be impossible — the guard requires every field a
    template names to be REQUIRED by that tool's schema, and a call missing a
    required argument is refused before it ever runs. It is handled anyway, and
    handled by dropping to the tool's name in words rather than by printing a
    half-formatted sentence: "Evaluating total debt for {ticker}" on a screen is
    worse than "Evaluate formula", because it looks like a bug in the answer
    rather than in the record.
    """
    fallback = (tool_name or "").replace("_", " ").strip().capitalize()
    if not template:
        return fallback
    values = {k: _one_line(_humanise(k, v)) for k, v in (args or {}).items() if v is not None}
    try:
        return string.Formatter().vformat(template, (), _Missing(values))
    except (KeyError, IndexError, ValueError):
        return fallback


class _Missing(dict):
    """Raises on a missing key rather than substituting a blank.

    A blank would produce "Evaluating  for AAPL", which reads as a defect in the
    product; falling all the way back to the tool's name reads as a record that
    is thinner than usual, which is what it is.
    """

    def __missing__(self, key):
        raise KeyError(key)


# ── one recorded step, as a line in the activity panel ───────────────────────


@lru_cache(maxsize=1)
def _templates() -> dict[str, str]:
    """name -> phrase, over both faces.

    Built once. The registries are pure construction — no database, no network —
    and a step list is rendered on every poll of a running turn.
    """
    from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

    out: dict[str, str] = {}
    for registry in (build_meta_registry(), build_research_registry()):
        for name, tool in registry.tools.items():
            if tool.display:
                out[name] = tool.display
    return out


def for_step(step_type: str, tool_name: str | None, status: str,
             args: dict | None) -> str | None:
    """The phrase for one recorded step, or None when the step is not an action.

    None is a decision, not an omission. Two kinds of row are recorded on the
    way past rather than because anyone chose them:

      llm_call  is what the turn COST. Nobody called it, nothing was retrieved,
                and `gpt-5.4-mini-2026-03-17: 1 tool call · 8963 in / 412 out`
                answers a question about this system's billing, not about the
                reader's. It belongs to the audit layer.

      a refusal is a call that did not happen — a spent allowance, a malformed
                argument. Rendering "Reading AAPL's revenue" for a call that
                read nothing would be the activity panel stating something
                false, and rendering the refusal's own words puts
                `turn_tool budget exhausted: 15/15` back on the screen. The
                count of them is on the turn; the rows are in the audit layer.

    So the reader's activity list is exactly the actions that happened, which is
    what "activity" means.
    """
    if step_type == "llm_call":
        return None
    if status in ("rejected", "error"):
        return None
    if not tool_name:
        return None
    return render(_templates().get(tool_name, ""), args, tool_name=tool_name)
