from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic, BaseCrossReference
from intric.database.tables.tenant_table import Tenants


class MCPServers(BasePublic):
    """Global MCP server catalog (like CompletionModels)."""
    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    server_type: Mapped[str] = mapped_column(String, nullable=False)  # "npm", "docker", "http"

    # Connection info (one of these will be set based on server_type)
    npm_package: Mapped[Optional[str]] = mapped_column(String)  # e.g., "@upstash/context7-mcp"
    uvx_package: Mapped[Optional[str]] = mapped_column(String)  # e.g., "mcp-server-time"
    docker_image: Mapped[Optional[str]] = mapped_column(String)  # e.g., "myorg/custom-mcp:latest"
    http_url: Mapped[Optional[str]] = mapped_column(String)  # e.g., "https://mcp.example.com"

    # Metadata
    config_schema: Mapped[Optional[dict]] = mapped_column(JSONB)  # JSON schema for configuration
    tags: Mapped[Optional[list]] = mapped_column(JSONB)  # ["documentation", "code-search", etc.]
    icon_url: Mapped[Optional[str]] = mapped_column(String)
    documentation_url: Mapped[Optional[str]] = mapped_column(String)


class MCPServerSettings(BaseCrossReference):
    """Tenant-level MCP server enablement and configuration (like CompletionModelSettings)."""
    __tablename__ = "mcp_server_settings"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )

    is_org_enabled: Mapped[bool] = mapped_column(server_default="False")
    env_vars: Mapped[Optional[dict]] = mapped_column(JSONB)  # Encrypted tenant credentials

    # Relationships
    mcp_server: Mapped[MCPServers] = relationship()
