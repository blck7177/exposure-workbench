"""Report agent facade — routes to direct_llm or langgraph based on REPORT_AGENT_MODE."""

from __future__ import annotations

import logging

from exposure_workbench.agents.schemas import ReportInput, ReportOutput

logger = logging.getLogger(__name__)


class ReportAgent:
    """Unified interface for report generation regardless of backend."""

    def __init__(self, mode: str = "direct_llm"):
        self.mode = mode
        self._agent = None

    def _get_agent(self):
        if self._agent is not None:
            return self._agent
        if self.mode == "direct_llm":
            from exposure_workbench.agents.direct_llm_agent import DirectLlmAgent
            self._agent = DirectLlmAgent()
        else:
            logger.warning("Unknown REPORT_AGENT_MODE=%s, falling back to direct_llm", self.mode)
            from exposure_workbench.agents.direct_llm_agent import DirectLlmAgent
            self._agent = DirectLlmAgent()
        return self._agent

    async def generate(self, inp: ReportInput) -> ReportOutput:
        agent = self._get_agent()
        return await agent.generate(inp)


_report_agent: ReportAgent | None = None


def get_report_agent() -> ReportAgent:
    global _report_agent
    if _report_agent is None:
        from exposure_workbench.app_state.settings import get_settings
        settings = get_settings()
        _report_agent = ReportAgent(mode=settings.report_agent_mode)
    return _report_agent
