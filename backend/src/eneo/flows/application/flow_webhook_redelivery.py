"""Sending a run's result again after its delivery ended in dead letter.

A run result delivery that ends in dead letter never changes its completed
run, so the result reaches its receiver only if someone sends it again. A
redelivery resets that one row to a fresh attempt budget; the outbox then
sends it as before, with the same idempotency key and to the same address.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus, FlowRuns
from eneo.flows.application.flow_webhook_delivery_policy import (
    flow_webhook_delivery_request,
    flow_webhook_delivery_request_timeout_seconds,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport import sends_run_result
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.published_runtime import load_published_definition
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuditLoggingUnavailableException,
    ConflictException,
    NotFoundException,
)
from eneo.tasks.contracts import TaskEnqueuer, TaskEnqueueStatus

logger = logging.getLogger(__name__)

RedeliveryRefusal = Literal[
    "not_run_result",
    "run_not_completed",
    "not_dead_lettered",
    "dead_lettered_at_changed",
]

_REFUSAL_MESSAGES: dict[RedeliveryRefusal, str] = {
    "not_run_result": "Only a run result delivery can be sent again.",
    "run_not_completed": "A run result is sent again only for a completed run.",
    "not_dead_lettered": "The delivery is not dead-lettered.",
    "dead_lettered_at_changed": (
        "The delivery's dead letter changed; refresh the run before retrying."
    ),
}


def _refuse(reason: RedeliveryRefusal, *, delivery_id: UUID) -> ConflictException:
    return ConflictException(
        _REFUSAL_MESSAGES[reason],
        code=FlowApiErrorCode.RUN_WEBHOOK_REDELIVERY_CONFLICT.value,
        context={"reason": reason, "delivery_id": str(delivery_id)},
    )


def _audit_unavailable() -> AuditLoggingUnavailableException:
    return AuditLoggingUnavailableException(
        "Redelivery audit logging is unavailable.",
        code=FlowApiErrorCode.RUN_WEBHOOK_REDELIVERY_AUDIT_UNAVAILABLE.value,
        context={"audit_required": True},
    )


async def redeliver_run_result(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    run_id: UUID,
    delivery_id: UUID,
    expected_dead_lettered_at: datetime,
    actor_id: UUID | None,
    actor_type: ActorType,
    actor_api_key_id: UUID | None,
    audit_metadata: dict[str, Any],
) -> FlowRunWebhookDeliveryRead:
    """Reset one dead-lettered run result delivery and audit it, in one commit.

    The run is locked first, so a redelivery and the run's history purge have
    one winner: a purge that wins leaves nothing to find (404), and a
    redelivery that wins leaves a pending delivery the purge keeps. The caller
    wakes the outbox after the commit."""
    try:
        async with sessionmanager.session() as session:
            container = Container(session=providers.Object(session))
            async with session.begin():
                run = (
                    await session.execute(
                        sa.select(FlowRuns.status, FlowRuns.flow_version)
                        .where(FlowRuns.id == run_id)
                        .where(FlowRuns.tenant_id == tenant_id)
                        .where(FlowRuns.flow_id == flow_id)
                        .with_for_update()
                    )
                ).one_or_none()
                delivery_repo = FlowRunWebhookDeliveryRepository(session=session)
                delivery = (
                    None
                    if run is None
                    else await delivery_repo.get_run_delivery(
                        delivery_id=delivery_id, run_id=run_id, tenant_id=tenant_id
                    )
                )
                if run is None or delivery is None:
                    raise NotFoundException("Flow run webhook delivery not found.")

                definition = await load_published_definition(
                    flow_version_repo=container.flow_version_repo(),
                    flow_id=flow_id,
                    version=run.flow_version,
                    tenant_id=tenant_id,
                )
                step = next(
                    (
                        item
                        for item in definition.runtime_steps()
                        if item.step_id == delivery.step_id
                    ),
                    None,
                )
                if step is None or not sends_run_result(
                    step.output_mode, step.output_config
                ):
                    raise _refuse("not_run_result", delivery_id=delivery_id)
                if run.status != FlowRunStatus.COMPLETED.value:
                    raise _refuse("run_not_completed", delivery_id=delivery_id)
                if delivery.delivery_status is not (
                    FlowOutboxDeliveryStatus.DEAD_LETTERED
                ):
                    raise _refuse("not_dead_lettered", delivery_id=delivery_id)

                reset = await delivery_repo.redeliver_dead_lettered(
                    delivery_id=delivery_id,
                    tenant_id=tenant_id,
                    expected_dead_lettered_at=expected_dead_lettered_at,
                    now=datetime.now(timezone.utc),
                )
                if reset is None:
                    raise _refuse("dead_lettered_at_changed", delivery_id=delivery_id)
                audit_log = await container.audit_service().log(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    actor_api_key_id=actor_api_key_id,
                    action=ActionType.FLOW_RUN_WEBHOOK_REDELIVERED,
                    entity_type=EntityType.FLOW_RUN,
                    entity_id=run_id,
                    description=f"Run result sent again for flow run {run_id}",
                    metadata={
                        **audit_metadata,
                        "flow_id": str(flow_id),
                        "run_id": str(run_id),
                        "delivery_id": str(delivery_id),
                        "previous_dead_lettered_at": (
                            expected_dead_lettered_at.isoformat()
                        ),
                        "previous_delivery_attempts": delivery.delivery_attempts,
                    },
                )
                if audit_log is None:
                    raise _audit_unavailable()
    except (AuditLoggingUnavailableException, ConflictException, NotFoundException):
        raise
    except Exception as exc:
        logger.exception(
            "Required Flow run redelivery audit transaction failed",
            extra={"run_id": str(run_id), "tenant_id": str(tenant_id)},
        )
        raise _audit_unavailable() from exc
    return reset


async def wake_webhook_outbox(task_enqueuer: TaskEnqueuer) -> None:
    """Ask for an outbox job after a redelivery has committed. A lost request
    only delays the send: the outbox cron starts a job every interval."""
    try:
        async with asyncio.timeout(flow_webhook_delivery_request_timeout_seconds()):
            result = await task_enqueuer.enqueue(flow_webhook_delivery_request())
    except Exception:
        logger.warning("flow_webhook_redelivery.wake_failed", exc_info=True)
        return
    if result.status is not TaskEnqueueStatus.ACCEPTED:
        logger.warning(
            "flow_webhook_redelivery.wake_not_accepted status=%s",
            result.status.value,
        )
