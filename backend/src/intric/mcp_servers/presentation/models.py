from typing import Generic, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, computed_field

T = TypeVar("T", bound=BaseModel)


class BaseListModel(BaseModel, Generic[T]):
    items: list[T]

    @computed_field
    def count(self) -> int:
        return len(self.items)


class MCPServerPublic(BaseModel):
    """Public DTO for MCP server."""

    id: UUID
    name: str
    description: Optional[str]
    server_type: str  # "npm", "docker", "http"
    npm_package: Optional[str]
    docker_image: Optional[str]
    http_url: Optional[str]
    config_schema: Optional[dict]
    tags: Optional[list[str]]
    icon_url: Optional[str]
    documentation_url: Optional[str]


class MCPServerList(BaseListModel[MCPServerPublic]):
    pass


class MCPServerCreate(BaseModel):
    """DTO for creating an MCP server (admin only)."""

    name: str
    server_type: Literal["npm", "docker", "http"]
    description: Optional[str] = None
    npm_package: Optional[str] = None
    docker_image: Optional[str] = None
    http_url: Optional[str] = None
    config_schema: Optional[dict] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[str] = None
    documentation_url: Optional[str] = None


class MCPServerUpdate(BaseModel):
    """DTO for updating an MCP server (admin only)."""

    name: Optional[str] = None
    server_type: Optional[Literal["npm", "docker", "http"]] = None
    description: Optional[str] = None
    npm_package: Optional[str] = None
    docker_image: Optional[str] = None
    http_url: Optional[str] = None
    config_schema: Optional[dict] = None
    tags: Optional[list[str]] = None
    icon_url: Optional[str] = None
    documentation_url: Optional[str] = None


class MCPServerSettingsPublic(MCPServerPublic):
    """DTO for MCP server with tenant settings."""

    mcp_server_id: UUID  # ID in global catalog
    is_org_enabled: bool
    has_credentials: bool  # Whether env_vars are configured

    @computed_field
    def is_available(self) -> bool:
        """Whether this MCP is enabled and available for use."""
        return self.is_org_enabled


class MCPServerSettingsList(BaseListModel[MCPServerSettingsPublic]):
    pass


class MCPServerSettingsCreate(BaseModel):
    """DTO for enabling an MCP server for tenant."""

    env_vars: Optional[dict] = None  # Credentials/tokens for this MCP


class MCPServerSettingsUpdate(BaseModel):
    """DTO for updating MCP server settings."""

    is_org_enabled: Optional[bool] = None
    env_vars: Optional[dict] = None


class AssistantMCPServerPublic(BaseModel):
    """DTO for assistant's MCP server association."""

    mcp_server_id: UUID
    mcp_server_name: str
    enabled: bool
    config: Optional[dict]
    priority: int


class AssistantMCPServerUpdate(BaseModel):
    """DTO for updating assistant MCP association."""

    enabled: Optional[bool] = None
    config: Optional[dict] = None
    priority: Optional[int] = None
