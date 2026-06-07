"""Audit chokepoint for chat-plane (config-MCP) mutations.

Chat-plane writes bypass the HTTP routers where audit normally lives, so every
mutating capability is audited here instead. A future form-plane execute endpoint
reuses this same emit so both planes produce identical audit rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from intric.audit.domain.outcome import Outcome
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.config_capabilities.capability import (
        CapabilityContext,
        CapabilityResult,
        ConfigCapability,
    )

logger = get_logger(__name__)


async def emit_capability_audit(
    ctx: "CapabilityContext",
    capability: "ConfigCapability",
    result: "CapabilityResult | None",
    outcome: Outcome = Outcome.SUCCESS,
    error_message: str | None = None,
) -> None:
    """Emit an audit row for a mutating capability. Best-effort: never raises."""
    if capability.audit_action is None or capability.audit_entity is None:
        return
    entity_id = (result.entity_id if result else None) or ctx.assistant_id
    description = (
        result.summary if result and result.summary else f"Capability {capability.id}"
    )
    try:
        await ctx.container.audit_service().log_async(
            tenant_id=ctx.user.tenant_id,
            action=capability.audit_action,
            entity_type=capability.audit_entity,
            entity_id=entity_id,
            description=description,
            metadata={
                "plane": "chat",
                "capability": capability.id,
                "scope": capability.scope.value,
                "assistant_id": str(ctx.assistant_id),
            },
            user=ctx.user,
            outcome=outcome,
            error_message=error_message,
        )
    except Exception as exc:  # noqa: BLE001 - audit must not break the tool
        logger.warning("Failed to emit capability audit for %s: %s", capability.id, exc)
