"""MCP server — the external agent face over the ToolRegistry.

Thin: it exposes the SAME registry the in-process agent and the recipe use, so an
external host (Claude Code, OpenClaw) plays the meta-agent role under the same
budget/citation/trace enforcement. No business logic lives here.
"""
