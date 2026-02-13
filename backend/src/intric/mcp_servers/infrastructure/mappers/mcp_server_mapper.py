from typing import TYPE_CHECKING, Any, Dict, List, Sequence

from sqlalchemy import inspect
from sqlalchemy.orm.base import NEVER_SET

from intric.database.tables.mcp_server_table import MCPServers as MCPServersTable
from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool

if TYPE_CHECKING:
    from intric.database.tables.mcp_server_table import (
        MCPServerTools as MCPServerToolsTable,
    )


class MCPServerToolMapper:
    """Mapper between MCPServerTools table and MCPServerTool domain entity."""

    @staticmethod
    def to_entity(db_model: "MCPServerToolsTable") -> MCPServerTool:
        """Convert database table to domain entity."""

        return MCPServerTool(
            id=db_model.id,  # type: ignore[arg-type]
            created_at=db_model.created_at,  # type: ignore[arg-type]
            updated_at=db_model.updated_at,  # type: ignore[arg-type]
            mcp_server_id=db_model.mcp_server_id,
            name=db_model.name,
            description=db_model.description,
            input_schema=db_model.input_schema,
            is_enabled_by_default=db_model.is_enabled_by_default,
            meta=db_model.meta,
        )

    @staticmethod
    def to_entities(db_models: Sequence["MCPServerToolsTable"]) -> List[MCPServerTool]:
        """Convert list of database tables to list of domain entities."""
        return [MCPServerToolMapper.to_entity(db_model) for db_model in db_models]

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
            "meta": entity.meta,
        }


class MCPServerMapper:
    """Mapper between MCPServers table and MCPServer domain entity."""

    @staticmethod
    def to_entity(db_model: MCPServersTable) -> MCPServer:
        """Convert database table to domain entity."""
        tools: List[MCPServerTool] = []
        # Check if tools relationship is loaded without triggering lazy load
        inspector = inspect(db_model)
        if inspector is not None:
            tools_loaded = inspector.attrs.tools.loaded_value
            if tools_loaded is not NEVER_SET and tools_loaded:
                tools = MCPServerToolMapper.to_entities(tools_loaded)

        return MCPServer(
            id=db_model.id,  # type: ignore[arg-type]
            created_at=db_model.created_at,  # type: ignore[arg-type]
            updated_at=db_model.updated_at,  # type: ignore[arg-type]
            tenant_id=db_model.tenant_id,
            name=db_model.name,
            description=db_model.description,
            http_url=db_model.http_url,
            http_auth_type=db_model.http_auth_type,
            http_auth_config_schema=db_model.http_auth_config_schema,
            is_enabled=db_model.is_enabled,
            env_vars=db_model.env_vars,
            tags=db_model.tags,
            icon_url=db_model.icon_url,
            documentation_url=db_model.documentation_url,
            tools=tools,
        )

    @staticmethod
    def to_entities(db_models: Sequence[MCPServersTable]) -> List[MCPServer]:
        """Convert list of database tables to list of domain entities."""
        return [MCPServerMapper.to_entity(db_model) for db_model in db_models]

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
