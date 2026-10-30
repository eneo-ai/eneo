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

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
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
    apply_tenant_tool_settings,
    backing_model_options,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )


async def active_capability_providers(
    session: "AsyncSession",
    tenant_id: UUID,
    purposes: Iterable[str] = CAPABILITY_PURPOSES,
) -> list["MCPServer"]:
    """Return every active provider for any of ``purposes`` in the tenant.

    One flat list in creation order: callers pick per purpose, so a purpose
    never sees another purpose's providers. Read as the server repository
    reads, so the tools carry the tenant's tool settings and audience groups,
    security classification and backing model (built-in providers) are loaded
    for resolution.
    """
    query = (
        sa.select(MCPServersTable)
        .where(
            MCPServersTable.tenant_id == tenant_id,
            MCPServersTable.purpose.in_(tuple(purposes)),
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
    return await apply_tenant_tool_settings(
        session, [MCPServerMapper.to_entity(record) for record in records]
    )


async def get_active_capability_servers(
    session: "AsyncSession", tenant_id: UUID, purpose: str
) -> list["MCPServer"]:
    """Return every active provider for ``purpose`` in the tenant."""
    return await active_capability_providers(session, tenant_id, (purpose,))


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


class ClassifiedServer(Protocol):
    """What the classification comparison reads of a server."""

    @property
    def effective_security_classification(self) -> "SecurityClassification | None": ...


def meets_security_classification(
    provider: ClassifiedServer,
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


def general_servers_for_space(
    attached_servers: Sequence["MCPServer"],
    space_security_classification: "SecurityClassification | None",
    *,
    in_space: Callable[[UUID], bool],
) -> list["MCPServer"]:
    """The general-purpose servers among ``attached_servers`` the space may call.

    Capability-purpose servers are markers resolved separately. A general
    server is called directly, so one that the space no longer has
    (``in_space``), or whose classification has dropped below the space's
    since it was attached, is left out this turn; attachments are never
    pruned here.
    """
    return [
        server
        for server in attached_servers
        if not is_capability_purpose(server.purpose)
        and in_space(server.id)
        and meets_security_classification(server, space_security_classification)
    ]


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
    in_space: Callable[[UUID], bool],
) -> CapabilityResolution:
    """Resolve independent purposes to the providers serving the user.

    Capability-purpose servers among ``attached_servers`` are stripped (they
    may be stale or deactivated), general servers the space no longer has or
    that are below its security classification are left out, and, for every
    requested purpose in ``CAPABILITY_PURPOSES`` order, the provider serving
    the user is attached in its place when the user's role allows the purpose
    (``allowed_purposes``,
    None meaning every purpose), a provider exists for the user's groups or
    the tenant default, its backing model (if any) is enabled, it has usable
    tools, it meets the space's security classification, and the model can
    call tools. Anything else leaves the purpose silently unavailable this
    turn.
    """
    general_servers = general_servers_for_space(
        attached_servers, space_security_classification, in_space=in_space
    )
    requested_purposes = set(requested_capabilities)
    if allowed_purposes is not None:
        requested_purposes &= allowed_purposes
    purposes = tuple(p for p in CAPABILITY_PURPOSES if p in requested_purposes)
    capability_servers: list["MCPServer"] = []
    if purposes and supports_tool_calling:
        providers = await active_capability_providers(session, tenant_id, purposes)
        for purpose in purposes:
            provider = select_provider_for_user(
                [p for p in providers if p.purpose == purpose], user_group_ids or set()
            )
            if (
                provider is not None
                and provider.is_backing_model_available
                and provider.usable_tools
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


def availability_from_providers(
    providers: Sequence["MCPServer"],
    space_security_classification: "SecurityClassification | None" = None,
    *,
    user_group_ids: set[UUID] | None = None,
    allowed_purposes: set[str] | None = None,
) -> list[CapabilityAvailability]:
    """Readiness of every purpose, in ``CAPABILITY_PURPOSES`` order, from
    providers loaded once by ``active_capability_providers``."""
    return [
        describe_capability_availability(
            providers,
            purpose,
            space_security_classification,
            user_group_ids=user_group_ids,
            allowed_purposes=allowed_purposes,
        )
        for purpose in CAPABILITY_PURPOSES
    ]


async def capability_availability(
    session: "AsyncSession",
    tenant_id: UUID,
    space_security_classification: "SecurityClassification | None" = None,
    *,
    user_group_ids: set[UUID] | None = None,
    allowed_purposes: set[str] | None = None,
) -> list[CapabilityAvailability]:
    """Stored readiness, never a live external connection-health claim."""
    return availability_from_providers(
        await active_capability_providers(session, tenant_id),
        space_security_classification,
        user_group_ids=user_group_ids,
        allowed_purposes=allowed_purposes,
    )


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
