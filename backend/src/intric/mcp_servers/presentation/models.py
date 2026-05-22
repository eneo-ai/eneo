from typing import Any, Generic, Literal, Optional, TypeVar, Union
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, computed_field

from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)

T = TypeVar("T", bound=BaseModel)


class BaseListModel(BaseModel, Generic[T]):
    items: list[T]

    @computed_field
    def count(self) -> int:
        return len(self.items)


MCPAuthScopeLiteral = Literal["per_user", "per_tenant", "static_bearer"]


class MCPServerPublic(BaseModel):
    """Public DTO for MCP server (HTTP-only, uses Streamable HTTP transport).

    ``space_id`` is non-null when the server is space-private (created via
    the self-service / knowledge-source flow) and null for the tenant-wide
    admin-curated catalog. Frontends use this to group the assistant
    picker (no other behavioural branching depends on it).
    """

    id: UUID
    space_id: Optional[UUID] = None
    name: str
    description: Optional[str]
    http_url: str
    http_auth_type: str  # "none", "bearer"
    has_credentials: bool
    credential_preview: Optional[str] = None  # masked token, e.g. "••••••••sk12"
    tags: Optional[list[str]]
    icon_url: Optional[str]
    documentation_url: Optional[str]
    security_classification: Optional[SecurityClassificationPublic] = None
    auth_scope: MCPAuthScopeLiteral = "static_bearer"
    expected_idp_issuer: Optional[str] = None
    target_resource_or_scope: Optional[str] = None


class MCPServerList(BaseListModel[MCPServerPublic]):
    pass


class MCPServerCreate(BaseModel):
    """DTO for creating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: str
    http_url: AnyHttpUrl
    http_auth_type: Literal["none", "bearer"] = "none"
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None
    security_classification: Optional[ModelId] = None
    auth_scope: MCPAuthScopeLiteral = "static_bearer"
    expected_idp_issuer: Optional[str] = None
    target_resource_or_scope: Optional[str] = None


class MCPServerUpdate(BaseModel):
    """DTO for updating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: Optional[str] = None
    http_url: Optional[AnyHttpUrl] = None
    http_auth_type: Optional[Literal["none", "bearer"]] = None
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED
    auth_scope: Optional[MCPAuthScopeLiteral] = None
    expected_idp_issuer: Union[str, None, NotProvided] = NOT_PROVIDED
    target_resource_or_scope: Union[str, None, NotProvided] = NOT_PROVIDED


class MCPServerSettingsPublic(MCPServerPublic):
    """DTO for MCP server with tenant settings."""

    mcp_server_id: UUID  # ID in global catalog
    is_org_enabled: bool
    tools: list["MCPServerToolPublic"] = []

    @computed_field
    def tools_count(self) -> int:
        """Number of tools available on this server."""
        return len(self.tools)

    @computed_field
    def is_available(self) -> bool:
        """Whether this MCP is enabled and available for use."""
        return self.is_org_enabled


class MCPServerSettingsList(BaseListModel[MCPServerSettingsPublic]):
    pass


class MCPServerSettingsCreate(BaseModel):
    """DTO for enabling an MCP server for tenant."""

    env_vars: Optional[dict[str, Any]] = None  # Credentials/tokens for this MCP


class MCPServerSettingsUpdate(BaseModel):
    """DTO for updating MCP server settings."""

    is_org_enabled: Optional[bool] = None
    env_vars: Optional[dict[str, Any]] = None


class AssistantMCPServerPublic(BaseModel):
    """DTO for assistant's MCP server association."""

    mcp_server_id: UUID
    mcp_server_name: str
    enabled: bool
    config: Optional[dict[str, Any]]
    priority: int


class AssistantMCPServerUpdate(BaseModel):
    """DTO for updating assistant MCP association."""

    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None
    priority: Optional[int] = None


class MCPServerToolPublic(BaseModel):
    """DTO for MCP server tool."""

    id: UUID
    mcp_server_id: UUID
    name: str
    description: Optional[str]
    input_schema: Optional[dict[str, Any]]
    is_enabled_by_default: bool
    pending_description: Optional[str] = None
    pending_input_schema: Optional[dict[str, Any]] = None
    requires_approval: bool = False
    removed_from_remote: bool = False


class MCPServerToolList(BaseListModel[MCPServerToolPublic]):
    pass


class MCPServiceAccountPublic(BaseModel):
    """DTO for the tenant MCP service-account read-out (masked).

    Also surfaces the tenant-wide default audience/scope so the panel
    can render both knobs from a single GET; they are written via
    separate PUT endpoints because the concerns are independent.
    """

    configured: bool
    client_id: Optional[str] = None
    client_secret_preview: Optional[str] = None  # e.g. "********4f3c"
    default_target: Optional[str] = None


class MCPServiceAccountUpdate(BaseModel):
    """DTO for setting / rotating the tenant MCP service-account credentials."""

    client_id: str
    client_secret: str


class MCPSsoDefaultTargetUpdate(BaseModel):
    """DTO for setting the tenant-wide default audience/scope.

    Used as the fallback ``target.resource_or_scope`` in the broker for
    every SSO MCP server that does not carry its own override.
    """

    default_target: str


class MCPServerToolUpdate(BaseModel):
    """DTO for updating tenant-level tool settings."""

    is_enabled: bool


class MCPConnectionStatus(BaseModel):
    """Status of MCP server connection attempt."""

    success: bool
    tools_discovered: int = 0
    error_message: Optional[str] = None


class MCPServerCreateResponse(BaseModel):
    """Response for MCP server creation including connection status."""

    server: MCPServerPublic
    connection: MCPConnectionStatus


class ToolChangePublic(BaseModel):
    """DTO for a tool change detected during sync."""

    tool: MCPServerToolPublic
    change_type: str  # "new", "changed", "removed"
    current_description: Optional[str] = None
    current_input_schema: Optional[dict[str, Any]] = None
    pending_description: Optional[str] = None
    pending_input_schema: Optional[dict[str, Any]] = None


class MCPServerToolSyncResponse(BaseModel):
    """Response for tool sync operation with changeset for review."""

    connection: MCPConnectionStatus
    new_tools: list[ToolChangePublic] = []
    changed_tools: list[ToolChangePublic] = []
    removed_tools: list[ToolChangePublic] = []
    unchanged_count: int = 0

    @computed_field
    def has_pending_changes(self) -> bool:
        return bool(self.new_tools or self.changed_tools or self.removed_tools)


class ToolReviewRequest(BaseModel):
    """DTO for reviewing (approving/rejecting) tool changes."""

    tool_ids: list[UUID]


class ToolReviewResponse(BaseModel):
    """Response after reviewing tool changes."""

    approved_tools: list[MCPServerToolPublic] = []
    rejected_tools: list[MCPServerToolPublic] = []
    deleted_count: int = 0
