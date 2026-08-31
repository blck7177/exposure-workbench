"""The report input honours the collinearity rule the gate enforces (V13 post-④).

Found by the first two scheduled/manual runs both losing their briefing: the
prompt said "focus on the top 2-3 factors by contribution magnitude", the input
handed the model five per-factor betas and contributions, the model quoted them
— and the gate refused every one, correctly, because under VIF 18 no single
coefficient is determined (V11-F). The system was at war with itself: one door
instructing what another door forbids, every morning.

The fix is structural, not a longer instruction: when the regression is
collinear the per-factor FIGURES never enter the model's context — direction
and rank do, which is what a sentence like "the market factor dominated the
day's fall" needs. A number the model never saw is a number it cannot quote,
which is how this codebase prefers to remove an error class.
"""

from __future__ import annotations

import re
from pathlib import Path

from exposure_workbench.agents.direct_llm_agent import _build_user_message
from exposure_workbench.agents.schemas import ReportInput

ROOT = Path(__file__).resolve().parents[1]

_FACTORS = [
    {"factor_name": "market", "beta": 1.1777, "factor_return": -0.0039, "contribution": -0.0047},
    {"factor_name": "small_cap", "beta": -0.1966, "factor_return": -0.0134, "contribution": 0.0026},
    {"factor_name": "growth", "beta": -0.1809, "factor_return": -0.0072, "contribution": 0.0013},
]


def _inp(collinear: bool) -> ReportInput:
    return ReportInput(
        portfolio_id="port_x", as_of_date="2026-08-31",
        portfolio_market_value=1_000_000.0, daily_pnl=-1000.0, daily_return=-0.001,
        factor_attributions=list(_FACTORS), factors_collinear=collinear,
    )


def _factor_block(msg: str) -> str:
    start = msg.index("Factor Attribution")
    end = msg.index("###", start + 1) if "###" in msg[start + 1:] else len(msg)
    return msg[start:end]


def test_a_collinear_regression_sends_no_per_factor_figures():
    block = _factor_block(_build_user_message(_inp(collinear=True)))
    assert not re.search(r"\d+\.\d+%", block), (
        f"a per-factor percentage reached the model's context under collinearity:\n{block}"
    )
    assert "β=" not in block and "beta" not in block.lower().replace("betas are collinear", ""), (
        f"a lone beta reached the model's context under collinearity:\n{block}"
    )
    # Direction and rank survive — that is what the prose needs.
    assert "market" in block and "small_cap" in block
    assert "negative" in block and "positive" in block


def test_the_collinear_block_says_why_and_ranks_by_magnitude():
    block = _factor_block(_build_user_message(_inp(collinear=True)))
    assert "collinear" in block.lower()
    # market (|-0.47%|) outranks small_cap (|0.26%|) outranks growth.
    assert block.index("market") < block.index("small_cap") < block.index("growth")


def test_a_determined_regression_still_sends_the_figures():
    block = _factor_block(_build_user_message(_inp(collinear=False)))
    assert "β=1.18" in block and "-0.47%" in block


def test_the_refusal_message_names_the_real_reason():
    """The workflow flattened every problem to `nearest.label` with a
    'nothing comparable' default — so a figure refused as NOT INDIVIDUALLY
    DETERMINED (which has no `nearest`) read as if the run held nothing like
    it. That wording sent this investigation down the wrong road for an hour,
    which is exactly the cost a wrong error message exists to charge."""
    src = (ROOT / "src" / "exposure_workbench" / "workflow" / "exposure_workflow.py").read_text()
    block = src[src.index("class ReportUnavailable") if "class ReportUnavailable" in src
                else src.index("ReportUnavailable("):]
    assert "_describe_problem" in src, (
        "the refusal message must render per-reason; a nearest-label flatten "
        "mislabels not_quotable_individually as 'nothing comparable'"
    )
    from exposure_workbench.workflow.exposure_workflow import _describe_problem
    quotable = _describe_problem({"number": "-0.47%", "reason": "not_quotable_individually",
                                  "detail": "collinear factors", "matched": ["factor_attributions.market.contribution"]})
    assert "not individually" in quotable and "market" in quotable
    assert "nothing comparable" not in quotable
    absent = _describe_problem({"number": "9.99%", "reason": "not_in_cited_evidence", "nearest": None})
    assert "nothing comparable" in absent
