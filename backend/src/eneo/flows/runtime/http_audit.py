from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.flows.domain.flow_run_exceptions import FlowStepAttemptClosed
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.mcp_servers.domain.server_address import loggable_server_address

logger = logging.getLogger(__name__)

# The longest a tool or HTTP input read waits for its audit record to be
# queued. The audit log's queue client sets no read timeout, so a half-open
# queue connection would otherwise hold the read, and its worker, without
# limit; the ending is logged instead.
READ_AUDIT_TIMEOUT_SECONDS: Final = 5.0

# Writes cut off at READ_AUDIT_TIMEOUT_SECONDS, held until they have unwound:
# the event loop keeps only a weak reference to a task.
_UNWINDING_WRITES: set[asyncio.Future[None]] = set()


class RuntimeAuditRun(Protocol):
    @property
    def id(self) -> Any: ...

    @property
    def flow_id(self) -> Any: ...

    @property
    def tenant_id(self) -> Any: ...


class RuntimeAuditStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def step_id(self) -> Any: ...

    @property
    def user_description(self) -> str | None: ...


@dataclass(frozen=True)
class HttpAuditDeps:
    audit_service: Any | None
    actor: FlowRunActor
    logger: Any
    # Event-loop time at which the audit write is given up and logged like any
    # other audit failure; None waits for it.
    ends_at: float | None = None


@dataclass(frozen=True, slots=True)
class AuditedToolCall:
    """What an outbound call to an MCP server was for: the registered server
    and the tool it was asked to run. The arguments are never part of it."""

    mcp_server_id: UUID
    tool_name: str


def unfinished_call_message(exc: BaseException, *, request_sent: bool) -> str:
    """The audit text of a read that ended without a typed result (stopped, or
    an error with no typed code): a fixed text that says whether its request
    was sent. The error's own text is never used: it can quote the server, its
    address or the request."""
    stopped = isinstance(exc, (asyncio.CancelledError, FlowStepAttemptClosed))
    if not request_sent:
        if stopped:
            return "The read was stopped before its request was sent."
        return "The read ended with an error that has no typed code before its request was sent."
    if stopped:
        return "The call was stopped before it ended."
    return "The call ended with an error that has no typed code."


async def await_read_audit(write: Awaitable[None]) -> None:
    """Wait at most READ_AUDIT_TIMEOUT_SECONDS for ``write``, which queues the
    audit record of a tool or HTTP input read; on expiry it is cancelled, a
    warning that the record may not have been queued is logged and this
    returns without waiting for it to unwind, so ``write`` must not use the
    read's database session.

    A read that is stopped while its record is being queued goes on waiting
    for that same write, within the same limit, and stops after it: the
    record is neither lost nor queued again by the read's own handling of
    the stop."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + READ_AUDIT_TIMEOUT_SECONDS
    queued = asyncio.ensure_future(write)
    stop: asyncio.CancelledError | None = None
    while not queued.done() and (left := deadline - loop.time()) > 0:
        try:
            # Cancelling this wait leaves the write running.
            await asyncio.wait((queued,), timeout=left)
        except asyncio.CancelledError as cancelled:
            stop = cancelled
    if not queued.done():
        queued.cancel()
        _UNWINDING_WRITES.add(queued)
        queued.add_done_callback(_UNWINDING_WRITES.discard)
        logger.warning(
            "flow_executor.read_audit_timed_out: the read's audit record may "
            "not have been queued"
        )
    elif stop is None:
        queued.result()
    if stop is not None:
        raise stop


async def audit_http_outbound(
    *,
    run: RuntimeAuditRun,
    step: RuntimeAuditStep,
    url: str,
    method: str,
    call_type: str,
    outcome: Outcome,
    error_message: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
    tool: AuditedToolCall | None = None,
    deps: HttpAuditDeps,
) -> None:
    if deps.audit_service is None:
        return
    try:
        extra: dict[str, Any] = {
            "call_type": call_type,
            "http_method": method,
            "flow_id": str(run.flow_id),
            "step_order": step.step_order,
            "step_id": str(step.step_id),
        }
        if step.user_description:
            extra["step_description"] = step.user_description
        if status_code is not None:
            extra["status_code"] = status_code
        if duration_ms is not None:
            extra["duration_ms"] = round(duration_ms, 2)
        if tool is None:
            parts = urlsplit(url)
            url_host = f"{parts.scheme}://{parts.hostname}" if parts.hostname else ""
            url_path = parts.path or "/"
            extra["url_path"] = url_path
            target = f"{url_host}{url_path}"
        else:
            # The path and query of an MCP server's registered address can
            # carry a token; the server is named by its id and its address
            # without them.
            url_host = target = loggable_server_address(url)
            extra["mcp_server_id"] = str(tool.mcp_server_id)
            extra["tool_name"] = tool.tool_name
        extra["url_host"] = url_host
        actor_fields = deps.actor.audit_actor_fields()
        async with asyncio.timeout_at(deps.ends_at):
            await deps.audit_service.log_async(
                tenant_id=run.tenant_id,
                actor_id=actor_fields["actor_id"],
                actor_type=actor_fields["actor_type"],
                actor_api_key_id=actor_fields["actor_api_key_id"],
                action=ActionType.FLOW_HTTP_OUTBOUND_CALL,
                entity_type=EntityType.FLOW_RUN,
                entity_id=run.id,
                description=f"Flow HTTP {call_type} {method} to {target}",
                metadata=deps.actor.audit_metadata(target=run, extra=extra),
                outcome=outcome,
                error_message=error_message,
            )
    except Exception:
        deps.logger.warning(
            "flow_executor.audit_http_outbound_failed run_id=%s step_order=%d",
            run.id,
            step.step_order,
            exc_info=True,
        )
