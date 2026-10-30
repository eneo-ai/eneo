"""Best-effort Flow run lifecycle events for operators.

The durable lifecycle audit trail is still `flow_run_audit_outbox`.
These events are structured log signals for dashboards and runbooks; they
must not become the recovery source for terminal state or audit delivery.
Keep failure text out of this event to avoid copying user-supplied content into logs.
Only bump the schema version for field changes that affect existing log queries.
"""

from __future__ import annotations

import logging
from typing import Final, Literal, TypedDict
from uuid import UUID

from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.enums import FlowRunLifecycleSource

logger = logging.getLogger(__name__)

FLOW_RUN_LIFECYCLE_EVENT_SCHEMA_VERSION: Final[int] = 1
FLOW_RUN_LIFECYCLE_EVENT_NAME: Final[str] = "flow_run.lifecycle"
FLOW_RUN_LIFECYCLE_LOG_MESSAGE: Final[str] = "flow_run_lifecycle_event"
FLOW_RUN_TERMINALIZATION_OPERATION: Final[str] = "terminalize_run"

FlowRunTerminalizationOutcome = Literal[
    "transitioned",
    "noop_already_terminal",
    "noop_lost_race",
]


class FlowRunTerminalizationEvent(TypedDict):
    event: str
    schema_version: int
    operation: str
    outcome: FlowRunTerminalizationOutcome
    tenant_id: str
    flow_id: str
    run_id: str
    trace_id: str
    source: str
    target_status: str
    previous_status: str
    run_revision: int
    audit_outbox_id: str | None
    error_code: str | None


def emit_flow_run_terminalization_event(
    *,
    run: FlowRun,
    outcome: FlowRunTerminalizationOutcome,
    source: FlowRunLifecycleSource,
    target_status: FlowRunStatus,
    previous_status: FlowRunStatus,
    audit_outbox_id: UUID | None,
    error_code: str | None,
) -> None:
    payload: FlowRunTerminalizationEvent = {
        "event": FLOW_RUN_LIFECYCLE_EVENT_NAME,
        "schema_version": FLOW_RUN_LIFECYCLE_EVENT_SCHEMA_VERSION,
        "operation": FLOW_RUN_TERMINALIZATION_OPERATION,
        "outcome": outcome,
        "tenant_id": str(run.tenant_id),
        "flow_id": str(run.flow_id),
        "run_id": str(run.id),
        "trace_id": str(run.trace_id),
        "source": source.value,
        "target_status": target_status.value,
        "previous_status": previous_status.value,
        "run_revision": run.revision,
        "audit_outbox_id": str(audit_outbox_id) if audit_outbox_id else None,
        "error_code": error_code,
    }
    logger.info(FLOW_RUN_LIFECYCLE_LOG_MESSAGE, extra=dict(payload))
