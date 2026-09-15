from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    from eneo.database.tables.ai_models_table import ImageModels
    from eneo.database.tables.security_classifications_table import (
        SecurityClassification,
    )
    from eneo.database.tables.user_groups_table import UserGroups


class MCPServers(BasePublic):
    """Tenant MCP server catalog (HTTP-only)."""

    __tablename__ = "mcp_servers"  # type: ignore[assignment]
    __table_args__ = (
        # One vendor may serve several capabilities from different endpoints
        # under the same name, so names are unique per tenant and purpose.
        UniqueConstraint(
            "tenant_id",
            "name",
            "purpose",
            name="uq_mcp_servers_tenant_name_purpose",
        ),
        # A tenant may save several providers per capability purpose but only
        # one DEFAULT provider (audience = everyone) may be active at a time;
        # activation is an explicit transactional switch. Group-targeted
        # providers coexist with the default and with each other.
        # A built-in provider runs on exactly one catalog image model and
        # takes its security classification from that model, never its own.
        CheckConstraint(
            "(http_auth_type = 'internal') = (image_model_id IS NOT NULL)",
            name="ck_mcp_servers_internal_image_model",
        ),
        CheckConstraint(
            "http_auth_type <> 'internal' OR security_classification_id IS NULL",
            name="ck_mcp_servers_internal_no_classification",
        ),
        Index(
            "uq_mcp_servers_tenant_active_capability",
            "tenant_id",
            "purpose",
            unique=True,
            postgresql_where=text(
                "purpose <> 'general' AND is_enabled = true AND audience = 'everyone'"
            ),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # What this server is for: "general" (ordinary assistant tooling) or a
    # capability purpose ("web_search", "image_generation"): a tenant-wide
    # provider that spaces and assistants attach as a capability marker and
    # the ask path resolves to the currently active provider.
    purpose: Mapped[str] = mapped_column(
        String, nullable=False, server_default="general"
    )

    # HTTP configuration (uses Streamable HTTP transport - MCP 2025-03-26+ standard)
    http_url: Mapped[str] = mapped_column(String, nullable=False)
    http_auth_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default="none"
    )
    http_auth_config_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # Built-in providers (http_auth_type = "internal") only: the catalog image
    # model the loopback tool calls. RESTRICT: the model's soft delete is
    # refused while referenced, so a hard delete can never reach a live ref.
    image_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("image_models.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    image_model: Mapped[Optional["ImageModels"]] = relationship()

    # Tenant enablement and credentials
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="True", nullable=False
    )
    # Capability providers only: "everyone" is the tenant default provider,
    # "groups" serves the members of the linked user groups. Lowest
    # audience_priority wins when a user matches several group providers.
    audience: Mapped[str] = mapped_column(
        String, nullable=False, server_default="everyone"
    )
    audience_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="100"
    )
    # When true, the acting user/tenant identity is forwarded to this server as
    # X-Eneo-* headers on every request. Off by default: identity is PII egress
    # to a third party, opted into per server.
    forward_identity: Mapped[bool] = mapped_column(
        Boolean, server_default="False", nullable=False
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
    user_groups: Mapped[list["UserGroups"]] = relationship(
        secondary="mcp_server_user_groups"
    )


class MCPServerUserGroups(BaseCrossReference):
    """Audience of a group-targeted capability provider."""

    __tablename__ = "mcp_server_user_groups"  # type: ignore[assignment]

    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )
    user_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True
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
