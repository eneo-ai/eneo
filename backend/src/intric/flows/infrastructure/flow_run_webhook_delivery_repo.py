from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunWebhookDeliveries,
)
from intric.flows.runtime.step_execution_result import WebhookDeliveryIntent


@dataclass(frozen=True, slots=True)
class FlowRunWebhookDeliveryRow:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    idempotency_key: str
    payload_ref: str
    delivery_attempts: int
    claim_token: UUID
    created_at: datetime


class FlowRunWebhookDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_pending_delivery(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        intent: WebhookDeliveryIntent,
    ) -> UUID:
        row_id = await self.session.scalar(
            pg_insert(FlowRunWebhookDeliveries)
            .values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=intent.flow_run_id,
                step_id=intent.step_id,
                step_order=intent.step_order,
                attempt_no=intent.attempt_no,
                idempotency_key=intent.idempotency_key,
                payload_ref=intent.payload.value,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_run_webhook_deliveries_attempt",
            )
            .returning(FlowRunWebhookDeliveries.id)
        )
        if row_id is not None:
            return row_id

        existing_id = await self.session.scalar(
            sa.select(FlowRunWebhookDeliveries.id)
            .where(FlowRunWebhookDeliveries.flow_run_id == intent.flow_run_id)
            .where(FlowRunWebhookDeliveries.step_id == intent.step_id)
            .where(FlowRunWebhookDeliveries.attempt_no == intent.attempt_no)
            .where(FlowRunWebhookDeliveries.tenant_id == tenant_id)
        )
        if existing_id is None:
            raise RuntimeError("Webhook delivery insert did not return an id.")
        return existing_id

    async def claim_due_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
        claim_ttl_seconds: int,
    ) -> list[FlowRunWebhookDeliveryRow]:
        if limit <= 0:
            return []
        claim_token = uuid4()
        claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
        candidate_ids = (
            (
                await self.session.execute(
                    sa.select(FlowRunWebhookDeliveries.id)
                    .where(
                        FlowRunWebhookDeliveries.delivery_status
                        == FlowOutboxDeliveryStatus.PENDING.value
                    )
                    .where(
                        sa.or_(
                            FlowRunWebhookDeliveries.next_delivery_at.is_(None),
                            FlowRunWebhookDeliveries.next_delivery_at <= now,
                        )
                    )
                    .where(
                        sa.or_(
                            FlowRunWebhookDeliveries.claim_token.is_(None),
                            FlowRunWebhookDeliveries.claim_expires_at <= now,
                        )
                    )
                    .order_by(
                        FlowRunWebhookDeliveries.next_delivery_at.asc().nullsfirst(),
                        FlowRunWebhookDeliveries.created_at.asc(),
                    )
                    .limit(limit)
                    .with_for_update(
                        of=FlowRunWebhookDeliveries,
                        skip_locked=True,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidate_ids:
            return []

        rows = (
            (
                await self.session.execute(
                    sa.update(FlowRunWebhookDeliveries)
                    .where(FlowRunWebhookDeliveries.id.in_(candidate_ids))
                    .values(
                        claim_token=claim_token,
                        claimed_at=now,
                        claim_expires_at=claim_expires_at,
                        updated_at=datetime.now(timezone.utc),
                    )
                    .returning(FlowRunWebhookDeliveries)
                )
            )
            .scalars()
            .all()
        )
        return [self._to_delivery_row(row) for row in rows]

    async def mark_delivery_succeeded(
        self,
        *,
        delivery_id: UUID,
        claim_token: UUID,
        delivered_at: datetime,
        attempt_no: int,
    ) -> bool:
        result = await self.session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .where(FlowRunWebhookDeliveries.claim_token == claim_token)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                delivery_attempts=attempt_no,
                next_delivery_at=None,
                claim_token=None,
                claimed_at=None,
                claim_expires_at=None,
                delivered_at=delivered_at,
                dead_lettered_at=None,
                delivery_last_error=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def record_delivery_failure(
        self,
        *,
        delivery_id: UUID,
        claim_token: UUID,
        attempt_no: int,
        error_message: str,
        next_delivery_at: datetime | None,
        dead_lettered_at: datetime | None,
    ) -> bool:
        delivery_status = (
            FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            if dead_lettered_at is not None
            else FlowOutboxDeliveryStatus.PENDING.value
        )
        result = await self.session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .where(FlowRunWebhookDeliveries.claim_token == claim_token)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=delivery_status,
                delivery_attempts=attempt_no,
                next_delivery_at=next_delivery_at,
                claim_token=None,
                claimed_at=None,
                claim_expires_at=None,
                delivered_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    @staticmethod
    def _to_delivery_row(
        row: FlowRunWebhookDeliveries,
    ) -> FlowRunWebhookDeliveryRow:
        if row.claim_token is None:
            raise RuntimeError("Claimed webhook delivery row has no claim token.")
        return FlowRunWebhookDeliveryRow(
            id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            flow_run_id=row.flow_run_id,
            step_id=row.step_id,
            step_order=row.step_order,
            attempt_no=row.attempt_no,
            idempotency_key=row.idempotency_key,
            payload_ref=row.payload_ref,
            delivery_attempts=row.delivery_attempts,
            claim_token=row.claim_token,
            created_at=row.created_at,
        )
