"""Persistence owner for Flow run review checkpoints.

Callers own the active database transaction. Mutating methods that touch both a
parent Flow run row and its review checkpoint rows lock the run first, then
re-check checkpoint state predicates before mutating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.flow_tables import (
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepResults,
)
from eneo.flows.application.flow_run_recovery_policy import (
    start_flow_dispatch_epoch,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointAlreadyResumedError,
    FlowReviewCheckpointCancelledError,
    FlowReviewCheckpointExpiredError,
    FlowReviewCheckpointNotActiveError,
    FlowReviewCheckpointNotApprovedError,
    FlowReviewCheckpointNotFoundError,
    FlowReviewCheckpointRejectedError,
    FlowReviewCheckpointRunNotRunningError,
    FlowReviewCheckpointStaleRevisionError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewEditStepResultMissingError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
    FlowReviewRunNoLongerAwaitingReviewError,
    FlowReviewRunNotAwaitingReviewError,
)
from eneo.flows.enums import (
    ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES,
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
    FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.principal import FlowAuditActorFields, FlowPrincipal


@dataclass(frozen=True, slots=True)
class FlowRunReviewCheckpointOpenResult:
    checkpoint: FlowRunReviewCheckpoint
    run: FlowRun
    created: bool
    audit_outbox_id: UUID | None


@dataclass(frozen=True, slots=True)
class FlowRunReviewCheckpointResumeResult:
    checkpoint: FlowRunReviewCheckpoint
    run: FlowRun
    accepted: bool


_ACTIVE_REVIEW_CHECKPOINT_STATES = tuple(
    state.value for state in ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES
)
_RECONCILABLE_REVIEW_CHECKPOINT_STATES = tuple(
    state.value for state in RECONCILABLE_REVIEW_CHECKPOINT_STATES
)
_ReviewCheckpointTimestampColumn = Literal[
    "edited_at",
    "approved_at",
    "rejected_at",
    "resumed_at",
    "cancelled_at",
    "expired_at",
]
_REVIEW_CHECKPOINT_TIMESTAMP_BY_STATE: dict[
    FlowRunReviewCheckpointState,
    _ReviewCheckpointTimestampColumn,
] = {
    FlowRunReviewCheckpointState.EDITED: "edited_at",
    FlowRunReviewCheckpointState.APPROVED: "approved_at",
    FlowRunReviewCheckpointState.REJECTED: "rejected_at",
    FlowRunReviewCheckpointState.RESUMED: "resumed_at",
    FlowRunReviewCheckpointState.CANCELLED: "cancelled_at",
    FlowRunReviewCheckpointState.EXPIRED: "expired_at",
}


class FlowRunReviewCheckpointRepository:
    def __init__(
        self,
        *,
        session: AsyncSession,
        audit_outbox_repo: FlowRunAuditOutboxRepository,
    ):
        self.session = session
        self.audit_outbox_repo = audit_outbox_repo

    async def create_or_get_review_checkpoint_for_attempt(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        original_payload_json: FlowPersistedJsonObject | None,
        current_payload_json: FlowPersistedJsonObject | None,
        requester_principal_type: PrincipalType,
        requester_user_id: UUID | None,
        requester_service_id: UUID | None,
        review_mode: FlowStepReviewMode,
        output_type: FlowOutputType,
        step_label: str | None = None,
        output_contract_json: FlowPersistedJsonObject | None = None,
        next_step_ids: Sequence[UUID] | None = None,
        review_expires_after_seconds: int | None = None,
    ) -> FlowRunReviewCheckpoint:
        effective_expires_after_seconds = (
            review_expires_after_seconds
            if review_expires_after_seconds is not None
            else FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=effective_expires_after_seconds
        )
        next_step_ids_json = (
            [str(next_step_id) for next_step_id in next_step_ids]
            if next_step_ids is not None
            else None
        )
        checkpoint_row = await self.session.scalar(
            pg_insert(FlowRunReviewCheckpoints)
            .values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=flow_run_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                state=FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
                revision=1,
                schema_version=1,
                original_payload_json=original_payload_json,
                current_payload_json=current_payload_json,
                step_label=step_label,
                review_mode=review_mode.value,
                output_type=output_type.value,
                output_contract_json=output_contract_json,
                requester_principal_type=requester_principal_type.value,
                requester_user_id=requester_user_id,
                requester_service_id=requester_service_id,
                next_step_ids_json=next_step_ids_json,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_run_review_checkpoints_run_step_attempt",
            )
            .returning(FlowRunReviewCheckpoints)
        )
        if checkpoint_row is None:
            checkpoint_row = await self.session.scalar(
                sa.select(FlowRunReviewCheckpoints)
                .where(FlowRunReviewCheckpoints.flow_run_id == flow_run_id)
                .where(FlowRunReviewCheckpoints.step_id == step_id)
                .where(FlowRunReviewCheckpoints.attempt_no == attempt_no)
                .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
            )
        if checkpoint_row is None:
            raise FlowRunPersistenceInvariantError(
                operation="create_review_checkpoint",
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        return FlowRunReviewCheckpoint.model_validate(checkpoint_row)

    async def open_review_checkpoint_for_completed_step(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        requester_principal: FlowPrincipal,
        next_step_ids: Sequence[UUID],
        review_mode: FlowStepReviewMode,
        output_type: FlowOutputType,
        step_label: str | None = None,
        output_contract_json: FlowPersistedJsonObject | None = None,
        review_expires_after_seconds: int | None = None,
    ) -> FlowRunReviewCheckpointOpenResult:
        """Open a checkpoint for a step the caller resolved from the published run graph.

        The repository persists downstream step IDs for resume decisions, but it
        does not infer graph topology while holding run locks.
        """
        run_row = await self.session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_row is None:
            raise FlowRunNotFoundError(
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

        existing_checkpoint_row = await self.session.scalar(
            sa.select(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.flow_run_id == flow_run_id)
            .where(FlowRunReviewCheckpoints.step_id == step_id)
            .where(FlowRunReviewCheckpoints.attempt_no == attempt_no)
            .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
        )
        if existing_checkpoint_row is not None:
            return FlowRunReviewCheckpointOpenResult(
                checkpoint=FlowRunReviewCheckpoint.model_validate(
                    existing_checkpoint_row
                ),
                run=FlowRun.model_validate(run_row),
                created=False,
                audit_outbox_id=None,
            )

        if run_row.status != FlowRunStatus.RUNNING.value:
            raise FlowReviewCheckpointRunNotRunningError(status=run_row.status)

        active_checkpoint = await self.get_active_review_checkpoint(
            run_id=flow_run_id,
            tenant_id=tenant_id,
        )
        if active_checkpoint is not None:
            raise FlowReviewOpenBlockedByActiveCheckpointError(
                active_checkpoint_id=active_checkpoint.id
            )

        step_result_row = await self.session.scalar(
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .with_for_update()
        )
        if (
            step_result_row is None
            or step_result_row.status != FlowStepResultStatus.COMPLETED.value
            or step_result_row.current_attempt_no != attempt_no
        ):
            raise FlowReviewCheckpointStepResultIncompleteError(
                step_id=step_id,
                attempt_no=attempt_no,
            )

        checkpoint = await self.create_or_get_review_checkpoint_for_attempt(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            step_id=step_id,
            step_order=step_order,
            attempt_no=attempt_no,
            original_payload_json=step_result_row.output_payload_json,
            current_payload_json=step_result_row.output_payload_json,
            step_label=step_label,
            review_mode=review_mode,
            output_type=output_type,
            output_contract_json=output_contract_json,
            requester_principal_type=requester_principal.principal_type,
            requester_user_id=requester_principal.principal_user_id,
            requester_service_id=requester_principal.principal_service_id,
            next_step_ids=next_step_ids,
            review_expires_after_seconds=review_expires_after_seconds,
        )
        updated_run_row = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.RUNNING.value)
            .values(
                status=FlowRunStatus.AWAITING_REVIEW.value,
                revision=FlowRuns.revision + 1,
            )
            .returning(FlowRuns)
        )
        if updated_run_row is None:
            raise FlowReviewCheckpointRunNotRunningError()

        actor_fields = requester_principal.audit_actor_fields()
        outbox_id = await self.audit_outbox_repo.insert_review_checkpoint_audit_outbox(
            checkpoint=checkpoint,
            run_revision=updated_run_row.revision,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
            actor_id=actor_fields["actor_id"],
            actor_type=actor_fields["actor_type"],
            actor_api_key_id=actor_fields["actor_api_key_id"],
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED,
            target_state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        )
        return FlowRunReviewCheckpointOpenResult(
            checkpoint=checkpoint,
            run=FlowRun.model_validate(updated_run_row),
            created=True,
            audit_outbox_id=outbox_id,
        )

    async def get_active_review_checkpoint(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> FlowRunReviewCheckpoint | None:
        checkpoint_rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunReviewCheckpoints)
                    .where(FlowRunReviewCheckpoints.flow_run_id == run_id)
                    .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
                    .where(
                        FlowRunReviewCheckpoints.state.in_(
                            _ACTIVE_REVIEW_CHECKPOINT_STATES
                        )
                    )
                    .order_by(FlowRunReviewCheckpoints.created_at.desc())
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if not checkpoint_rows:
            return None
        if len(checkpoint_rows) > 1:
            raise FlowReviewMultipleActiveCheckpointsError()
        return FlowRunReviewCheckpoint.model_validate(checkpoint_rows[0])

    async def get_review_checkpoint_for_edit(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        expected_revision: int,
    ) -> FlowRunReviewCheckpoint:
        (
            checkpoint_row,
            run_row,
        ) = await self._load_review_checkpoint_and_run_rows_for_update(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
        )
        self._require_review_checkpoint_not_expired(checkpoint_row)
        self._require_review_run_waiting(run_row)
        self._require_review_checkpoint_revision(
            checkpoint_row=checkpoint_row,
            expected_revision=expected_revision,
        )
        self._require_review_checkpoint_state(
            checkpoint_row=checkpoint_row,
            allowed_states=(
                FlowRunReviewCheckpointState.AWAITING_REVIEW,
                FlowRunReviewCheckpointState.EDITED,
            ),
        )
        return FlowRunReviewCheckpoint.model_validate(checkpoint_row)

    async def edit_review_checkpoint_payload(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        expected_revision: int,
        current_payload_json: FlowPersistedJsonObject,
        principal: FlowPrincipal,
    ) -> FlowRunReviewCheckpoint:
        (
            checkpoint_row,
            run_row,
        ) = await self._load_review_checkpoint_and_run_rows_for_update(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
        )
        self._require_review_checkpoint_not_expired(checkpoint_row)
        self._require_review_run_waiting(run_row)
        self._require_review_checkpoint_revision(
            checkpoint_row=checkpoint_row,
            expected_revision=expected_revision,
        )
        self._require_review_checkpoint_state(
            checkpoint_row=checkpoint_row,
            allowed_states=(
                FlowRunReviewCheckpointState.AWAITING_REVIEW,
                FlowRunReviewCheckpointState.EDITED,
            ),
        )
        updated_checkpoint = await self._update_review_checkpoint_state(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            target_state=FlowRunReviewCheckpointState.EDITED,
            principal=principal,
            values={"current_payload_json": current_payload_json},
        )
        step_result_id = await self.session.scalar(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.flow_id == flow_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.step_id == checkpoint_row.step_id)
            .where(FlowStepResults.current_attempt_no == checkpoint_row.attempt_no)
            .values(output_payload_json=current_payload_json)
            .returning(FlowStepResults.id)
        )
        if step_result_id is None:
            raise FlowReviewEditStepResultMissingError()
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=updated_checkpoint,
            run_revision=run_row.revision,
            principal=principal,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_EDITED,
            target_state=FlowRunReviewCheckpointState.EDITED,
        )
        return updated_checkpoint

    async def approve_review_checkpoint(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        expected_revision: int,
        principal: FlowPrincipal,
    ) -> FlowRunReviewCheckpoint:
        (
            checkpoint_row,
            run_row,
        ) = await self._load_review_checkpoint_and_run_rows_for_update(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
        )
        self._require_review_checkpoint_not_expired(checkpoint_row)
        self._require_review_run_waiting(run_row)
        self._require_review_checkpoint_revision(
            checkpoint_row=checkpoint_row,
            expected_revision=expected_revision,
        )
        self._require_review_checkpoint_state(
            checkpoint_row=checkpoint_row,
            allowed_states=(
                FlowRunReviewCheckpointState.AWAITING_REVIEW,
                FlowRunReviewCheckpointState.EDITED,
            ),
        )
        updated_checkpoint = await self._update_review_checkpoint_state(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            target_state=FlowRunReviewCheckpointState.APPROVED,
            principal=principal,
        )
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=updated_checkpoint,
            run_revision=run_row.revision,
            principal=principal,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_APPROVED,
            target_state=FlowRunReviewCheckpointState.APPROVED,
        )
        return updated_checkpoint

    async def reject_review_checkpoint(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        expected_revision: int,
        reason: str,
        principal: FlowPrincipal,
    ) -> FlowRunReviewCheckpoint:
        (
            checkpoint_row,
            run_row,
        ) = await self._load_review_checkpoint_and_run_rows_for_update(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
        )
        self._require_review_checkpoint_not_expired(checkpoint_row)
        self._require_review_run_waiting(run_row)
        self._require_review_checkpoint_revision(
            checkpoint_row=checkpoint_row,
            expected_revision=expected_revision,
        )
        self._require_review_checkpoint_state(
            checkpoint_row=checkpoint_row,
            allowed_states=(
                FlowRunReviewCheckpointState.AWAITING_REVIEW,
                FlowRunReviewCheckpointState.EDITED,
            ),
        )
        updated_checkpoint = await self._update_review_checkpoint_state(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            target_state=FlowRunReviewCheckpointState.REJECTED,
            principal=principal,
        )
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=updated_checkpoint,
            run_revision=run_row.revision,
            principal=principal,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_REJECTED,
            target_state=FlowRunReviewCheckpointState.REJECTED,
            error_code=FlowApiErrorCode.REVIEW_REJECTED.value,
            error_message=reason,
        )
        return updated_checkpoint

    async def resume_review_checkpoint(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        expected_revision: int,
        resume_idempotency_key: str,
        principal: FlowPrincipal,
    ) -> FlowRunReviewCheckpointResumeResult:
        (
            checkpoint_row,
            run_row,
        ) = await self._load_review_checkpoint_and_run_rows_for_update(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
        )
        self._require_review_checkpoint_not_expired(checkpoint_row)
        if checkpoint_row.state == FlowRunReviewCheckpointState.RESUMED.value:
            if checkpoint_row.resume_idempotency_key == resume_idempotency_key:
                return FlowRunReviewCheckpointResumeResult(
                    checkpoint=FlowRunReviewCheckpoint.model_validate(checkpoint_row),
                    run=FlowRun.model_validate(run_row),
                    accepted=False,
                )
            raise FlowReviewCheckpointAlreadyResumedError()
        self._require_review_resume_source_state(checkpoint_row)
        self._require_review_run_waiting(run_row)
        self._require_review_checkpoint_revision(
            checkpoint_row=checkpoint_row,
            expected_revision=expected_revision,
        )
        updated_checkpoint = await self._update_review_checkpoint_state(
            checkpoint_id=checkpoint_id,
            tenant_id=tenant_id,
            target_state=FlowRunReviewCheckpointState.RESUMED,
            principal=principal,
            values={"resume_idempotency_key": resume_idempotency_key},
        )
        now_utc = datetime.now(timezone.utc)
        updated_run_row = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.AWAITING_REVIEW.value)
            .values(
                status=FlowRunStatus.QUEUED.value,
                revision=FlowRuns.revision + 1,
                **start_flow_dispatch_epoch(now_utc),
            )
            .returning(FlowRuns)
        )
        if updated_run_row is None:
            raise FlowReviewRunNoLongerAwaitingReviewError()
        run = FlowRun.model_validate(updated_run_row)
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=updated_checkpoint,
            run_revision=run.revision,
            principal=principal,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_RESUMED,
            target_state=FlowRunReviewCheckpointState.RESUMED,
        )
        return FlowRunReviewCheckpointResumeResult(
            checkpoint=updated_checkpoint,
            run=run,
            accepted=True,
        )

    async def cancel_active_review_checkpoint_for_terminal_run(
        self,
        *,
        tenant_id: UUID,
        flow_run_id: UUID,
        run_revision: int,
        principal: FlowPrincipal | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> FlowRunReviewCheckpoint | None:
        """Cancel after the caller has locked and terminalized the parent run."""
        now_utc = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "state": FlowRunReviewCheckpointState.CANCELLED.value,
            "revision": FlowRunReviewCheckpoints.revision + 1,
            "cancelled_at": now_utc,
        }
        if principal is not None:
            values["decided_by_principal_type"] = principal.principal_type.value
            values["decided_by_user_id"] = principal.principal_user_id
            values["decided_by_service_id"] = principal.principal_service_id
        checkpoint_row = await self.session.scalar(
            sa.update(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.flow_run_id == flow_run_id)
            .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
            .where(FlowRunReviewCheckpoints.state.in_(_ACTIVE_REVIEW_CHECKPOINT_STATES))
            .values(**values)
            .returning(FlowRunReviewCheckpoints)
        )
        if checkpoint_row is None:
            return None
        checkpoint = FlowRunReviewCheckpoint.model_validate(checkpoint_row)
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=checkpoint,
            run_revision=run_revision,
            principal=principal,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_CANCELLED,
            target_state=FlowRunReviewCheckpointState.CANCELLED,
            error_code=error_code,
            error_message=error_message,
        )
        return checkpoint

    async def list_expired_review_checkpoints(
        self,
        *,
        tenant_id: UUID,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[FlowRunReviewCheckpoint]:
        # Discovery is intentionally read-only. The mutator below owns run-first
        # locking and CAS predicates so review decisions cannot deadlock with expiry.
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunReviewCheckpoints)
                    .join(
                        FlowRuns,
                        sa.and_(
                            FlowRuns.id == FlowRunReviewCheckpoints.flow_run_id,
                            FlowRuns.tenant_id == FlowRunReviewCheckpoints.tenant_id,
                        ),
                    )
                    .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
                    .where(FlowRunReviewCheckpoints.expires_at.is_not(None))
                    .where(FlowRunReviewCheckpoints.expires_at <= expires_before)
                    .where(
                        FlowRunReviewCheckpoints.state.in_(
                            _RECONCILABLE_REVIEW_CHECKPOINT_STATES
                        )
                    )
                    .where(FlowRuns.status == FlowRunStatus.AWAITING_REVIEW.value)
                    .order_by(
                        FlowRunReviewCheckpoints.expires_at.asc(),
                        FlowRunReviewCheckpoints.id.asc(),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [FlowRunReviewCheckpoint.model_validate(row) for row in rows]

    async def expire_review_checkpoint_for_reconciliation(
        self,
        *,
        checkpoint_id: UUID,
        flow_run_id: UUID,
        tenant_id: UUID,
        expires_before: datetime,
    ) -> FlowRunReviewCheckpoint | None:
        run_row = await self.session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_row is None:
            raise FlowRunNotFoundError(
                run_id=flow_run_id,
                tenant_id=tenant_id,
            )
        if run_row.status != FlowRunStatus.AWAITING_REVIEW.value:
            return None

        now_utc = datetime.now(timezone.utc)
        checkpoint_row = await self.session.scalar(
            sa.update(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.id == checkpoint_id)
            .where(FlowRunReviewCheckpoints.flow_run_id == flow_run_id)
            .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
            .where(FlowRunReviewCheckpoints.expires_at.is_not(None))
            .where(FlowRunReviewCheckpoints.expires_at <= expires_before)
            .where(
                FlowRunReviewCheckpoints.state.in_(
                    _RECONCILABLE_REVIEW_CHECKPOINT_STATES
                )
            )
            .values(
                state=FlowRunReviewCheckpointState.EXPIRED.value,
                revision=FlowRunReviewCheckpoints.revision + 1,
                expired_at=now_utc,
            )
            .returning(FlowRunReviewCheckpoints)
        )
        if checkpoint_row is None:
            return None
        checkpoint = FlowRunReviewCheckpoint.model_validate(checkpoint_row)
        await self._insert_review_checkpoint_transition_outbox(
            checkpoint=checkpoint,
            run_revision=run_row.revision,
            principal=None,
            action=ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EXPIRED,
            source=FlowRunLifecycleSource.REVIEW_CHECKPOINT_EXPIRED,
            target_state=FlowRunReviewCheckpointState.EXPIRED,
            error_code=FlowApiErrorCode.REVIEW_EXPIRED.value,
            error_message=FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
        )
        return checkpoint

    async def _load_review_checkpoint_and_run_rows_for_update(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
    ) -> tuple[FlowRunReviewCheckpoints, FlowRuns]:
        run_row = await self.session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_row is None:
            raise FlowRunNotFoundError(
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        checkpoint_row = await self.session.scalar(
            sa.select(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.id == checkpoint_id)
            .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
            .where(FlowRunReviewCheckpoints.flow_id == flow_id)
            .where(FlowRunReviewCheckpoints.flow_run_id == flow_run_id)
            .with_for_update()
        )
        if checkpoint_row is None:
            raise FlowReviewCheckpointNotFoundError()
        return checkpoint_row, run_row

    @staticmethod
    def _require_review_run_waiting(run_row: FlowRuns) -> None:
        if run_row.status == FlowRunStatus.AWAITING_REVIEW.value:
            return
        raise FlowReviewRunNotAwaitingReviewError(status=run_row.status)

    @staticmethod
    def _require_review_checkpoint_not_expired(
        checkpoint_row: FlowRunReviewCheckpoints,
    ) -> None:
        if checkpoint_row.state == FlowRunReviewCheckpointState.EXPIRED.value:
            raise FlowReviewCheckpointExpiredError(
                checkpoint_id=checkpoint_row.id,
                state=checkpoint_row.state,
                expires_at=checkpoint_row.expires_at,
                expired_at=checkpoint_row.expired_at,
            )
        if checkpoint_row.state not in _RECONCILABLE_REVIEW_CHECKPOINT_STATES:
            return
        if checkpoint_row.expires_at is None:
            return
        expires_at = checkpoint_row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc):
            return
        raise FlowReviewCheckpointExpiredError(
            checkpoint_id=checkpoint_row.id,
            state=checkpoint_row.state,
            expires_at=expires_at,
            expired_at=checkpoint_row.expired_at,
        )

    @staticmethod
    def _require_review_checkpoint_revision(
        *,
        checkpoint_row: FlowRunReviewCheckpoints,
        expected_revision: int,
    ) -> None:
        if checkpoint_row.revision == expected_revision:
            return
        raise FlowReviewCheckpointStaleRevisionError(
            expected_checkpoint_revision=expected_revision,
            current_checkpoint_revision=checkpoint_row.revision,
        )

    @staticmethod
    def _require_review_checkpoint_state(
        *,
        checkpoint_row: FlowRunReviewCheckpoints,
        allowed_states: Sequence[FlowRunReviewCheckpointState],
    ) -> None:
        allowed_values = tuple(state.value for state in allowed_states)
        if checkpoint_row.state in allowed_values:
            return
        raise FlowReviewCheckpointNotActiveError(state=checkpoint_row.state)

    @staticmethod
    def _require_review_resume_source_state(
        checkpoint_row: FlowRunReviewCheckpoints,
    ) -> None:
        state = checkpoint_row.state
        if state == FlowRunReviewCheckpointState.APPROVED.value:
            return
        if state == FlowRunReviewCheckpointState.REJECTED.value:
            raise FlowReviewCheckpointRejectedError()
        if state == FlowRunReviewCheckpointState.CANCELLED.value:
            raise FlowReviewCheckpointCancelledError()
        if state == FlowRunReviewCheckpointState.EXPIRED.value:
            raise FlowReviewCheckpointExpiredError(
                checkpoint_id=checkpoint_row.id,
                state=checkpoint_row.state,
                expires_at=checkpoint_row.expires_at,
                expired_at=checkpoint_row.expired_at,
            )
        if state == FlowRunReviewCheckpointState.RESUMED.value:
            raise FlowReviewCheckpointAlreadyResumedError()
        raise FlowReviewCheckpointNotApprovedError(state=state)

    async def _update_review_checkpoint_state(
        self,
        *,
        checkpoint_id: UUID,
        tenant_id: UUID,
        target_state: FlowRunReviewCheckpointState,
        principal: FlowPrincipal,
        values: dict[str, Any] | None = None,
    ) -> FlowRunReviewCheckpoint:
        update_values: dict[str, Any] = {
            "state": target_state.value,
            "revision": FlowRunReviewCheckpoints.revision + 1,
            "decided_by_principal_type": principal.principal_type.value,
            "decided_by_user_id": principal.principal_user_id,
            "decided_by_service_id": principal.principal_service_id,
        }
        timestamp_field = _REVIEW_CHECKPOINT_TIMESTAMP_BY_STATE.get(target_state)
        if timestamp_field is not None:
            update_values[timestamp_field] = datetime.now(timezone.utc)
        if values is not None:
            update_values.update(values)
        checkpoint_row = await self.session.scalar(
            sa.update(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.id == checkpoint_id)
            .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
            .values(**update_values)
            .returning(FlowRunReviewCheckpoints)
        )
        if checkpoint_row is None:
            raise FlowReviewCheckpointNotFoundError()
        return FlowRunReviewCheckpoint.model_validate(checkpoint_row)

    async def _insert_review_checkpoint_transition_outbox(
        self,
        *,
        checkpoint: FlowRunReviewCheckpoint,
        run_revision: int,
        principal: FlowPrincipal | None,
        action: ActionType,
        source: FlowRunLifecycleSource,
        target_state: FlowRunReviewCheckpointState,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> UUID:
        actor_fields: FlowAuditActorFields = (
            principal.audit_actor_fields()
            if principal is not None
            else {
                "actor_id": None,
                "actor_type": ActorType.SYSTEM,
                "actor_api_key_id": None,
            }
        )
        return await self.audit_outbox_repo.insert_review_checkpoint_audit_outbox(
            checkpoint=checkpoint,
            run_revision=run_revision,
            action=action,
            actor_id=actor_fields["actor_id"],
            actor_type=actor_fields["actor_type"],
            actor_api_key_id=actor_fields["actor_api_key_id"],
            source=source,
            target_state=target_state,
            error_code=error_code,
            error_message=error_message,
        )

    async def list_review_checkpoints_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowRunReviewCheckpoint]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunReviewCheckpoints)
                    .where(FlowRunReviewCheckpoints.flow_run_id == run_id)
                    .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
                    .order_by(
                        FlowRunReviewCheckpoints.step_order.asc(),
                        FlowRunReviewCheckpoints.attempt_no.asc(),
                        FlowRunReviewCheckpoints.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [FlowRunReviewCheckpoint.model_validate(row) for row in rows]
