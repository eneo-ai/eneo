from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.tenant_table import Tenants

if TYPE_CHECKING:
    from intric.database.tables.security_classifications_table import (
        SecurityClassification,
    )


class MCPServers(BasePublic):
    """Tenant MCP server catalog (HTTP-only).

    ``space_id`` IS NULL means a tenant-wide, admin-curated entry. A non-null
    ``space_id`` makes the entry private to that space, created via the
    space-scoped self-service endpoint. Uniqueness is enforced separately
    for each scope via partial unique indexes.
    """

    __tablename__ = "mcp_servers"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "uq_mcp_servers_tenant_name_global",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("space_id IS NULL"),
        ),
        Index(
            "uq_mcp_servers_tenant_space_name",
            "tenant_id",
            "space_id",
            "name",
            unique=True,
            postgresql_where=text("space_id IS NOT NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # HTTP configuration (uses Streamable HTTP transport - MCP 2025-03-26+ standard)
    http_url: Mapped[str] = mapped_column(String, nullable=False)
    http_auth_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default="none"
    )
    http_auth_config_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    # OAuth / token-exchange discriminator. ``static_bearer`` preserves the
    # legacy ``http_auth_config_schema`` path. ``per_user`` and ``per_tenant``
    # drive the same-IdP token-exchange broker (Phase 3); they are gated by
    # the ``MCP_OAUTH_ENABLED`` setting at the API layer until the broker ships.
    auth_scope: Mapped[str] = mapped_column(
        PgEnum(
            "per_user",
            "per_tenant",
            "static_bearer",
            name="mcp_auth_scope",
            create_type=False,
        ),
        nullable=False,
        server_default="static_bearer",
    )
    # Same-IdP assertion gate: the broker requires the user's IdP issuer and
    # the MCP server's published authorization-server issuer both equal this.
    expected_idp_issuer: Mapped[Optional[str]] = mapped_column(Text)
    # Identity used to populate the tool catalog (``MCPServerTools``). The
    # catalog describes the server's surface, not what a specific user can
    # do, so the discovery principal is decoupled from ``auth_scope``.
    tool_discovery_principal: Mapped[str] = mapped_column(
        PgEnum(
            "anonymous",
            "tenant_service_account",
            "admin_user",
            name="mcp_discovery_principal",
            create_type=False,
        ),
        nullable=False,
        server_default="anonymous",
    )
    # Strategy-target hint. Keycloak (RFC 8693) uses this as the ``resource``
    # / ``audience`` value; Entra (OBO) uses it as the target API ``scope``
    # (e.g. ``api://<mcp-app-id>/.default``).
    target_resource_or_scope: Mapped[Optional[str]] = mapped_column(Text)

    # Tenant enablement and credentials
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
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
