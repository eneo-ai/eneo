from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_metadata import (
    deleted_actor_snapshot,
    service_principal_actor_snapshot,
    system_actor_snapshot,
    user_actor_snapshot,
)
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
)
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.users_table import Users
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
)
from eneo.flows.domain.flow_audit_outbox_limits import (
    FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX,
)
from eneo.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.principal import FlowPrincipal


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
    payload_sha256_before: str | None = None
    payload_sha256_after: str | None = None
    actor_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxDeadLetterRow:
    outbox_id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    action: str
    source: str
    delivery_attempts: int
    dead_lettered_at: datetime
    delivery_last_error: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxDeadLetterPage:
    items: tuple[FlowRunAuditOutboxDeadLetterRow, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxRedriveTransition:
    outbox_id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    previous_delivery_attempts: int
    previous_dead_lettered_at: datetime
    previous_delivery_last_error: str | None
    next_delivery_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxRedriveStateConflict:
    delivery_status: str


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxRedriveGenerationConflict:
    current_dead_lettered_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxRedriveInspection:
    outbox_id: UUID
    delivery_status: str
    dead_lettered_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CapturedActor:
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None
    snapshot: dict[str, Any]


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
        principal: FlowPrincipal | None,
        source: FlowRunLifecycleSource,
        target_status: FlowRunStatus,
        error_code: str | None,
        error_message: str | None,
    ) -> UUID:
        actor = await self._capture_actor(principal=principal, source=source)
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
                actor_id=actor.actor_id,
                actor_type=actor.actor_type.value,
                actor_api_key_id=actor.actor_api_key_id,
                actor_snapshot=actor.snapshot,
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
        principal: FlowPrincipal | None,
        source: FlowRunLifecycleSource,
        target_state: FlowRunReviewCheckpointState,
        error_code: str | None = None,
        error_message: str | None = None,
        payload_sha256_before: str | None = None,
        payload_sha256_after: str | None = None,
    ) -> UUID:
        actor = await self._capture_actor(principal=principal, source=source)
        outbox_id = await self.session.scalar(
            sa.insert(FlowRunAuditOutbox)
            .values(
                tenant_id=checkpoint.tenant_id,
                flow_id=checkpoint.flow_id,
                flow_run_id=checkpoint.flow_run_id,
                run_revision=run_revision,
                review_checkpoint_id=checkpoint.id,
                checkpoint_revision=checkpoint.revision,
                payload_sha256_before=payload_sha256_before,
                payload_sha256_after=payload_sha256_after,
                description=flow_run_audit_description(action=action, source=source),
                action=action.value,
                entity_type=EntityType.FLOW_RUN_REVIEW_CHECKPOINT.value,
                entity_id=checkpoint.id,
                actor_id=actor.actor_id,
                actor_type=actor.actor_type.value,
                actor_api_key_id=actor.actor_api_key_id,
                actor_snapshot=actor.snapshot,
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

    async def _capture_actor(
        self, *, principal: FlowPrincipal | None, source: FlowRunLifecycleSource
    ) -> _CapturedActor:
        """Who acted, from the stable principal: None is a system transition.

        The actor FK columns follow the principal's audit fields; a user or key
        row already deleted leaves its column NULL. FOR KEY SHARE is the lock the
        actor FK check takes on insert, taken at the read so the row cannot be
        deleted before the insert.
        """
        if principal is None:
            return _CapturedActor(
                None, ActorType.SYSTEM, None, system_actor_snapshot(source.value)
            )
        if principal.principal_type == PrincipalType.USER:
            user_id = principal.principal_user_id
            assert user_id is not None
            user = (
                await self.session.execute(
                    sa.select(Users.id, Users.username, Users.email)
                    .where(Users.id == user_id)
                    .with_for_update(read=True, key_share=True)
                )
            ).one_or_none()
            if user is None:
                gone = deleted_actor_snapshot("user", user_id)
                return _CapturedActor(None, ActorType.USER, None, gone)
            snapshot = user_actor_snapshot(user)
            return _CapturedActor(user_id, ActorType.USER, None, snapshot)
        service_id = principal.principal_service_id
        assert service_id is not None
        key_id = principal.actor_api_key_id
        live_key_id = None
        if key_id is not None:
            live_key_id = await self.session.scalar(
                sa.select(ApiKeysV2.id)
                .where(ApiKeysV2.id == key_id)
                .with_for_update(read=True, key_share=True)
            )
        service = (
            await self.session.execute(
                sa.select(
                    ServicePrincipals.id,
                    ServicePrincipals.display_name,
                    ServicePrincipals.scope_type,
                    ServicePrincipals.scope_id,
                ).where(ServicePrincipals.id == service_id)
            )
        ).one_or_none()
        snapshot = (
            deleted_actor_snapshot("service_principal", service_id)
            if service is None
            else service_principal_actor_snapshot(service, actor_api_key_id=key_id)
        )
        if live_key_id is None:
            return _CapturedActor(None, ActorType.SYSTEM, None, snapshot)
        return _CapturedActor(None, ActorType.API_KEY, live_key_id, snapshot)

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

    async def list_dead_letters(
        self,
        *,
        limit: int,
        offset: int,
    ) -> FlowRunAuditOutboxDeadLetterPage:
        if not 1 <= limit <= FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX:
            raise ValueError(
                "Flow audit outbox dead-letter list limit must be between 1 and "
                f"{FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX}."
            )
        if offset < 0:
            raise ValueError(
                "Flow audit outbox dead-letter list offset cannot be negative."
            )

        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunAuditOutbox)
                    .where(
                        FlowRunAuditOutbox.delivery_status
                        == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
                    )
                    .order_by(
                        FlowRunAuditOutbox.dead_lettered_at.asc().nullsfirst(),
                        FlowRunAuditOutbox.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        items = tuple(self._to_dead_letter_row(row) for row in rows[:limit])
        return FlowRunAuditOutboxDeadLetterPage(
            items=items,
            has_more=len(rows) > limit,
        )

    async def inspect_redrive(
        self,
        *,
        outbox_id: UUID,
    ) -> FlowRunAuditOutboxRedriveInspection | None:
        row = await self.session.scalar(
            sa.select(FlowRunAuditOutbox).where(FlowRunAuditOutbox.id == outbox_id)
        )
        if row is None:
            return None
        return FlowRunAuditOutboxRedriveInspection(
            outbox_id=row.id,
            delivery_status=row.delivery_status,
            dead_lettered_at=row.dead_lettered_at,
        )

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

    async def redrive_dead_lettered(
        self,
        *,
        outbox_id: UUID,
        expected_dead_lettered_at: datetime,
        now: datetime,
    ) -> (
        FlowRunAuditOutboxRedriveTransition
        | FlowRunAuditOutboxRedriveStateConflict
        | FlowRunAuditOutboxRedriveGenerationConflict
        | None
    ):
        row = await self.session.scalar(
            sa.select(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .with_for_update()
        )
        if row is None:
            return None

        previous_status = row.delivery_status
        if previous_status != FlowOutboxDeliveryStatus.DEAD_LETTERED.value:
            return FlowRunAuditOutboxRedriveStateConflict(
                delivery_status=previous_status,
            )
        if row.dead_lettered_at is None:
            raise RuntimeError("Dead-lettered Flow audit outbox row has no generation.")
        if row.dead_lettered_at != expected_dead_lettered_at:
            return FlowRunAuditOutboxRedriveGenerationConflict(
                current_dead_lettered_at=row.dead_lettered_at,
            )

        transition = FlowRunAuditOutboxRedriveTransition(
            outbox_id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            flow_run_id=row.flow_run_id,
            previous_delivery_attempts=row.delivery_attempts,
            previous_dead_lettered_at=row.dead_lettered_at,
            previous_delivery_last_error=row.delivery_last_error,
            next_delivery_at=now,
        )

        redriven_id = await self.session.scalar(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .where(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            )
            .where(FlowRunAuditOutbox.dead_lettered_at == expected_dead_lettered_at)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=now,
                delivered_at=None,
                dead_lettered_at=None,
                delivery_last_error=None,
                updated_at=now,
            )
            .returning(FlowRunAuditOutbox.id)
        )
        if redriven_id is None:
            raise RuntimeError("Locked Flow audit outbox redrive lost its transition.")
        return transition

    @staticmethod
    def _to_dead_letter_row(
        row: FlowRunAuditOutbox,
    ) -> FlowRunAuditOutboxDeadLetterRow:
        if row.dead_lettered_at is None:
            raise RuntimeError("Dead-lettered Flow audit outbox row has no generation.")
        return FlowRunAuditOutboxDeadLetterRow(
            outbox_id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            flow_run_id=row.flow_run_id,
            action=row.action,
            source=row.source,
            delivery_attempts=row.delivery_attempts,
            dead_lettered_at=row.dead_lettered_at,
            delivery_last_error=row.delivery_last_error,
            created_at=row.created_at,
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
            payload_sha256_before=row.payload_sha256_before,
            payload_sha256_after=row.payload_sha256_after,
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
            actor_snapshot=row.actor_snapshot,
        )
