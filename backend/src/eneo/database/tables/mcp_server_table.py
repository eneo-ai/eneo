from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.tenant_table import Tenants

if TYPE_CHECKING:
    from eneo.database.tables.security_classifications_table import (
        SecurityClassification,
    )


class MCPServers(BasePublic):
    """Tenant MCP server catalog (HTTP-only)."""

    __tablename__ = "mcp_servers"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_mcp_servers_tenant_name"),
        # A tenant may save several web-search providers but only one may be
        # active at a time; activation is an explicit transactional switch.
        Index(
            "uq_mcp_servers_tenant_active_web_search",
            "tenant_id",
            unique=True,
            postgresql_where=text("purpose = 'web_search' AND is_enabled = true"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # What this server is for: "general" (ordinary assistant tooling) or
    # "web_search" (the tenant's web-search boundary, driven by the chat
    # Search toggle rather than per-assistant attachment).
    purpose: Mapped[str] = mapped_column(
        String, nullable=False, server_default="general"
    )

    # HTTP configuration (uses Streamable HTTP transport - MCP 2025-03-26+ standard)
    http_url: Mapped[str] = mapped_column(String, nullable=False)
    http_auth_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default="none"
    )
    http_auth_config_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    # Tenant enablement and credentials
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )
    # When true, the acting user/tenant identity is forwarded to this server as
    # X-Eneo-* headers on every request. Off by default: identity is PII egress
    # to a third party, opted into per server.
    forward_identity: Mapped[bool] = mapped_column(
        Boolean, server_default="False", nullable=False
    )
    identity_policy_generation: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    tool_catalog_max_count: Mapped[int] = mapped_column(
        Integer, server_default="256", nullable=False
    )
    tool_catalog_max_bytes: Mapped[int] = mapped_column(
        Integer, server_default=str(16 * 1024 * 1024), nullable=False
    )
    tool_definition_max_bytes: Mapped[int] = mapped_column(
        Integer, server_default="65536", nullable=False
    )
    env_vars: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB
    )  # Encrypted tenant credentials

    # Metadata
    tags: Mapped[Optional[list[str]]] = mapped_column(
        JSONB
    )  # ["documentation", "code-search", etc.]
    icon_url: Mapped[Optional[str]] = mapped_column(String)
    documentation_url: Mapped[Optional[str]] = mapped_column(String)

    # Security classification
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("security_classifications.id", ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional["SecurityClassification"]] = relationship()

    # Relationships
    tools: Mapped[list["MCPServerTools"]] = relationship(
        back_populates="mcp_server", cascade="all, delete-orphan"
    )


class MCPServerTools(BasePublic):
    """Tool catalog for MCP servers."""

    __tablename__ = "mcp_server_tools"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "mcp_server_id", "name", name="uq_mcp_server_tools_server_name"
        ),
    )

    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    # Admin-set display name. Overrides the remote-synced title in every UI
    # surface; never touched by tool sync.
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    input_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    is_enabled_by_default: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )

    # Pending changes for tool sync approval
    pending_description: Mapped[Optional[str]] = mapped_column(Text)
    pending_input_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    removed_from_remote: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )

    # Relationships
    mcp_server: Mapped[MCPServers] = relationship(back_populates="tools")


class MCPServerToolSettings(BaseCrossReference):
    """Tenant-level tool permissions."""

    __tablename__ = "mcp_server_tool_settings"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"), primary_key=True
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )

    # Relationships
    tool: Mapped[MCPServerTools] = relationship()


class MCPServerSettings(BaseCrossReference):
    """Tenant-level MCP server settings (org-wide configuration)."""

    __tablename__ = "mcp_server_settings"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )

    is_org_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )
    env_vars: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB
    )  # Org-level credentials

    # Relationships
    mcp_server: Mapped[MCPServers] = relationship()


class SpacesMCPServers(BaseCrossReference):
    """Space-level MCP server selection."""

    __tablename__ = "spaces_mcp_servers"  # type: ignore[assignment]

    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )


class SpacesMCPServerTools(BaseCrossReference):
    """Space-level tool permissions."""

    __tablename__ = "spaces_mcp_server_tools"  # type: ignore[assignment]

    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"), primary_key=True
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )
