from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.base.base_entity import Entity
from eneo.roles.permissions import Permission

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

# An MCP server's purpose is either "general" (ordinary assistant tooling) or
# a capability purpose. A capability server is a tenant-wide provider for one
# capability (web search, image generation): at most one is active per tenant,
# spaces and assistants attach it as a capability marker rather than a
# provider pin, and the ask path substitutes the active provider. The tuple
# order is the order resolved providers are prepended in at ask time.
GENERAL_PURPOSE = "general"
CAPABILITY_PURPOSES: tuple[str, ...] = ("web_search", "image_generation")

# Who a capability provider serves. "everyone" is the tenant's default provider
# for its purpose (at most one active per tenant and purpose); "groups" targets
# the members of the provider's user groups and may coexist with the default
# and with other group-targeted providers. A user matching several
# group-targeted providers gets the one with the lowest audience_priority.
AUDIENCE_EVERYONE = "everyone"
AUDIENCE_GROUPS = "groups"
AUDIENCES: tuple[str, ...] = (AUDIENCE_EVERYONE, AUDIENCE_GROUPS)
DEFAULT_AUDIENCE_PRIORITY = 100

# A built-in provider is an ordinary row whose endpoint is one of Eneo's own
# loopback MCP servers. It differs from an external server only by this auth
# type: the ask path mints a scoped token for it instead of sending stored
# credentials, and ``image_model_id`` names the catalog image model the
# loopback tool calls (credentials come from that model's provider, defaults
# and security classification from the model). Today only image generation
# has one.
INTERNAL_AUTH_TYPE = "internal"
BUILTIN_PROVIDER_PURPOSES: tuple[str, ...] = ("image_generation",)


def is_builtin_provider(http_auth_type: str | None) -> bool:
    return http_auth_type == INTERNAL_AUTH_TYPE


@dataclass(frozen=True)
class MCPServerBackingModel:
    """Read-only projection of the catalog model a built-in provider runs on."""

    id: UUID
    name: str
    nickname: str
    provider_name: str | None
    is_enabled: bool
    is_deleted: bool
    security_classification: "SecurityClassification | None"


def is_capability_purpose(purpose: str | None) -> bool:
    return bool(purpose) and purpose != GENERAL_PURPOSE


def duplicate_capability_purposes(purposes: Iterable[str | None]) -> list[str]:
    """Capability purposes that occur more than once, in first-seen order.

    A space or assistant attaches at most one marker per capability: the
    marker only requests the capability, so a second one for the same purpose
    adds nothing and would let a stale marker keep the capability requested
    after the user switches the other one off.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for purpose in purposes:
        if not is_capability_purpose(purpose):
            continue
        assert purpose is not None
        if purpose in seen and purpose not in duplicates:
            duplicates.append(purpose)
        seen.add(purpose)
    return duplicates


def capability_permission(purpose: str) -> Permission:
    """The role permission that lets a user use this capability purpose.

    Permission values equal purpose strings, so no per-purpose table exists.
    """
    return Permission(purpose)


def allowed_capability_purposes(permissions: "set[Permission]") -> set[str]:
    """Capability purposes the given permission set may use."""
    return {
        purpose
        for purpose in CAPABILITY_PURPOSES
        if capability_permission(purpose) in permissions
    }


@dataclass(frozen=True)
class MCPServerAudienceGroup:
    """A user group in a group-targeted provider's audience."""

    id: UUID
    name: str


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
        display_name: Optional[str] = None,
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
        self.display_name = display_name
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
        purpose: str = GENERAL_PURPOSE,
        is_enabled: bool = True,
        audience: str = AUDIENCE_EVERYONE,
        audience_priority: int = DEFAULT_AUDIENCE_PRIORITY,
        user_groups: Optional[list[MCPServerAudienceGroup]] = None,
        image_model_id: Optional[UUID] = None,
        image_model: Optional[MCPServerBackingModel] = None,
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
        self.purpose = purpose
        self.is_enabled = is_enabled
        self.audience = audience
        self.audience_priority = audience_priority
        self.user_groups = list(user_groups or [])
        self.image_model_id = image_model_id
        self.image_model = image_model
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

    @property
    def user_group_ids(self) -> list[UUID]:
        return [group.id for group in self.user_groups]

    @property
    def effective_security_classification(self) -> "SecurityClassification | None":
        """The row's own classification, else that of the model it runs on.

        A built-in provider never stores its own classification, so for it
        this is always the image model's; an external server has no backing
        model, so this is always its own.
        """
        if self.security_classification is not None:
            return self.security_classification
        if self.image_model is not None:
            return self.image_model.security_classification
        return None

    @property
    def is_backing_model_available(self) -> bool:
        """False when the provider runs on a model that is disabled or deleted."""
        if self.image_model is None:
            return True
        return self.image_model.is_enabled and not self.image_model.is_deleted

    def is_default_provider(self) -> bool:
        """True for a capability provider that serves everyone in the tenant."""
        return (
            is_capability_purpose(self.purpose) and self.audience == AUDIENCE_EVERYONE
        )

    def serves_user_groups(self, user_group_ids: "set[UUID]") -> bool:
        """True when this group-targeted provider covers any of the groups."""
        return self.audience == AUDIENCE_GROUPS and any(
            group_id in user_group_ids for group_id in self.user_group_ids
        )


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
