from intric.mcp_servers.domain.entities.mcp_server import MCPServerTool
from intric.mcp_servers.presentation.models import (
    MCPServerToolList,
    MCPServerToolPublic,
)


class MCPServerToolAssembler:
    """Assembler for converting MCP tool domain entities to presentation DTOs."""

    @staticmethod
    def from_domain_to_model(tool: MCPServerTool) -> MCPServerToolPublic:
        """Convert MCPServerTool domain entity to DTO."""
        return MCPServerToolPublic(
            id=tool.id,
            mcp_server_id=tool.mcp_server_id,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            is_enabled_by_default=tool.is_enabled_by_default,
            meta=tool.meta,
        )

    @staticmethod
    def to_paginated_response(tools: list[MCPServerTool]) -> MCPServerToolList:
        """Convert list of MCPServerTool entities to paginated response."""
        items = [MCPServerToolAssembler.from_domain_to_model(tool) for tool in tools]
        return MCPServerToolList(items=items)
