"""Loopback config-MCP server for conversational assistant "edit mode"."""

from intric.assistant_config_mcp.server import (
    CONFIG_PERSONA_PROMPT,
    CONFIG_SERVER_NAME,
    build_config_mcp_server,
    build_config_persona,
    config_mcp_app,
    config_mcp_lifespan,
)

__all__ = [
    "CONFIG_PERSONA_PROMPT",
    "CONFIG_SERVER_NAME",
    "build_config_mcp_server",
    "build_config_persona",
    "config_mcp_app",
    "config_mcp_lifespan",
]
