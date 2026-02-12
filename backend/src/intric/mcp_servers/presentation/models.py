from typing import Any, Generic, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, computed_field

T = TypeVar("T", bound=BaseModel)


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
    http_auth_type: str  # "none", "bearer", "api_key", "custom_headers"
    http_auth_config_schema: Optional[dict[str, Any]]
    tags: Optional[list[str]]
    icon_url: Optional[str]
    documentation_url: Optional[str]


class MCPServerList(BaseListModel[MCPServerPublic]):
    pass


class MCPServerCreate(BaseModel):
    """DTO for creating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: str
    http_url: AnyHttpUrl
    http_auth_type: Literal["none", "bearer", "api_key", "custom_headers", "oauth2_client_credentials"] = "none"
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None


class MCPServerUpdate(BaseModel):
    """DTO for updating an MCP server (admin only, uses Streamable HTTP transport)."""

    name: Optional[str] = None
    http_url: Optional[AnyHttpUrl] = None
    http_auth_type: Optional[Literal["none", "bearer", "api_key", "custom_headers", "oauth2_client_credentials"]] = (
        None
    )
    description: Optional[str] = None
    http_auth_config_schema: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[AnyHttpUrl] = None
    documentation_url: Optional[AnyHttpUrl] = None


class MCPServerSettingsPublic(MCPServerPublic):
    """DTO for MCP server with tenant settings."""

    mcp_server_id: UUID  # ID in global catalog
    is_org_enabled: bool
    has_credentials: bool  # Whether env_vars are configured
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


class MCPServerToolList(BaseListModel[MCPServerToolPublic]):
    pass


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


class MCPServerToolSyncResponse(BaseModel):
    """Response for tool sync operation including connection status."""

    tools: list[MCPServerToolPublic]
    connection: MCPConnectionStatus

    @computed_field
    def count(self) -> int:
        return len(self.tools)
