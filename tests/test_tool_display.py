"""V13-S4 — every tool can say what one call of it is doing (offline).

The activity panel showed `get_portfolio_snapshot`, `evaluate_formula`, `respond`
and `gpt-5.4-mini-2026-03-17: 1 tool call · 8963 in / 412 out`. Every line true,
none of it addressed to the person watching their own question being worked on.

Two guards, and the second is the one that keeps the first from being decorative:
every registered tool has a phrase, and every argument a phrase names is one the
tool actually REQUIRES. A template naming an optional argument renders a
half-finished sentence on exactly the calls that omit it — the failure would be
intermittent, invisible in review, and would look like a bug in the answer.

Both sets are derived from the registries, so a tool added tomorrow is covered by
these tests without anybody remembering they exist.
"""

from __future__ import annotations

import pytest

from exposure_workbench.tools.display import placeholders, render
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def _all_tools() -> dict:
    tools = dict(build_meta_registry().tools)
    tools.update(build_research_registry().tools)
    return tools


TOOLS = _all_tools()


def test_there_are_tools_to_check():
    """The guard's own liveness. A registry that failed to build would make
    every test below pass over an empty dict."""
    assert len(TOOLS) >= 30, f"only {len(TOOLS)} tools resolved — the registries did not build"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_every_tool_has_a_phrase(name):
    tool = TOOLS[name]
    assert tool.display.strip(), (
        f"{name} has no display phrase, so a person watching the turn sees "
        f"`{name}` — which is correct and is not English."
    )


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_a_phrase_only_names_arguments_the_tool_requires(name):
    """The load-bearing one.

    A phrase naming an OPTIONAL argument renders "Reading AAPL's  over the
    periods it reports" on the calls that leave it out. Required arguments are
    guaranteed present: arg_validation refuses a call missing one before it runs.
    """
    tool = TOOLS[name]
    required = set((tool.json_schema or {}).get("required", []))
    named = placeholders(tool.display)
    unmet = sorted(named - required)
    assert unmet == [], (
        f"{name}'s phrase names {unmet}, which the schema does not require. "
        f"Required: {sorted(required)}. Either the phrase should not depend on "
        f"it, or the argument should be required."
    )


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_a_phrase_is_a_sentence_about_the_work_not_the_machinery(name):
    """No tool names, no ids, no snake_case leaking through.

    The whole reason the panel needed changing was that it printed identifiers;
    a phrase that embeds one has changed nothing.
    """
    display = TOOLS[name].display
    assert name not in display, f"{name}'s phrase names the tool itself"
    literal = display
    for field in placeholders(display):
        literal = literal.replace("{" + field + "}", "")
    assert "_" not in literal, (
        f"{name}'s phrase carries an underscore outside a placeholder: {display!r}"
    )


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_every_phrase_renders_from_a_call_that_satisfies_its_schema(name):
    """Rendered, not just inspected: a template with a stray brace type-checks
    fine and throws at the moment somebody is watching a turn."""
    tool = TOOLS[name]
    args = {field: "X" for field in placeholders(tool.display)}
    out = render(tool.display, args, tool_name=name)
    assert out and "{" not in out and "}" not in out, f"{name} rendered {out!r}"


def test_a_real_call_reads_as_a_sentence():
    tool = TOOLS["evaluate_formula"]
    assert render(tool.display, {"name": "total_debt", "ticker": "AAPL"},
                  tool_name="evaluate_formula") == "Evaluating total debt for AAPL"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_a_rendered_call_humanises_the_fields_that_carry_identifiers(name):
    """The template being clean is not enough — some VALUES are identifiers too.

    Found the moment the first phrase was rendered: `evaluate_formula(name=
    "total_debt")` produced "Evaluating total_debt for AAPL". A clean template
    with an identifier substituted into it is the same defect one level down,
    and it is the level a reader sees.

    Only the fields that carry this system's own names are checked. A `{query}`
    or a `{reason}` is the user's words or the model's, and passing those
    through a humaniser would be editing somebody's text to look tidy — a search
    for `free_cash_flow` must render as what was searched for.
    """
    from exposure_workbench.tools.display import _IDENTIFIER_FIELDS

    tool = TOOLS[name]
    fields = placeholders(tool.display)
    identifier_fields = fields & _IDENTIFIER_FIELDS
    if not identifier_fields:
        pytest.skip(f"{name}'s phrase names no identifier-valued field")
    args = {f: ("operating_cash_flow" if f in identifier_fields else "AAPL") for f in fields}
    out = render(tool.display, args, tool_name=name)
    assert "operating_cash_flow" not in out, f"{name} rendered an identifier: {out!r}"
    assert "cash from operations" in out, out


def test_a_users_own_words_are_not_tidied_up():
    """A query is what was searched for, underscores and all."""
    assert render("Searching {ticker}'s filings for “{query}”",
                  {"ticker": "AAPL", "query": "free_cash_flow covenant"}) \
        == "Searching AAPL's filings for “free_cash_flow covenant”"


def test_a_metric_argument_reads_as_the_desk_says_it():
    """Not underscore-replacement: `operating_cash_flow` is "cash from
    operations", and only the caption table knows that."""
    assert render("Reading {ticker}'s {metric}", {"ticker": "AAPL", "metric": "operating_cash_flow"}) \
        == "Reading AAPL's cash from operations"
    # a name with no caption keeps its own words, which are already English
    assert render("Evaluating {name}", {"name": "total_debt"}) == "Evaluating total debt"


def test_a_long_argument_is_bounded_rather_than_pasted():
    """A step's args can carry a pasted paragraph. The progress line is a line."""
    out = render("Searching {ticker}'s filings for “{query}”",
                 {"ticker": "AAPL", "query": "tariff " * 40}, tool_name="search_filing_passages")
    assert len(out) < 140 and out.endswith("”")


def test_a_record_missing_an_argument_falls_back_to_words_not_to_a_broken_sentence():
    """Should be unreachable — a call missing a required argument is refused
    before it runs — and is handled anyway, because "Evaluating total debt for
    {ticker}" on a screen reads as a defect in the answer rather than in the
    record.
    """
    assert render("Evaluating {name} for {ticker}", {"name": "total_debt"},
                  tool_name="evaluate_formula") == "Evaluate formula"
    assert render("", {}, tool_name="get_flow") == "Get flow"


def test_arguments_that_are_null_are_treated_as_absent():
    """Optional arguments arrive as an explicit null about as often as they are
    omitted (the V13-era lesson in start_exposure_run's own schema comment)."""
    assert render("Reading {ticker}", {"ticker": None}, tool_name="get_flow") == "Get flow"
