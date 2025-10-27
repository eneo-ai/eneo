from typing import Any, Dict, List

from intric.database.tables.mcp_server_table import MCPServerSettings as MCPServerSettingsTable
from intric.mcp_servers.domain.entities.mcp_server import MCPServerSettings
from intric.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper


class MCPServerSettingsMapper:
    """Mapper between MCPServerSettings table and MCPServerSettings domain entity."""

    @staticmethod
    def to_entity(table: MCPServerSettingsTable) -> MCPServerSettings:
        """Convert database table to domain entity."""
        return MCPServerSettings(
            tenant_id=table.tenant_id,
            mcp_server_id=table.mcp_server_id,
            created_at=table.created_at,
            updated_at=table.updated_at,
            is_org_enabled=table.is_org_enabled,
            env_vars=table.env_vars,
            mcp_server=MCPServerMapper.to_entity(table.mcp_server),
        )

    @staticmethod
    def to_entities(tables: List[MCPServerSettingsTable]) -> List[MCPServerSettings]:
        """Convert list of database tables to list of domain entities."""
        return [MCPServerSettingsMapper.to_entity(table) for table in tables]

    @staticmethod
    def to_db_dict(entity: MCPServerSettings) -> Dict[str, Any]:
        """Convert domain entity to database dict for insert/update."""
        return {
            "tenant_id": entity.tenant_id,
            "mcp_server_id": entity.mcp_server_id,
            "is_org_enabled": entity.is_org_enabled,
            "env_vars": entity.env_vars,
        }
