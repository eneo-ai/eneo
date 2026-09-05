from typing import Any, Generic, Literal, Optional, TypeVar, Union
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, computed_field, model_validator

from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided
from eneo.mcp_servers.domain.entities.mcp_server import (
    DEFAULT_AUDIENCE_PRIORITY,
    MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES,
    MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT,
    MCP_TOOL_CATALOG_HARD_MAX_BYTES,
    MCP_TOOL_CATALOG_HARD_MAX_COUNT,
    MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES,
    MCP_TOOL_DEFINITION_HARD_MAX_BYTES,
)
from eneo.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)

T = TypeVar("T", bound=BaseModel)

MCPServerPurpose = Literal["general", "web_search", "image_generation"]
MCPServerAudience = Literal["everyone", "groups"]


class MCPServerAudienceGroupPublic(BaseModel):
    id: UUID
    name: str


# "api_key_header" sends the credential in an admin-chosen header
# (e.g. X-Api-Key). Header name is validated server-side against HTTP token
# syntax and a deny-list of transport-level headers.
# "internal" marks a built-in provider: the endpoint is one of Eneo's own
# loopback MCP servers, authenticated with a per-request scoped token, and
# ``image_model_id`` names the catalog image model it calls.
MCPServerAuthType = Literal["none", "bearer", "api_key_header", "internal"]


class MCPServerBackingModelPublic(BaseModel):
    """The catalog image model a built-in provider runs on (read-only)."""

    id: UUID
    name: str
    nickname: str
    provider_name: Optional[str] = None
    is_enabled: bool


class BaseListModel(BaseModel, Generic[T]):
    items: list[T]

    @computed_field
    def count(self) -> int:
        return len(self.items)


class MCPServerPublic(BaseModel):
    """Public DTO for MCP server (HTTP-only, uses Streamable HTTP transport)."""

    id: UUID
    name: str
    description: Optional[str]
    http_url: str
    http_auth_type: str  # "none", "bearer", "api_key_header", "internal"
    purpose: MCPServerPurpose = "general"
    # Built-in providers only: the image model the loopback tool calls.
    image_model_id: Optional[UUID] = None
    image_model: Optional[MCPServerBackingModelPublic] = None
    is_enabled: bool = True
    readiness_reason: str | None = None
    # Capability providers: who this provider serves. "everyone" is the
    # tenant default; "groups" serves the listed user groups (lowest
    # audience_priority wins when a user matches several providers).
    audience: MCPServerAudience = "everyone"
    audience_priority: int = DEFAULT_AUDIENCE_PRIORITY
    user_groups: list[MCPServerAudienceGroupPublic] = []
    has_credentials: bool
    credential_preview: Optional[str] = None  # masked token, e.g. "••••••••sk12"
    forward_identity: bool = False
    tool_catalog_max_count: int = MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT
    tool_catalog_max_bytes: int = MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES
    tool_definition_max_bytes: int = MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES
    tags: Optional[list[str]]
    icon_url: Optional[str]
    documentation_url: Optional[str]
    # Effective classification: the row's own, or for a built-in provider the
    # one of its image model.
    security_classification: Optional[SecurityClassificationPublic] = None


class MCPServerList(BaseListModel[MCPServerPublic]):
    pass


class MCPServerCreate(BaseModel):
    activate: bool = False
    """DTO for creating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: str
    # Required unless http_auth_type is "internal": a built-in provider's URL
    # is Eneo's own loopback endpoint and is set server-side.
    http_url: Optional[AnyHttpUrl] = None
    http_auth_type: MCPServerAuthType = "none"
    purpose: MCPServerPurpose = "general"
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    # Built-in providers only: the catalog image model to call.
    image_model_id: Optional[UUID] = None
    forward_identity: bool = False
    tool_catalog_max_count: int = Field(
        default=MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT,
        ge=1,
        le=MCP_TOOL_CATALOG_HARD_MAX_COUNT,
    )
    tool_catalog_max_bytes: int = Field(
        default=MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES,
        ge=1024 * 1024,
        le=MCP_TOOL_CATALOG_HARD_MAX_BYTES,
        multiple_of=1024 * 1024,
    )
    tool_definition_max_bytes: int = Field(
        default=MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES,
        ge=1024,
        le=MCP_TOOL_DEFINITION_HARD_MAX_BYTES,
        multiple_of=1024,
    )
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None
    security_classification: Optional[ModelId] = None
    audience: MCPServerAudience = "everyone"
    audience_priority: int = Field(default=DEFAULT_AUDIENCE_PRIORITY, ge=0)
    user_group_ids: list[UUID] = []

    @model_validator(mode="after")
    def require_url_for_external_servers(self) -> "MCPServerCreate":
        if self.http_auth_type != "internal" and self.http_url is None:
            raise ValueError("http_url is required")
        if self.http_auth_type == "internal" and self.image_model_id is None:
            raise ValueError("image_model_id is required for a built-in provider")
        return self


class MCPServerUpdate(BaseModel):
    """DTO for updating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: Optional[str] = None
    http_url: Optional[AnyHttpUrl] = None
    http_auth_type: Optional[MCPServerAuthType] = None
    # Moving into a capability purpose saves the server as an inactive
    # provider; moving back to general makes it an ordinary enabled server.
    purpose: Optional[MCPServerPurpose] = None
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    # Absent keeps the current model, null clears it (only valid when
    # leaving the internal auth type), a UUID re-points the provider.
    image_model_id: Union[UUID, None, NotProvided] = NOT_PROVIDED
    forward_identity: Optional[bool] = None
    tool_catalog_max_count: Optional[int] = Field(
        default=None,
        ge=1,
        le=MCP_TOOL_CATALOG_HARD_MAX_COUNT,
    )
    tool_catalog_max_bytes: Optional[int] = Field(
        default=None,
        ge=1024 * 1024,
        le=MCP_TOOL_CATALOG_HARD_MAX_BYTES,
        multiple_of=1024 * 1024,
    )
    tool_definition_max_bytes: Optional[int] = Field(
        default=None,
        ge=1024,
        le=MCP_TOOL_DEFINITION_HARD_MAX_BYTES,
        multiple_of=1024,
    )
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED
    audience: Optional[MCPServerAudience] = None
    audience_priority: Optional[int] = Field(default=None, ge=0)
    user_group_ids: Optional[list[UUID]] = None


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
    title: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str]
    input_schema: Optional[dict[str, Any]]
    is_enabled_by_default: bool
    pending_description: Optional[str] = None
    pending_input_schema: Optional[dict[str, Any]] = None
    requires_approval: bool = False
    removed_from_remote: bool = False


class MCPServerToolList(BaseListModel[MCPServerToolPublic]):
    pass


class MCPServerToolUpdate(BaseModel):
    """DTO for updating tenant-level tool settings."""

    is_enabled: bool


class MCPServerToolRename(BaseModel):
    """DTO for setting an admin display name on a tool.

    None clears the override, falling back to the remote-synced title.
    """

    display_name: Optional[str] = None


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


class CapabilityActivationResponse(BaseModel):
    """Response after activating a capability provider."""

    server: MCPServerPublic
    deactivated_server_ids: list[UUID] = []
