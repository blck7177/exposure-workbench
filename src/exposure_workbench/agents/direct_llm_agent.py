"""Direct LLM agent — single OpenAI call to generate the daily exposure report."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from exposure_workbench.agents.schemas import ReportInput, ReportOutput
from exposure_workbench.llm import client as llm_client

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "daily_exposure_report.md"


def _load_system_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text()
    return "You are a portfolio risk analyst. Generate a daily exposure briefing as JSON."


def _build_user_message(inp: ReportInput) -> str:
    pct = lambda x: f"{x * 100:.2f}%" if x is not None else "N/A"
    # The sign goes OUTSIDE the currency mark. The report model is told to copy
    # figures exactly, so a plain f"${x:,.0f}" put "$-141,973" in front of it and
    # "down $-141,973" in the published briefing. ASCII "-$", not U+2212: this
    # string passes through the verification gate, and "-$141,973" is the form it
    # parses as negative MONEY.
    usd = lambda x: ("-$" if x < 0 else "$") + f"{abs(x):,.0f}" if x is not None else "N/A"

    lines = [
        f"## Portfolio Risk Data — {inp.as_of_date}",
        f"",
        f"**Portfolio:** {inp.portfolio_id}",
        f"**Market Value:** {usd(inp.portfolio_market_value)}",
        f"**Daily P&L:** {usd(inp.daily_pnl)} ({pct(inp.daily_return)})",
        f"",
        "### Top Contributors",
    ]
    for c in inp.top_contributors:
        lines.append(f"- {c['ticker']}: {pct(c.get('contribution'))} contribution ({pct(c.get('daily_return'))} return)")

    lines.append("\n### Top Detractors")
    for d in inp.top_detractors:
        lines.append(f"- {d['ticker']}: {pct(d.get('contribution'))} contribution ({pct(d.get('daily_return'))} return)")

    lines.append("\n### Sector Exposures")
    for sector, weight in sorted(inp.sector_exposures.items(), key=lambda x: -x[1]):
        lines.append(f"- {sector}: {pct(weight)}")

    lines.append("\n### Risk Metrics")
    lines.append(f"- 1-day 95% VaR: {pct(inp.var_95_1d)}")
    lines.append(f"- 30d Annualised Vol: {pct(inp.vol_30d)}")
    lines.append(f"- Max Drawdown: {pct(inp.max_drawdown)}")

    if inp.factor_attributions:
        if inp.factors_collinear:
            # No per-factor figures, on purpose. Under collinearity no single
            # beta or contribution is individually determined, and the gate
            # refuses each one quoted alone (V11-F) — which it did, correctly,
            # to the first two runs' drafts, costing both their briefing. The
            # prose needs direction and rank, so that is all the model is given;
            # a figure that never enters the context cannot be written.
            vif = f" (max VIF {inp.factors_max_vif:.0f})" if inp.factors_max_vif else ""
            lines.append(
                "\n### Factor Attribution (direction and rank only — the factors are "
                f"collinear{vif}, so no single factor's figure is individually "
                "determined and none is supplied; describe influence in words)")
            # Rank words, not rank NUMERALS: "#2" in the context came straight
            # back as a bare "2" in the draft, which the gate then had to judge
            # as a figure. The same rule as the contributions themselves — a
            # digit the model never saw is a digit it cannot echo.
            _RANK = ("largest", "second", "third", "fourth", "fifth")
            ranked = sorted(inp.factor_attributions[:5],
                            key=lambda fa: abs(fa.get("contribution") or 0.0), reverse=True)
            for i, fa in enumerate(ranked):
                sign = "negative" if (fa.get("contribution") or 0.0) < 0 else "positive"
                lines.append(f"- {fa['factor_name']}: {sign} contribution ({_RANK[i]} by size)")
        else:
            lines.append("\n### Factor Attribution (top 5)")
            for fa in inp.factor_attributions[:5]:
                lines.append(
                    f"- {fa['factor_name']} (β={fa['beta']:.2f}): "
                    f"factor return {pct(fa.get('factor_return'))}, "
                    f"contribution {pct(fa.get('contribution'))}"
                )

    if inp.stress_scenarios:
        lines.append("\n### Stress Scenarios")
        for s in inp.stress_scenarios:
            lines.append(f"- {s['name']}: estimated loss {pct(s.get('loss_pct'))}")

    if inp.alerts:
        lines.append("\n### Risk Alerts")
        for a in inp.alerts:
            lines.append(f"- [{a['severity'].upper()}] {a['message']}")
    else:
        lines.append("\n### Risk Alerts\nNo alerts triggered.")

    lines.append(f"\nAudience: {inp.audience}")
    lines.append("\nPlease generate the JSON report as specified in the system prompt.")

    return "\n".join(lines)


class ReportUnavailable(RuntimeError):
    """The report could not be produced, with a reason a person can read.

    Every branch that used to end in a fabricated report ends here instead. The
    three it replaces were not equally bad, they were bad in the same way: each
    returned something shaped exactly like a report, and the caller persisted it
    because a caller cannot tell the difference between "here is the report" and
    "here is what I made up when I could not produce one".

    Measured on the live database before this existed: 9 of 19 stored reports
    were the mock template, and its own disclaimer read "LLM API key not
    configured" — which was true for none of them. The key was configured; the
    model had returned something the parser did not expect, and the bare
    `except Exception` reported that as a missing key.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# recommended_actions left this set in V13-S7: the prompt stopped asking for
# trade suggestions — "Consider trimming LLY" is a verdict, and the desk's rule
# is that verdicts are the reader's (the same sentence _SYSTEM applies to the
# analyst). The column stays on daily_reports for the reports that were written
# under the old prompt; new rows record NULL, which reads as "not produced".
_REQUIRED_FIELDS = (
    "executive_summary", "key_movements", "factor_explanation",
    "risk_alert_explanation", "markdown_report",
)


class DirectLlmAgent:
    """Generates the daily report via a single structured OpenAI call."""

    async def generate(self, inp: ReportInput) -> ReportOutput:
        client = llm_client.get_openai_client()
        if client is None:
            raise ReportUnavailable("no LLM client is configured")

        system_prompt = _load_system_prompt()
        user_message = _build_user_message(inp)

        try:
            content, model_name, prompt_tokens, completion_tokens = await llm_client.chat_complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=2048,
            )
        except Exception as e:
            raise ReportUnavailable(f"the LLM call failed: {e}") from e

        # Strip markdown code fences if present
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ReportUnavailable(f"the model did not return JSON: {e}") from e
        if not isinstance(data, dict):
            # Valid JSON that is a list, a string or null. This used to reach
            # `data.get`, raise AttributeError, and land in the bare except that
            # blamed a missing API key.
            raise ReportUnavailable(
                f"the model returned JSON that is not an object ({type(data).__name__})"
            )

        # Every field is required and non-empty. `.get(k, "")` accepted a report
        # missing five of its six sections and flagged it clean.
        missing = [k for k in _REQUIRED_FIELDS if not str(data.get(k) or "").strip()]
        if missing:
            raise ReportUnavailable(f"the report is missing: {', '.join(missing)}")

        return ReportOutput(
            executive_summary=data["executive_summary"],
            key_movements=data["key_movements"],
            factor_explanation=data["factor_explanation"],
            risk_alert_explanation=data["risk_alert_explanation"],
            markdown_report=data["markdown_report"],
            confidence_flags={},
            llm_model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
