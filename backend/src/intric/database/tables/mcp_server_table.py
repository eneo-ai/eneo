from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic, BaseCrossReference
from intric.database.tables.tenant_table import Tenants


class MCPServers(BasePublic):
    """Tenant MCP server catalog (HTTP-only)."""
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='uq_mcp_servers_tenant_name'),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # HTTP configuration (uses Streamable HTTP transport - MCP 2025-03-26+ standard)
    http_url: Mapped[str] = mapped_column(String, nullable=False)
    http_auth_type: Mapped[str] = mapped_column(String, nullable=False, server_default='none')
    http_auth_config_schema: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Tenant enablement and credentials
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default='True', nullable=False)
    env_vars: Mapped[Optional[dict]] = mapped_column(JSONB)  # Encrypted tenant credentials

    # Metadata
    tags: Mapped[Optional[list]] = mapped_column(JSONB)  # ["documentation", "code-search", etc.]
    icon_url: Mapped[Optional[str]] = mapped_column(String)
    documentation_url: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    tools: Mapped[list["MCPServerTools"]] = relationship(
        back_populates="mcp_server",
        cascade="all, delete-orphan"
    )


class MCPServerTools(BasePublic):
    """Tool catalog for MCP servers."""
    __tablename__ = "mcp_server_tools"
    __table_args__ = (
        UniqueConstraint('mcp_server_id', 'name', name='uq_mcp_server_tools_server_name'),
    )

    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    input_schema: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_enabled_by_default: Mapped[bool] = mapped_column(Boolean, server_default="True", nullable=False)

    # Relationships
    mcp_server: Mapped[MCPServers] = relationship(back_populates="tools")


class MCPServerToolSettings(BaseCrossReference):
    """Tenant-level tool permissions."""
    __tablename__ = "mcp_server_tool_settings"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"), primary_key=True
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default="True", nullable=False)

    # Relationships
    tool: Mapped[MCPServerTools] = relationship()


class SpacesMCPServers(BaseCrossReference):
    """Space-level MCP server selection."""
    __tablename__ = "spaces_mcp_servers"

    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )


class SpacesMCPServerTools(BaseCrossReference):
    """Space-level tool permissions."""
    __tablename__ = "spaces_mcp_server_tools"

    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"), primary_key=True
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default="True", nullable=False)
