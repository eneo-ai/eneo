"""Resolve the MCP provider that serves a user for a capability purpose.

Spaces, assistants, and governance policies store capability purposes.
At ask time the provider serving the current user is resolved from that
purpose. Provider deletion or replacement never removes saved intent.

Per purpose a tenant may have one active default provider (audience
"everyone") and any number of active group-targeted providers (audience
"groups"). A user gets the group-targeted provider with the lowest
audience_priority among those covering one of their groups, else the default.
The resolved provider is then gated by the user's role permission for the
purpose and by the space's security classification.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
)
from eneo.database.tables.mcp_server_table import (
    MCPServerToolSettings,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    is_capability_purpose,
)
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_repo_impl import (
    backing_model_options,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.mcp_servers.domain.entities.mcp_server import (
        MCPServer,
        MCPServerTool,
    )
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )


def usable_capability_tools(server: "MCPServer") -> list["MCPServerTool"]:
    """Tools the proxy would actually expose: enabled, still on the remote,
    and with an admin-approved definition."""
    return [
        tool
        for tool in server.tools
        if tool.is_enabled_by_default
        and not tool.removed_from_remote
        and (tool.description is not None or tool.input_schema is not None)
    ]


async def get_active_capability_servers(
    session: "AsyncSession", tenant_id: UUID, purpose: str
) -> list["MCPServer"]:
    """Return every active provider for ``purpose`` in the tenant.

    Tools carry the tenant-level enablement overlay so downstream consumers
    (the MCP proxy, usability checks) see effective enablement. Audience
    groups, security classification and the backing model (built-in
    providers) are loaded for resolution.
    """
    query = (
        sa.select(MCPServersTable)
        .where(
            MCPServersTable.tenant_id == tenant_id,
            MCPServersTable.purpose == purpose,
            MCPServersTable.is_enabled == True,  # noqa: E712
        )
        .options(
            selectinload(MCPServersTable.tools),
            selectinload(MCPServersTable.user_groups),
            selectinload(MCPServersTable.security_classification).selectinload(
                SecurityClassificationDBModel.tenant
            ),
            *backing_model_options(),
        )
        .order_by(MCPServersTable.created_at, MCPServersTable.id)
    )
    records = (await session.scalars(query)).all()
    if not records:
        return []

    servers = [MCPServerMapper.to_entity(record) for record in records]

    tool_ids = [tool.id for server in servers for tool in server.tools]
    if tool_ids:
        settings_stmt = sa.select(
            MCPServerToolSettings.mcp_server_tool_id,
            MCPServerToolSettings.is_enabled,
        ).where(
            MCPServerToolSettings.tenant_id == tenant_id,
            MCPServerToolSettings.mcp_server_tool_id.in_(tool_ids),
        )
        settings_rows = (await session.execute(settings_stmt)).all()
        tenant_settings = {tool_id: enabled for tool_id, enabled in settings_rows}
        for server in servers:
            for tool in server.tools:
                if tool.id in tenant_settings:
                    tool.is_enabled_by_default = tenant_settings[tool.id]

    return servers


def select_provider_for_user(
    providers: Iterable["MCPServer"], user_group_ids: "set[UUID]"
) -> "MCPServer | None":
    """Pick the provider that serves a member of ``user_group_ids``.

    A group-targeted provider covering any of the user's groups wins over the
    default; among several, the lowest ``audience_priority`` wins and the
    name breaks ties so the choice is deterministic and visible to admins.
    """
    providers = list(providers)
    targeted = [
        provider
        for provider in providers
        if provider.serves_user_groups(user_group_ids)
    ]
    if targeted:
        return min(targeted, key=lambda p: (p.audience_priority, p.name.lower()))
    return next((p for p in providers if p.is_default_provider()), None)


def meets_security_classification(
    provider: "MCPServer",
    space_security_classification: "SecurityClassification | None",
) -> bool:
    """False when the space's classification is stricter than the provider's.

    A built-in provider's classification is the one of the model it runs on.
    """
    if space_security_classification is None:
        return True
    return not space_security_classification.is_greater_than(
        provider.effective_security_classification
    )


@dataclass(frozen=True)
class CapabilityResolution:
    """Attached servers split into general servers and resolved providers."""

    general_servers: list["MCPServer"]
    capability_servers: list["MCPServer"]


async def resolve_capability_servers(
    session: "AsyncSession",
    tenant_id: UUID,
    attached_servers: Sequence["MCPServer"],
    *,
    supports_tool_calling: bool,
    requested_capabilities: Sequence[str] = (),
    user_group_ids: "set[UUID] | None" = None,
    allowed_purposes: "set[str] | None" = None,
    space_security_classification: "SecurityClassification | None" = None,
) -> CapabilityResolution:
    """Resolve independent purposes to the providers serving the user.

    Capability-purpose servers among ``attached_servers`` are stripped (they
    may be stale or deactivated) and, for every requested purpose in
    ``CAPABILITY_PURPOSES`` order, the provider serving the user is attached
    in its place when the user's role allows the purpose (``allowed_purposes``,
    None meaning every purpose), a provider exists for the user's groups or
    the tenant default, its backing model (if any) is enabled, it has usable
    tools, it meets the space's security classification, and the model can
    call tools. Anything else leaves the purpose silently unavailable this
    turn.
    """
    general_servers = [
        server
        for server in attached_servers
        if not is_capability_purpose(server.purpose)
    ]
    requested_purposes = set(requested_capabilities)
    if allowed_purposes is not None:
        requested_purposes &= allowed_purposes
    capability_servers: list["MCPServer"] = []
    if requested_purposes and supports_tool_calling:
        for purpose in CAPABILITY_PURPOSES:
            if purpose not in requested_purposes:
                continue
            providers = await get_active_capability_servers(session, tenant_id, purpose)
            provider = select_provider_for_user(providers, user_group_ids or set())
            if (
                provider is not None
                and provider.is_backing_model_available
                and usable_capability_tools(provider)
                and meets_security_classification(
                    provider, space_security_classification
                )
            ):
                capability_servers.append(provider)
    return CapabilityResolution(
        general_servers=general_servers, capability_servers=capability_servers
    )


def describe_capability_availability(
    providers: Sequence["MCPServer"],
    purpose: CapabilityPurpose,
    classification: "SecurityClassification | None" = None,
    *,
    user_group_ids: set[UUID] | None = None,
    allowed_purposes: set[str] | None = None,
) -> CapabilityAvailability:
    """Describe stored configuration readiness for a tenant or a specific user."""
    candidates = [p for p in providers if p.purpose == purpose and p.is_enabled]
    if allowed_purposes is not None and purpose not in allowed_purposes:
        return CapabilityAvailability(
            purpose=purpose, available=False, reason="permission"
        )
    if user_group_ids is not None:
        selected = select_provider_for_user(candidates, user_group_ids)
        candidates = [selected] if selected else []
    ready = [p for p in candidates if p.readiness_reason is None]
    available = any(meets_security_classification(p, classification) for p in ready)
    reason = (
        None
        if available
        else (
            "no_active_provider"
            if not candidates
            else "classification"
            if ready
            else next(
                (p.readiness_reason for p in candidates if p.readiness_reason),
                "no_approved_tools",
            )
        )
    )
    return CapabilityAvailability(purpose=purpose, available=available, reason=reason)


async def capability_availability(
    session: "AsyncSession",
    tenant_id: UUID,
    space_security_classification: "SecurityClassification | None" = None,
    *,
    user_group_ids: set[UUID] | None = None,
    allowed_purposes: set[str] | None = None,
) -> list[CapabilityAvailability]:
    """Stored readiness, never a live external connection-health claim."""
    result: list[CapabilityAvailability] = []
    for purpose in CAPABILITY_PURPOSES:
        providers = await get_active_capability_servers(session, tenant_id, purpose)
        result.append(
            describe_capability_availability(
                providers,
                purpose,
                space_security_classification,
                user_group_ids=user_group_ids,
                allowed_purposes=allowed_purposes,
            )
        )
    return result


async def validate_capability_additions(
    session: "AsyncSession",
    tenant_id: UUID,
    selected: Sequence[str],
    previous: Sequence[str],
    classification: "SecurityClassification | None" = None,
) -> None:
    """Only new grants require readiness; removals and retained intent always survive."""
    from eneo.main.exceptions import BadRequestException

    unknown = set(selected) - set(CAPABILITY_PURPOSES)
    if unknown:
        raise BadRequestException("Unknown capability")
    added = set(selected) - set(previous)
    if not added:
        return
    states = await capability_availability(session, tenant_id, classification)
    unavailable = [s.purpose for s in states if s.purpose in added and not s.available]
    if unavailable:
        raise BadRequestException("Capability unavailable: " + ", ".join(unavailable))
