"""MCP Tools aggregator.

Re-exports the functions split into the ``mcp_lib`` package while keeping
backwards-compatible names for existing imports.
"""

from __future__ import annotations

from .mcp_lib import (
    _st_rerun,
    _render_wallet_section,
    _render_tool_runner,
    render_mcp_tools_page,
)

__all__ = [
    "_st_rerun",
    "_render_wallet_section",
    "_render_tool_runner",
    "render_mcp_tools_page",
]

