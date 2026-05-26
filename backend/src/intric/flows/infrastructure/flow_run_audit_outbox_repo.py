from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
)
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
)
from intric.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxDeliveryRow:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    run_revision: int
    review_checkpoint_id: UUID | None
    checkpoint_revision: int | None
    description: str
    action: str
    entity_type: str
    entity_id: UUID
    actor_id: UUID | None
    actor_type: str
    actor_api_key_id: UUID | None
    source: str
    target_status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    delivery_attempts: int


def flow_run_audit_description(
    *, action: ActionType, source: FlowRunLifecycleSource
) -> str:
    return f"{action.value}:{source.value}"


class FlowRunAuditOutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_terminal_audit_outbox(
        self,
        *,
        run: FlowRun,
        action: ActionType,
        actor_id: UUID | None,
        actor_type: ActorType,
        actor_api_key_id: UUID | None,
        source: FlowRunLifecycleSource,
        target_status: FlowRunStatus,
        error_code: str | None,
        error_message: str | None,
    ) -> UUID:
        outbox_id = await self.session.scalar(
            sa.insert(FlowRunAuditOutbox)
            .values(
                tenant_id=run.tenant_id,
                flow_id=run.flow_id,
                flow_run_id=run.id,
                run_revision=run.revision,
                description=flow_run_audit_description(action=action, source=source),
                action=action.value,
                entity_type=EntityType.FLOW_RUN.value,
                entity_id=run.id,
                actor_id=actor_id,
                actor_type=actor_type.value,
                actor_api_key_id=actor_api_key_id,
                source=source.value,
                target_status=target_status.value,
                error_code=error_code,
                error_message=error_message,
            )
            .returning(FlowRunAuditOutbox.id)
        )
        if outbox_id is None:
            raise RuntimeError("Flow run audit outbox insert did not return an id.")
        return outbox_id

    async def insert_review_checkpoint_audit_outbox(
        self,
        *,
        checkpoint: FlowRunReviewCheckpoint,
        run_revision: int,
        action: ActionType,
        actor_id: UUID | None,
        actor_type: ActorType,
        actor_api_key_id: UUID | None,
        source: FlowRunLifecycleSource,
        target_state: FlowRunReviewCheckpointState,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> UUID:
        outbox_id = await self.session.scalar(
            sa.insert(FlowRunAuditOutbox)
            .values(
                tenant_id=checkpoint.tenant_id,
                flow_id=checkpoint.flow_id,
                flow_run_id=checkpoint.flow_run_id,
                run_revision=run_revision,
                review_checkpoint_id=checkpoint.id,
                checkpoint_revision=checkpoint.revision,
                description=flow_run_audit_description(action=action, source=source),
                action=action.value,
                entity_type=EntityType.FLOW_RUN_REVIEW_CHECKPOINT.value,
                entity_id=checkpoint.id,
                actor_id=actor_id,
                actor_type=actor_type.value,
                actor_api_key_id=actor_api_key_id,
                source=source.value,
                target_status=target_state.value,
                error_code=error_code,
                error_message=error_message,
            )
            .returning(FlowRunAuditOutbox.id)
        )
        if outbox_id is None:
            raise RuntimeError("Review checkpoint audit outbox insert returned no id.")
        return outbox_id

    async def list_due_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[FlowRunAuditOutboxDeliveryRow]:
        if limit <= 0:
            return []
        # Delivery uses per-row savepoints; PostgreSQL keeps these claims locked
        # until the outer transaction commits.
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunAuditOutbox)
                    .where(
                        FlowRunAuditOutbox.delivery_status
                        == FlowOutboxDeliveryStatus.PENDING.value
                    )
                    .where(
                        sa.or_(
                            FlowRunAuditOutbox.next_delivery_at.is_(None),
                            FlowRunAuditOutbox.next_delivery_at <= now,
                        )
                    )
                    .order_by(
                        FlowRunAuditOutbox.next_delivery_at.asc().nullsfirst(),
                        FlowRunAuditOutbox.created_at.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        return [self._to_delivery_row(row) for row in rows]

    async def mark_delivery_succeeded(
        self,
        *,
        outbox_id: UUID,
        delivered_at: datetime,
        attempt_no: int,
    ) -> None:
        await self.session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                delivery_attempts=attempt_no,
                next_delivery_at=None,
                delivered_at=delivered_at,
                dead_lettered_at=None,
                delivery_last_error=None,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def record_delivery_failure(
        self,
        *,
        outbox_id: UUID,
        attempt_no: int,
        error_message: str,
        next_delivery_at: datetime | None,
        dead_lettered_at: datetime | None,
    ) -> None:
        delivery_status = (
            FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            if dead_lettered_at is not None
            else FlowOutboxDeliveryStatus.PENDING.value
        )
        await self.session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=delivery_status,
                delivery_attempts=attempt_no,
                next_delivery_at=next_delivery_at,
                delivered_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _to_delivery_row(row: FlowRunAuditOutbox) -> FlowRunAuditOutboxDeliveryRow:
        return FlowRunAuditOutboxDeliveryRow(
            id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            flow_run_id=row.flow_run_id,
            run_revision=row.run_revision,
            review_checkpoint_id=row.review_checkpoint_id,
            checkpoint_revision=row.checkpoint_revision,
            description=row.description,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            actor_id=row.actor_id,
            actor_type=row.actor_type,
            actor_api_key_id=row.actor_api_key_id,
            source=row.source,
            target_status=row.target_status,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            delivery_attempts=row.delivery_attempts,
        )
