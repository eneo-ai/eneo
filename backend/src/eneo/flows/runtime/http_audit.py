from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.mcp_servers.domain.server_address import loggable_server_address


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


@dataclass(frozen=True, slots=True)
class AuditedToolCall:
    """What an outbound call to an MCP server was for: the registered server
    and the tool it was asked to run. The arguments are never part of it."""

    mcp_server_id: UUID
    tool_name: str


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
