"""Bootstrap + runner for config capabilities (chat plane).

``capability_context`` builds a user-bound container and the resolved scope for
the token, inside a single write transaction. ``run_capability`` checks the
capability's permission against the space actor, runs the handler, and emits the
audit row for mutating capabilities. The MCP layer handles confirmation
(elicitation) before calling ``run_capability`` because that needs the live MCP
context; everything else is MCP-agnostic so the form plane can reuse it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator
from uuid import UUID

import jwt
from dependency_injector import providers
from pydantic import BaseModel

from intric.audit.domain.outcome import Outcome
from intric.config_capabilities.audit import emit_capability_audit
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
)
from intric.database.database import sessionmanager
from intric.main.config import get_settings
from intric.main.exceptions import UnauthorizedException

if TYPE_CHECKING:
    pass


def decode_config_claims(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        key=str(settings.jwt_secret),
        audience=settings.jwt_audience,
        algorithms=[settings.jwt_algorithm],
    )


@asynccontextmanager
async def capability_context(token: str) -> AsyncIterator[CapabilityContext]:
    """Yield a user-bound CapabilityContext for the token, in a write transaction.

    Commits on clean exit, rolls back on error (e.g. a permission failure). The
    space is resolved from the token's ``assistant_id`` (edit mode always carries
    it), so capabilities operate within the assistant's space.
    """
    # Lazy import: Container pulls in the full service graph (incl. assistant_service,
    # which imports the config-MCP package), so a top-level import would cycle.
    from intric.main.container.container import Container
    from intric.main.container.container_overrides import override_user

    claims = decode_config_claims(token)
    raw_assistant = claims.get("assistant_id")
    if not raw_assistant:
        raise ValueError("Config token is not scoped to an assistant.")
    assistant_id = UUID(str(raw_assistant))
    lang = "sv" if str(claims.get("lang", "")).lower().startswith("sv") else "en"

    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            user = await container.user_service().authenticate(token=token)
            override_user(container=container, user=user)
            space = await container.space_repo().get_space_by_assistant(
                assistant_id=assistant_id
            )
            yield CapabilityContext(
                container=container,
                user=user,
                space=space,
                assistant_id=assistant_id,
                lang=lang,
            )


async def run_capability(
    capability: ConfigCapability,
    ctx: CapabilityContext,
    inp: BaseModel,
) -> CapabilityResult:
    """Check permission, run the handler, audit mutating capabilities.

    The underlying application service re-checks permissions, so this pre-check is
    additive defense in depth (and gives a clean error before any work).
    """
    actor = ctx.container.actor_manager().get_space_actor_from_space(space=ctx.space)
    if not capability.permission(actor):
        raise UnauthorizedException(
            f"You do not have permission to run '{capability.id}'.",
            code="forbidden_action",
            context={
                "resource_type": "config_capability",
                "action": capability.id,
                "auth_layer": "domain_policy",
            },
        )

    try:
        result = await capability.handler(ctx, inp)
    except Exception as exc:
        if capability.mutating:
            await emit_capability_audit(
                ctx, capability, None, outcome=Outcome.FAILURE, error_message=str(exc)
            )
        raise

    if capability.mutating:
        await emit_capability_audit(ctx, capability, result, outcome=Outcome.SUCCESS)
    return result
