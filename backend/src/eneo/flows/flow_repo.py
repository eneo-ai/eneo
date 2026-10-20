"""Persistence for flows, versions, runs, step results, attempts, checkpoints.

Every write is a plain statement; the compare-and-swap helpers return whether
the row moved so a slow worker, the stale-run reconciler and a reviewer can
never resurrect or double-decide a row. The repository holds no business
rules: it does not know what a step kind is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FLOW_REVIEW_CHECKPOINT_ACTIVE_STATES,
    FlowRunFiles,
    FlowRunReviewCheckpoints,
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from eneo.flows.flow_models import (
    FlowRunStatus,
    ReviewCheckpointState,
    StepAttemptStatus,
    StepResultStatus,
)

ERROR_MESSAGE_MAX = 2000


def _now() -> datetime:
    return datetime.now(UTC)


def _rowcount(result: object) -> int:
    return cast(CursorResult[Any], result).rowcount


def _clip(text: Optional[str]) -> Optional[str]:
    return text[:ERROR_MESSAGE_MAX] if text else None


@dataclass(frozen=True)
class FlowListRow:
    flow: Flows
    last_run: Optional[FlowRuns]


@dataclass(frozen=True)
class RunFileEntry:
    file_id: UUID
    role: str
    field_key: Optional[str] = None
    step_id: Optional[UUID] = None
    ordinal: int = 0


@dataclass(frozen=True)
class RunFileRow:
    file_id: UUID
    name: str
    mimetype: Optional[str]
    size: Optional[int]
    role: str
    field_key: Optional[str]
    step_id: Optional[UUID]


class FlowRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Flows ---

    async def add_flow(
        self,
        *,
        name: str,
        description: Optional[str],
        definition: dict[str, Any],
        space_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: Optional[UUID] = None,
    ) -> Flows:
        stmt = (
            sa.insert(Flows)
            .values(
                name=name,
                description=description,
                definition=definition,
                space_id=space_id,
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            .returning(Flows)
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_flow(
        self, flow_id: UUID, tenant_id: UUID, *, include_deleted: bool = False
    ) -> Optional[Flows]:
        stmt = sa.select(Flows).where(Flows.id == flow_id, Flows.tenant_id == tenant_id)
        if not include_deleted:
            stmt = stmt.where(Flows.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_flows(self, space_id: UUID, tenant_id: UUID) -> list[FlowListRow]:
        last_run_id = (
            sa.select(FlowRuns.id)
            .where(FlowRuns.flow_id == Flows.id)
            .order_by(FlowRuns.created_at.desc(), FlowRuns.id.desc())
            .limit(1)
            .correlate(Flows)
            .scalar_subquery()
        )
        stmt = (
            sa.select(Flows, FlowRuns)
            .outerjoin(FlowRuns, FlowRuns.id == last_run_id)
            .where(
                Flows.space_id == space_id,
                Flows.tenant_id == tenant_id,
                Flows.deleted_at.is_(None),
            )
            .order_by(Flows.created_at, Flows.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [FlowListRow(flow=flow, last_run=run) for flow, run in rows]

    async def update_flow(
        self,
        flow_id: UUID,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        definition: Optional[dict[str, Any]] = None,
    ) -> None:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if definition is not None:
            values["definition"] = definition
        if not values:
            return
        values["updated_at"] = _now()
        await self.session.execute(
            sa.update(Flows).where(Flows.id == flow_id).values(**values)
        )

    async def soft_delete_flow(self, flow_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id, Flows.deleted_at.is_(None))
            .values(deleted_at=_now())
        )
        return _rowcount(result) == 1

    async def set_conversation_id(
        self, flow_id: UUID, conversation_id: Optional[UUID]
    ) -> None:
        await self.session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(conversation_id=conversation_id)
        )

    # --- Versions ---

    async def add_version(
        self,
        *,
        flow_id: UUID,
        version: int,
        definition: dict[str, Any],
        published_by_user_id: Optional[UUID],
    ) -> FlowVersions:
        row = (
            await self.session.execute(
                sa.insert(FlowVersions)
                .values(
                    flow_id=flow_id,
                    version=version,
                    definition=definition,
                    published_by_user_id=published_by_user_id,
                )
                .returning(FlowVersions)
            )
        ).scalar_one()
        await self.session.execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(published_version=version, updated_at=_now())
        )
        return row

    async def get_version(self, flow_id: UUID, version: int) -> Optional[FlowVersions]:
        stmt = sa.select(FlowVersions).where(
            FlowVersions.flow_id == flow_id, FlowVersions.version == version
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # --- Runs ---

    async def add_run(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        tenant_id: UUID,
        principal_type: str,
        principal_user_id: Optional[UUID],
        principal_service_id: Optional[UUID] = None,
        created_by_api_key_id: Optional[UUID] = None,
        run_label: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        input_payload_json: Optional[dict[str, Any]] = None,
    ) -> FlowRuns:
        stmt = (
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                tenant_id=tenant_id,
                principal_type=principal_type,
                principal_user_id=principal_user_id,
                principal_service_id=principal_service_id,
                created_by_api_key_id=created_by_api_key_id,
                status=FlowRunStatus.QUEUED.value,
                run_label=run_label,
                idempotency_key=idempotency_key,
                input_payload_json=input_payload_json,
            )
            .returning(FlowRuns.id)
        )
        run_id = (await self.session.execute(stmt)).scalar_one()
        run = await self.get_run(run_id, tenant_id)
        assert run is not None
        return run

    def _run_query(self) -> sa.Select[tuple[FlowRuns]]:
        return sa.select(FlowRuns).options(
            selectinload(FlowRuns.step_results), selectinload(FlowRuns.files)
        )

    async def get_run(self, run_id: UUID, tenant_id: UUID) -> Optional[FlowRuns]:
        stmt = (
            self._run_query()
            .where(FlowRuns.id == run_id, FlowRuns.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_run_by_idempotency_key(
        self, flow_id: UUID, idempotency_key: str
    ) -> Optional[FlowRuns]:
        stmt = self._run_query().where(
            FlowRuns.flow_id == flow_id,
            FlowRuns.idempotency_key == idempotency_key,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_runs(
        self, flow_id: UUID, tenant_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[FlowRuns], int]:
        where = (FlowRuns.flow_id == flow_id, FlowRuns.tenant_id == tenant_id)
        total = (
            await self.session.execute(
                sa.select(sa.func.count()).select_from(FlowRuns).where(*where)
            )
        ).scalar_one()
        stmt = (
            sa.select(FlowRuns)
            .where(*where)
            .order_by(FlowRuns.created_at.desc(), FlowRuns.id.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = list((await self.session.execute(stmt)).scalars().all())
        return runs, int(total)

    async def update_run_status(
        self,
        run_id: UUID,
        status: FlowRunStatus,
        *,
        output_payload_json: Optional[dict[str, Any]] = None,
        error: Optional[dict[str, Any]] = None,
        expected_statuses: Optional[tuple[FlowRunStatus, ...]] = None,
    ) -> bool:
        """Move a run to ``status``.

        With ``expected_statuses`` this is a compare-and-swap: the write only
        applies from one of those states, so a slow worker cannot resurrect a
        run the reconciler or a reviewer already terminalized.
        """
        now = _now()
        values: dict[str, Any] = {"status": status.value, "updated_at": now}
        if output_payload_json is not None:
            values["output_payload_json"] = output_payload_json
        if error is not None:
            values["error_json"] = error
        if status == FlowRunStatus.RUNNING:
            values["started_at"] = sa.func.coalesce(FlowRuns.started_at, now)
            values["heartbeat_at"] = now
        if status.is_terminal:
            values["finished_at"] = now
        if status == FlowRunStatus.CANCELLED:
            values["cancelled_at"] = now
        stmt = sa.update(FlowRuns).where(FlowRuns.id == run_id).values(**values)
        if expected_statuses is not None:
            stmt = stmt.where(FlowRuns.status.in_([s.value for s in expected_statuses]))
        return _rowcount(await self.session.execute(stmt)) == 1

    async def touch_heartbeat(self, run_id: UUID) -> bool:
        """Refresh the heartbeat while running; False once the lease is gone."""
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(
                FlowRuns.id == run_id,
                FlowRuns.status == FlowRunStatus.RUNNING.value,
            )
            .values(heartbeat_at=_now())
        )
        return _rowcount(result) == 1

    async def set_run_job(self, run_id: UUID, job_id: UUID) -> None:
        await self.session.execute(
            sa.update(FlowRuns).where(FlowRuns.id == run_id).values(job_id=job_id)
        )

    async def get_stale_running_runs(
        self, *, stale_before: datetime, limit: int = 20
    ) -> list[FlowRuns]:
        stmt = (
            sa.select(FlowRuns)
            .where(
                FlowRuns.status == FlowRunStatus.RUNNING.value,
                sa.func.coalesce(FlowRuns.heartbeat_at, FlowRuns.updated_at)
                < stale_before,
            )
            .order_by(FlowRuns.heartbeat_at.asc().nullsfirst())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # --- Run files ---

    async def add_run_files(self, run_id: UUID, entries: list[RunFileEntry]) -> None:
        for entry in entries:
            await self.session.execute(
                sa.insert(FlowRunFiles).values(
                    flow_run_id=run_id,
                    file_id=entry.file_id,
                    role=entry.role,
                    field_key=entry.field_key,
                    step_id=entry.step_id,
                    ordinal=entry.ordinal,
                )
            )

    async def list_run_files(self, run_id: UUID) -> list[RunFileRow]:
        stmt = (
            sa.select(
                FlowRunFiles.file_id,
                Files.name,
                Files.mimetype,
                # Byte sizes live in object content; the run API leaves size null.
                sa.null().label("size"),
                FlowRunFiles.role,
                FlowRunFiles.field_key,
                FlowRunFiles.step_id,
            )
            .join(Files, Files.id == FlowRunFiles.file_id)
            .where(FlowRunFiles.flow_run_id == run_id)
            .order_by(FlowRunFiles.ordinal, FlowRunFiles.created_at)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            RunFileRow(
                file_id=file_id,
                name=name,
                mimetype=mimetype,
                size=size,
                role=role,
                field_key=field_key,
                step_id=step_id,
            )
            for file_id, name, mimetype, size, role, field_key, step_id in rows
        ]

    # --- Step results ---

    async def seed_step_results(
        self, run_id: UUID, steps: list[tuple[UUID, int]]
    ) -> None:
        for step_id, order in steps:
            await self.session.execute(
                sa.insert(FlowStepResults).values(
                    flow_run_id=run_id,
                    step_id=step_id,
                    step_order=order,
                    status=StepResultStatus.PENDING.value,
                )
            )

    async def get_step_results(self, run_id: UUID) -> list[FlowStepResults]:
        stmt = (
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .order_by(FlowStepResults.step_order)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_step_result(
        self, run_id: UUID, step_id: UUID
    ) -> Optional[FlowStepResults]:
        stmt = (
            sa.select(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def claim_step_result(self, run_id: UUID, step_id: UUID) -> bool:
        """Claim a pending step (CAS pending -> running).

        False when the step is no longer pending: already completed before a
        crash, or claimed by a worker that never resolved it.
        """
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
                FlowStepResults.status == StepResultStatus.PENDING.value,
            )
            .values(status=StepResultStatus.RUNNING.value, started_at=_now())
        )
        return _rowcount(result) == 1

    async def open_attempt(self, run_id: UUID, step_id: UUID) -> int:
        next_no = (
            sa.select(sa.func.coalesce(sa.func.max(FlowStepAttempts.attempt_no), 0) + 1)
            .where(
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.step_id == step_id,
            )
            .scalar_subquery()
        )
        attempt_no = (
            await self.session.execute(
                sa.insert(FlowStepAttempts)
                .values(
                    flow_run_id=run_id,
                    step_id=step_id,
                    attempt_no=next_no,
                    status=StepAttemptStatus.STARTED.value,
                )
                .returning(FlowStepAttempts.attempt_no)
            )
        ).scalar_one()
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
            )
            .values(current_attempt_no=attempt_no)
        )
        return int(attempt_no)

    async def finish_attempt(
        self,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        *,
        status: StepAttemptStatus,
        error: Optional[str] = None,
    ) -> bool:
        """Close a started attempt (CAS). False when it was already closed,
        e.g. reconciled to outcome_unknown."""
        result = await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.step_id == step_id,
                FlowStepAttempts.attempt_no == attempt_no,
                FlowStepAttempts.status == StepAttemptStatus.STARTED.value,
            )
            .values(status=status.value, error_message=_clip(error), finished_at=_now())
        )
        return _rowcount(result) == 1

    async def mark_started_attempts_outcome_unknown(self, run_id: UUID) -> int:
        result = await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.status == StepAttemptStatus.STARTED.value,
            )
            .values(status=StepAttemptStatus.OUTCOME_UNKNOWN.value, finished_at=_now())
        )
        return _rowcount(result)

    async def fail_running_step_results(
        self, run_id: UUID, *, error_code: str, error_message: str
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.status == StepResultStatus.RUNNING.value,
            )
            .values(
                status=StepResultStatus.FAILED.value,
                error_code=error_code,
                error_message=_clip(error_message),
                finished_at=_now(),
            )
        )
        return _rowcount(result)

    async def cancel_pending_step_results(self, run_id: UUID) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.status.in_(
                    [
                        StepResultStatus.PENDING.value,
                        StepResultStatus.AWAITING_REVIEW.value,
                    ]
                ),
            )
            .values(status=StepResultStatus.CANCELLED.value, finished_at=_now())
        )
        return _rowcount(result)

    async def complete_step_result(
        self,
        run_id: UUID,
        step_id: UUID,
        *,
        input_payload_json: Optional[dict[str, Any]],
        output_payload_json: dict[str, Any],
        num_tokens_input: Optional[int] = None,
        num_tokens_output: Optional[int] = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": StepResultStatus.COMPLETED.value,
            "output_payload_json": output_payload_json,
            "num_tokens_input": num_tokens_input,
            "num_tokens_output": num_tokens_output,
            "error_code": None,
            "error_message": None,
            "finished_at": _now(),
        }
        if input_payload_json is not None:
            values["input_payload_json"] = input_payload_json
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
            )
            .values(**values)
        )

    async def fail_step_result(
        self,
        run_id: UUID,
        step_id: UUID,
        *,
        error_code: str,
        error_message: str,
        input_payload_json: Optional[dict[str, Any]] = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": StepResultStatus.FAILED.value,
            "error_code": error_code,
            "error_message": _clip(error_message),
            "finished_at": _now(),
        }
        if input_payload_json is not None:
            values["input_payload_json"] = input_payload_json
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
            )
            .values(**values)
        )

    async def set_step_awaiting_review(
        self,
        run_id: UUID,
        step_id: UUID,
        *,
        input_payload_json: Optional[dict[str, Any]] = None,
    ) -> None:
        values: dict[str, Any] = {"status": StepResultStatus.AWAITING_REVIEW.value}
        if input_payload_json is not None:
            values["input_payload_json"] = input_payload_json
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == step_id,
            )
            .values(**values)
        )

    # --- Review checkpoints ---

    async def create_checkpoint(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        review_mode: str,
        output_type: str,
        payload: Optional[dict[str, Any]],
        requester_principal_type: str,
        requester_user_id: Optional[UUID],
        requester_service_id: Optional[UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> FlowRunReviewCheckpoints:
        stmt = (
            sa.insert(FlowRunReviewCheckpoints)
            .values(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                state=ReviewCheckpointState.AWAITING_REVIEW.value,
                revision=1,
                review_mode=review_mode,
                output_type=output_type,
                original_payload_json=payload,
                current_payload_json=payload,
                requester_principal_type=requester_principal_type,
                requester_user_id=requester_user_id,
                requester_service_id=requester_service_id,
                expires_at=expires_at,
            )
            .returning(FlowRunReviewCheckpoints)
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_active_checkpoint(
        self, run_id: UUID
    ) -> Optional[FlowRunReviewCheckpoints]:
        stmt = (
            sa.select(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.flow_run_id == run_id,
                FlowRunReviewCheckpoints.state.in_(
                    FLOW_REVIEW_CHECKPOINT_ACTIVE_STATES
                ),
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_checkpoint(
        self, checkpoint_id: UUID, run_id: UUID
    ) -> Optional[FlowRunReviewCheckpoints]:
        stmt = (
            sa.select(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.id == checkpoint_id,
                FlowRunReviewCheckpoints.flow_run_id == run_id,
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def edit_checkpoint(
        self,
        checkpoint_id: UUID,
        *,
        expected_revision: int,
        current_payload_json: dict[str, Any],
    ) -> bool:
        """Replace the reviewed payload (CAS on revision and an open state)."""
        result = await self.session.execute(
            sa.update(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.id == checkpoint_id,
                FlowRunReviewCheckpoints.revision == expected_revision,
                FlowRunReviewCheckpoints.state.in_(
                    [
                        ReviewCheckpointState.AWAITING_REVIEW.value,
                        ReviewCheckpointState.EDITED.value,
                    ]
                ),
            )
            .values(
                state=ReviewCheckpointState.EDITED.value,
                revision=FlowRunReviewCheckpoints.revision + 1,
                current_payload_json=current_payload_json,
                edited_at=_now(),
                updated_at=_now(),
            )
        )
        return _rowcount(result) == 1

    async def decide_checkpoint(
        self,
        checkpoint_id: UUID,
        *,
        state: ReviewCheckpointState,
        from_states: tuple[ReviewCheckpointState, ...],
        expected_revision: Optional[int] = None,
        decided_by_principal_type: Optional[str] = None,
        decided_by_user_id: Optional[UUID] = None,
        decided_by_service_id: Optional[UUID] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Move a checkpoint to a decided state (CAS on state and revision)."""
        now = _now()
        values: dict[str, Any] = {"state": state.value, "updated_at": now}
        if decided_by_principal_type is not None:
            values["decided_by_principal_type"] = decided_by_principal_type
            values["decided_by_user_id"] = decided_by_user_id
            values["decided_by_service_id"] = decided_by_service_id
        if reason is not None:
            values["reason"] = reason
        stamp = {
            ReviewCheckpointState.APPROVED: "approved_at",
            ReviewCheckpointState.REJECTED: "rejected_at",
            ReviewCheckpointState.RESUMED: "resumed_at",
            ReviewCheckpointState.CANCELLED: "cancelled_at",
        }.get(state)
        if stamp is not None:
            values[stamp] = now
        stmt = (
            sa.update(FlowRunReviewCheckpoints)
            .where(
                FlowRunReviewCheckpoints.id == checkpoint_id,
                FlowRunReviewCheckpoints.state.in_([s.value for s in from_states]),
            )
            .values(**values)
        )
        if expected_revision is not None:
            stmt = stmt.where(FlowRunReviewCheckpoints.revision == expected_revision)
        return _rowcount(await self.session.execute(stmt)) == 1

    async def mark_resumed(self, checkpoint_id: UUID) -> bool:
        return await self.decide_checkpoint(
            checkpoint_id,
            state=ReviewCheckpointState.RESUMED,
            from_states=(ReviewCheckpointState.APPROVED,),
        )
