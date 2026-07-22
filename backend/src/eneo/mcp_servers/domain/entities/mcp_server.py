from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.base.base_entity import Entity

if TYPE_CHECKING:
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )


# Administrators can tune normal operating limits per MCP server. The wider
# envelope is an application safety invariant: even a mistaken configuration
# must not make an untrusted tools/list response unbounded.
MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT = 256
MCP_TOOL_CATALOG_HARD_MAX_COUNT = 4096
MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
MCP_TOOL_CATALOG_HARD_MAX_BYTES = 64 * 1024 * 1024
MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES = 64 * 1024
MCP_TOOL_DEFINITION_HARD_MAX_BYTES = 1024 * 1024


class MCPToolCatalogLimitExceeded(ValueError):
    """A projected persisted tool catalog exceeds its server safety policy."""


class MCPToolCatalogStagingTimeout(RuntimeError):
    """A runtime catalog observation could not acquire its bounded DB window."""


class MCPServerTool(Entity):
    """Domain entity for MCP server tool."""

    def __init__(
        self,
        mcp_server_id: UUID,
        name: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        input_schema: Optional[dict[str, Any]] = None,
        is_enabled_by_default: bool = True,
        pending_description: Optional[str] = None,
        pending_input_schema: Optional[dict[str, Any]] = None,
        requires_approval: bool = False,
        removed_from_remote: bool = False,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.mcp_server_id = mcp_server_id
        self.name = name
        self.title = title
        self.description = description
        self.input_schema = input_schema
        self.is_enabled_by_default = is_enabled_by_default
        self.pending_description = pending_description
        self.pending_input_schema = pending_input_schema
        self.requires_approval = requires_approval
        self.removed_from_remote = removed_from_remote

    @classmethod
    def pending_discovery(
        cls,
        *,
        mcp_server_id: UUID,
        name: str,
        title: str | None,
        description: str | None,
        input_schema: dict[str, Any] | None,
    ) -> "MCPServerTool":
        """Create a discovered definition that cannot run before approval."""
        return cls(
            mcp_server_id=mcp_server_id,
            name=name,
            title=title,
            description=None,
            input_schema=None,
            is_enabled_by_default=True,
            pending_description=description,
            pending_input_schema=input_schema,
            requires_approval=True,
        )

    def has_definition_drift(
        self,
        *,
        description: str | None,
        input_schema: dict[str, Any] | None,
    ) -> bool:
        """Return whether a live contract differs from the approved contract."""
        return self.description != description or self.input_schema != input_schema


class MCPServer(Entity):
    """Domain entity for MCP server (tenant-scoped, HTTP-only)."""

    def __init__(
        self,
        tenant_id: UUID,
        name: str,
        http_url: str,
        description: Optional[str] = None,
        http_auth_type: str = "none",
        http_auth_config_schema: Optional[dict[str, Any]] = None,
        is_enabled: bool = True,
        forward_identity: bool = False,
        tool_catalog_max_count: int = MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT,
        tool_catalog_max_bytes: int = MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES,
        tool_definition_max_bytes: int = MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES,
        env_vars: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        icon_url: Optional[str] = None,
        documentation_url: Optional[str] = None,
        tools: Optional[list[MCPServerTool]] = None,
        security_classification: Optional["SecurityClassification"] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.http_url = http_url
        self.http_auth_type = http_auth_type
        self.http_auth_config_schema = http_auth_config_schema
        self.is_enabled = is_enabled
        self.forward_identity = forward_identity
        self.tool_catalog_max_count = tool_catalog_max_count
        self.tool_catalog_max_bytes = tool_catalog_max_bytes
        self.tool_definition_max_bytes = tool_definition_max_bytes
        self.env_vars = env_vars
        self.tags = tags
        self.icon_url = icon_url
        self.documentation_url = documentation_url
        self.tools = tools or []
        self.security_classification = security_classification


class MCPServerSettings(Entity):
    """Domain entity for MCP server settings (tenant-scoped configuration)."""

    def __init__(
        self,
        tenant_id: UUID,
        mcp_server_id: UUID,
        is_org_enabled: bool = True,
        env_vars: Optional[dict[str, Any]] = None,
        mcp_server: Optional[MCPServer] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.mcp_server_id = mcp_server_id
        self.is_org_enabled = is_org_enabled
        self.env_vars = env_vars
        self.mcp_server = mcp_server
