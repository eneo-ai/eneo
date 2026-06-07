"""Elicitation manager for MCP server-initiated user prompts.

When an MCP server calls ``ctx.elicit(...)`` during a tool call, eneo's MCP
client receives an elicitation request. The streaming loop surfaces it to the
user (an SSE event) and this manager bridges the user's later HTTP response back
to the suspended tool call.

In-process by design: the suspended completion stream and the response endpoint
must run in the same worker. This mirrors ``ToolApprovalManager``'s lifecycle but
for the simpler one-shot elicitation case. Swap the in-memory dict for Redis if
cross-worker delivery is ever required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Optional
from uuid import UUID

from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

# Reuse the tool-approval timeout knob so both human-in-the-loop gates wait the
# same amount of time before giving up.
ELICITATION_TIMEOUT_SECONDS = float(get_settings().mcp_tool_approval_timeout_seconds)

ElicitationAction = Literal["accept", "decline", "cancel"]


@dataclass
class ElicitationContext:
    """Actor/scope context for a pending elicitation (used to authorize replies)."""

    tenant_id: UUID
    user_id: UUID
    session_id: UUID
    assistant_id: Optional[UUID] = None


@dataclass
class ElicitationResult:
    action: ElicitationAction
    content: Optional[dict[str, Any]] = None


@dataclass
class _Pending:
    context: ElicitationContext
    event: asyncio.Event
    result: Optional[ElicitationResult] = None


class ElicitationManager:
    """Tracks pending elicitations and resolves them when the user responds."""

    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    def request(self, elicitation_id: str, context: ElicitationContext) -> None:
        """Register a new pending elicitation before surfacing it to the user."""
        self._pending[elicitation_id] = _Pending(context=context, event=asyncio.Event())

    async def wait(
        self, elicitation_id: str, timeout: float | None = None
    ) -> ElicitationResult:
        """Block until the user responds or the wait times out (then cancel)."""
        pending = self._pending.get(elicitation_id)
        if pending is None:
            return ElicitationResult(action="cancel")

        effective = ELICITATION_TIMEOUT_SECONDS if timeout is None else timeout
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=effective)
            return pending.result or ElicitationResult(action="cancel")
        except asyncio.TimeoutError:
            logger.info("Elicitation %s timed out; cancelling", elicitation_id)
            return ElicitationResult(action="cancel")
        finally:
            self._pending.pop(elicitation_id, None)

    def submit(
        self,
        elicitation_id: str,
        action: ElicitationAction,
        content: Optional[dict[str, Any]],
        actor_tenant_id: UUID,
        actor_user_id: UUID,
    ) -> Literal["accepted", "not_found", "forbidden"]:
        """Submit the user's response; unblocks the suspended ``wait``."""
        pending = self._pending.get(elicitation_id)
        if pending is None:
            return "not_found"
        if (
            pending.context.tenant_id != actor_tenant_id
            or pending.context.user_id != actor_user_id
        ):
            return "forbidden"
        pending.result = ElicitationResult(action=action, content=content)
        pending.event.set()
        return "accepted"

    def get_context(
        self,
        elicitation_id: str,
        actor_tenant_id: UUID,
        actor_user_id: UUID,
    ) -> Optional[ElicitationContext]:
        """Return the pending context if it belongs to this actor, else None."""
        pending = self._pending.get(elicitation_id)
        if pending is None:
            return None
        ctx = pending.context
        if ctx.tenant_id != actor_tenant_id or ctx.user_id != actor_user_id:
            return None
        return ctx

    def cancel(self, elicitation_id: str) -> None:
        """Cancel a pending elicitation (e.g. on stream disconnect)."""
        pending = self._pending.get(elicitation_id)
        if pending is not None:
            pending.result = ElicitationResult(action="cancel")
            pending.event.set()


_elicitation_manager: Optional[ElicitationManager] = None


def get_elicitation_manager() -> ElicitationManager:
    """Get the global in-process elicitation manager."""
    global _elicitation_manager
    if _elicitation_manager is None:
        _elicitation_manager = ElicitationManager()
    return _elicitation_manager
