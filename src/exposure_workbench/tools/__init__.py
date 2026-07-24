"""Tool layer — the ONLY interface between the agent world and deterministic code.

One tool definition, four consumers (meta-agent, research subagent, MCP host,
recipe). Budget/validation/trace enforcement lives in the wrapper, so it is
written once and no transport can bypass it.
"""
