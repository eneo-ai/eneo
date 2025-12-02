from typing import Any, Dict, List

from sqlalchemy import inspect
from sqlalchemy.orm.attributes import NEVER_SET

from intric.database.tables.mcp_server_table import MCPServers as MCPServersTable
from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


class MCPServerToolMapper:
    """Mapper between MCPServerTools table and MCPServerTool domain entity."""

    @staticmethod
    def to_entity(table) -> MCPServerTool:
        """Convert database table to domain entity."""

        return MCPServerTool(
            id=table.id,
            created_at=table.created_at,
            updated_at=table.updated_at,
            mcp_server_id=table.mcp_server_id,
            name=table.name,
            description=table.description,
            input_schema=table.input_schema,
            is_enabled_by_default=table.is_enabled_by_default,
        )

    @staticmethod
    def to_entities(tables: list) -> List[MCPServerTool]:
        """Convert list of database tables to list of domain entities."""
        return [MCPServerToolMapper.to_entity(table) for table in tables]

    @staticmethod
    def to_db_dict(entity: MCPServerTool) -> Dict[str, Any]:
        """Convert domain entity to database dict for insert/update."""
        return {
            "id": entity.id,
            "mcp_server_id": entity.mcp_server_id,
            "name": entity.name,
            "description": entity.description,
            "input_schema": entity.input_schema,
            "is_enabled_by_default": entity.is_enabled_by_default,
        }


class MCPServerMapper:
    """Mapper between MCPServers table and MCPServer domain entity."""

    @staticmethod
    def to_entity(table: MCPServersTable) -> MCPServer:
        """Convert database table to domain entity."""
        tools = []
        # Check if tools relationship is loaded without triggering lazy load
        inspector = inspect(table)
        tools_loaded = inspector.attrs.tools.loaded_value
        if tools_loaded is not NEVER_SET and tools_loaded:
            tools = MCPServerToolMapper.to_entities(tools_loaded)

        return MCPServer(
            id=table.id,
            created_at=table.created_at,
            updated_at=table.updated_at,
            tenant_id=table.tenant_id,
            name=table.name,
            description=table.description,
            http_url=table.http_url,
            http_auth_type=table.http_auth_type,
            http_auth_config_schema=table.http_auth_config_schema,
            is_enabled=table.is_enabled,
            env_vars=table.env_vars,
            tags=table.tags,
            icon_url=table.icon_url,
            documentation_url=table.documentation_url,
            tools=tools,
        )

    @staticmethod
    def to_entities(tables: List[MCPServersTable]) -> List[MCPServer]:
        """Convert list of database tables to list of domain entities."""
        return [MCPServerMapper.to_entity(table) for table in tables]

    @staticmethod
    def to_db_dict(entity: MCPServer) -> Dict[str, Any]:
        """Convert domain entity to database dict for insert/update."""
        return {
            "id": entity.id,
            "tenant_id": entity.tenant_id,
            "name": entity.name,
            "description": entity.description,
            "http_url": entity.http_url,
            "http_auth_type": entity.http_auth_type,
            "http_auth_config_schema": entity.http_auth_config_schema,
            "is_enabled": entity.is_enabled,
            "env_vars": entity.env_vars,
            "tags": entity.tags,
            "icon_url": entity.icon_url,
            "documentation_url": entity.documentation_url,
        }
