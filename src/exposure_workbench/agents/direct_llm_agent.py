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
    usd = lambda x: f"${x:,.0f}" if x is not None else "N/A"

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


def _mock_output(inp: ReportInput) -> ReportOutput:
    """Fallback mock when LLM is unavailable."""
    pct = lambda x: f"{x * 100:.2f}%" if x is not None else "N/A"
    usd = lambda x: f"${x:,.0f}" if x is not None else "N/A"

    alert_note = ""
    if inp.alerts:
        alert_note = f" {len(inp.alerts)} risk alert(s) require attention."

    summary = (
        f"Portfolio {inp.portfolio_id} reported a daily P&L of {usd(inp.daily_pnl)} "
        f"({pct(inp.daily_return)}) on {inp.as_of_date} with total market value of "
        f"{usd(inp.portfolio_market_value)}.{alert_note}"
    )

    top_c = ", ".join(f"{c['ticker']} ({pct(c.get('contribution'))})" for c in inp.top_contributors)
    top_d = ", ".join(f"{d['ticker']} ({pct(d.get('contribution'))})" for d in inp.top_detractors)
    key_mvt = f"Top contributors: {top_c or 'N/A'}. Top detractors: {top_d or 'N/A'}."

    alert_text = ""
    if inp.alerts:
        alert_text = "; ".join(a["message"] for a in inp.alerts[:3])
    else:
        alert_text = "No risk limits breached or warned."

    md = f"""## Daily Exposure Briefing — {inp.as_of_date}

### Portfolio Summary
{summary}

### P&L Attribution
{key_mvt}

### Risk Metrics
- VaR (95%, 1-day): {pct(inp.var_95_1d)}
- 30d Volatility (annualised): {pct(inp.vol_30d)}
- Max Drawdown: {pct(inp.max_drawdown)}

### Risk Alerts
{alert_text}

*Note: This report was generated in mock mode — LLM API key not configured.*
"""

    return ReportOutput(
        executive_summary=summary,
        key_movements=key_mvt,
        factor_explanation="Factor attribution model ran successfully. Configure LLM for detailed explanation.",
        risk_alert_explanation=alert_text,
        recommended_actions="Review factor attribution and ensure LLM API key is configured for full reports.",
        markdown_report=md,
        confidence_flags={"mock_mode": True, "llm_unavailable": True},
        llm_model=None,
        prompt_tokens=None,
        completion_tokens=None,
    )


class DirectLlmAgent:
    """Generates the daily report via a single structured OpenAI call."""

    async def generate(self, inp: ReportInput) -> ReportOutput:
        client = llm_client.get_openai_client()
        if client is None:
            logger.info("LLM client unavailable — using mock report output")
            return _mock_output(inp)

        system_prompt = _load_system_prompt()
        user_message = _build_user_message(inp)

        try:
            content, model_name, prompt_tokens, completion_tokens = await llm_client.chat_complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=2048,
            )

            # Parse JSON response
            # Strip markdown code fences if present
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            data = json.loads(text)

            return ReportOutput(
                executive_summary=data.get("executive_summary", ""),
                key_movements=data.get("key_movements", ""),
                factor_explanation=data.get("factor_explanation", ""),
                risk_alert_explanation=data.get("risk_alert_explanation", ""),
                recommended_actions=data.get("recommended_actions", ""),
                markdown_report=data.get("markdown_report", ""),
                confidence_flags={"mock_mode": False},
                llm_model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        except json.JSONDecodeError as e:
            logger.warning("LLM returned non-JSON response: %s", e)
            # Fall back to using raw content as markdown_report
            return ReportOutput(
                executive_summary="Report generated — see full report for details.",
                key_movements="",
                factor_explanation="",
                risk_alert_explanation="",
                recommended_actions="",
                markdown_report=content,
                confidence_flags={"json_parse_error": True},
                llm_model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return _mock_output(inp)
