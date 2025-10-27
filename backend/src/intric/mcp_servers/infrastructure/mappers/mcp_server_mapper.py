from typing import Any, Dict, List

from intric.database.tables.mcp_server_table import MCPServers as MCPServersTable
from intric.mcp_servers.domain.entities.mcp_server import MCPServer


class MCPServerMapper:
    """Mapper between MCPServers table and MCPServer domain entity."""

    @staticmethod
    def to_entity(table: MCPServersTable) -> MCPServer:
        """Convert database table to domain entity."""
        return MCPServer(
            id=table.id,
            created_at=table.created_at,
            updated_at=table.updated_at,
            name=table.name,
            description=table.description,
            server_type=table.server_type,
            npm_package=table.npm_package,
            docker_image=table.docker_image,
            http_url=table.http_url,
            config_schema=table.config_schema,
            tags=table.tags,
            icon_url=table.icon_url,
            documentation_url=table.documentation_url,
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
            "name": entity.name,
            "description": entity.description,
            "server_type": entity.server_type,
            "npm_package": entity.npm_package,
            "docker_image": entity.docker_image,
            "http_url": entity.http_url,
            "config_schema": entity.config_schema,
            "tags": entity.tags,
            "icon_url": entity.icon_url,
            "documentation_url": entity.documentation_url,
        }
