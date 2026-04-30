from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence, TypedDict
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.principal_types import PrincipalType
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.tenant_table import Tenants
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    JsonObject,
)
from intric.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunTerminalSource,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import NotFoundException


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int


class FlowRunRepository:
    """Tenant-scoped repository for flow run lifecycle and run evidence."""

    _ACTIVE_STATUSES = tuple(status.value for status in ACTIVE_FLOW_RUN_STATUSES)
    _OPEN_ATTEMPT_STATUSES = (
        FlowStepAttemptStatus.STARTED.value,
        FlowStepAttemptStatus.RETRIED.value,
    )
    _ACTIVE_STEP_RESULT_STATUSES = (
        FlowStepResultStatus.PENDING.value,
        FlowStepResultStatus.RUNNING.value,
    )

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def create(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        user_id: UUID | None,
        principal_type: str = "user",
        principal_user_id: UUID | None = None,
        principal_api_key_id: UUID | None = None,
        tenant_id: UUID,
        input_payload_json: dict[str, Any] | None,
        preseed_steps: Sequence["PreseedStep"],
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> FlowRun:
        if principal_type == PrincipalType.USER.value and principal_user_id is None:
            principal_user_id = user_id
        run_row = await self.session.scalar(
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                user_id=user_id,
                principal_type=principal_type,
                principal_user_id=principal_user_id,
                principal_api_key_id=principal_api_key_id,
                tenant_id=tenant_id,
                trace_id=uuid4(),
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                status=FlowRunStatus.QUEUED.value,
                input_payload_json=input_payload_json,
            )
            .returning(FlowRuns)
        )
        if run_row is None:
            raise NotFoundException("Could not create flow run.")

        preseed_rows = [
            {
                "flow_run_id": run_row.id,
                "flow_id": flow_id,
                "tenant_id": tenant_id,
                "step_id": step["step_id"],
                "step_order": step["step_order"],
                "assistant_id": step["assistant_id"],
                "status": FlowStepResultStatus.PENDING.value,
            }
            for step in sorted(preseed_steps, key=lambda item: int(item["step_order"]))
        ]
        if preseed_rows:
            await self.session.execute(sa.insert(FlowStepResults).values(preseed_rows))

        return self.factory.from_flow_run_db(run_row)

    async def get(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        flow_id: UUID | None = None,
    ) -> FlowRun:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        run_row = await self.session.scalar(stmt)
        if run_row is None:
            raise NotFoundException("Flow run not found.")
        return self.factory.from_flow_run_db(run_row)

    async def get_idempotent_run(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        idempotency_key: str,
        principal: FlowPrincipal | None = None,
        user_id: UUID | None = None,
    ) -> tuple[FlowRun, str | None] | None:
        if principal is None:
            if user_id is None:
                raise ValueError("principal or user_id is required")
            principal = FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=user_id,
            )
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.idempotency_key == idempotency_key)
            .where(FlowRuns.principal_type == principal.principal_type.value)
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal.principal_user_id)
        if principal.principal_api_key_id is not None:
            stmt = stmt.where(
                FlowRuns.principal_api_key_id == principal.principal_api_key_id
            )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return self.factory.from_flow_run_db(row), row.request_fingerprint

    async def count_active_runs(self, *, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
        )
        return int(count or 0)

    async def acquire_tenant_run_creation_lock(self, *, tenant_id: UUID) -> None:
        await self.session.execute(
            sa.select(Tenants.id).where(Tenants.id == tenant_id).with_for_update()
        )

    async def list_runs(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID | None = None,
        principal_user_id: UUID | None = None,
        principal_api_key_id: UUID | None = None,
        user_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .order_by(FlowRuns.created_at.desc())
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        resolved_principal_user_id = principal_user_id or user_id
        if resolved_principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == resolved_principal_user_id)
        if principal_api_key_id is not None:
            stmt = stmt.where(FlowRuns.principal_api_key_id == principal_api_key_id)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_stale_queued_runs(
        self,
        *,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        if run_id is not None:
            stmt = stmt.where(FlowRuns.id == run_id)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_stale_running_runs(
        self,
        *,
        tenant_id: UUID,
        stale_before: datetime,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.RUNNING.value)
            .where(FlowRuns.updated_at <= stale_before)
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def claim_stale_queued_run_for_redispatch(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
    ) -> FlowRun | None:
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        claimed = await self.session.scalar(
            stmt.values(updated_at=datetime.now(timezone.utc)).returning(FlowRuns)
        )
        if claimed is None:
            return None
        return self.factory.from_flow_run_db(claimed)

    async def terminalize_run_status(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        error_message: str | None = None,
        output_payload_json: JsonObject | None = None,
        cancelled_at: datetime | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRun | None:
        if target_status not in TERMINAL_FLOW_RUN_STATUSES:
            raise ValueError("target_status must be terminal")

        values: dict[str, Any] = {
            "status": target_status.value,
            "error_message": error_message,
            "output_payload_json": output_payload_json,
            "finished_at": datetime.now(timezone.utc),
        }
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at

        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
        )
        if stale_before is not None:
            stmt = stmt.where(FlowRuns.updated_at <= stale_before)
        run_row = await self.session.scalar(stmt.values(**values).returning(FlowRuns))
        if run_row is None:
            return None
        return self.factory.from_flow_run_db(run_row)

    async def count_active_step_results(
        self, *, run_id: UUID, tenant_id: UUID
    ) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(self._ACTIVE_STEP_RESULT_STATUSES))
        )
        return int(count or 0)

    async def count_open_step_attempts(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(self._OPEN_ATTEMPT_STATUSES))
        )
        return int(count or 0)

    async def close_active_step_results_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepResultStatus,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(self._ACTIVE_STEP_RESULT_STATUSES))
            .values(
                status=target_status.value,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def close_open_step_attempts_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepAttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(self._OPEN_ATTEMPT_STATUSES))
            .values(
                status=target_status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def insert_terminal_audit_outbox(
        self,
        *,
        run: FlowRun,
        description: str,
        action: ActionType,
        entity_type: EntityType,
        actor_id: UUID | None,
        actor_type: ActorType,
        actor_api_key_id: UUID | None,
        source: FlowRunTerminalSource,
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
                description=description,
                action=action.value,
                entity_type=entity_type.value,
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

    async def update_input_payload(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        input_payload_json: dict[str, Any],
    ) -> None:
        # Merge-patch under row lock to avoid clobbering concurrent key updates.
        current_payload = await self.session.scalar(
            sa.select(FlowRuns.input_payload_json)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        merged_payload = dict(current_payload or {})
        merged_payload.update(dict(input_payload_json))
        await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(input_payload_json=merged_payload)
        )

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepResult]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run_id)
                    .where(FlowStepResults.tenant_id == tenant_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        return [self.factory.from_flow_step_result_db(row) for row in rows]

    async def list_step_attempts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepAttempt]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == run_id)
                    .where(FlowStepAttempts.tenant_id == tenant_id)
                    .order_by(
                        FlowStepAttempts.step_order.asc(),
                        FlowStepAttempts.attempt_no.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self.factory.from_flow_step_attempt_db(row) for row in rows]

    async def mark_running_if_claimable(self, *, run_id: UUID, tenant_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .values(
                status=FlowRunStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def get_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        row = await self.session.scalar(
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def claim_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        now_utc = datetime.now(timezone.utc)
        row = await self.session.scalar(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(
                FlowStepResults.status.in_(
                    (
                        FlowStepResultStatus.PENDING.value,
                        FlowStepResultStatus.FAILED.value,
                    )
                )
            )
            .values(
                status=FlowStepResultStatus.RUNNING.value,
                error_message=None,
                started_at=sa.func.coalesce(FlowStepResults.started_at, now_utc),
                finished_at=None,
            )
            .returning(FlowStepResults)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def create_or_get_attempt_started(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        celery_task_id: str | None,
    ) -> FlowStepAttempt:
        started_at = datetime.now(timezone.utc)
        insert_stmt = (
            pg_insert(FlowStepAttempts)
            .values(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                celery_task_id=celery_task_id,
                status=FlowStepAttemptStatus.STARTED.value,
                started_at=started_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_step_attempts_run_step_attempt",
            )
            .returning(FlowStepAttempts)
        )
        row = await self.session.scalar(insert_stmt)
        if row is None:
            row = await self.session.scalar(
                sa.select(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.step_id == step_id)
                .where(FlowStepAttempts.attempt_no == attempt_no)
                .where(FlowStepAttempts.tenant_id == tenant_id)
            )
        if row is None:
            raise NotFoundException("Could not create or fetch flow step attempt.")
        return self.factory.from_flow_step_attempt_db(row)

    async def finish_attempt(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        status: FlowStepAttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        requested_model: str | None = None,
        response_model: str | None = None,
        provider: str | None = None,
        finish_reason: str | None = None,
        provider_response_id: str | None = None,
        num_tokens_input: int | None = None,
        num_tokens_output: int | None = None,
        provenance_json: dict[str, Any] | None = None,
    ) -> FlowStepAttempt | None:
        row = await self.session.scalar(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(
                FlowStepAttempts.status.in_(
                    (
                        FlowStepAttemptStatus.STARTED.value,
                        FlowStepAttemptStatus.RETRIED.value,
                    )
                )
            )
            .values(
                status=status.value,
                error_code=error_code,
                error_message=error_message,
                requested_model=requested_model,
                response_model=response_model,
                provider=provider,
                finish_reason=finish_reason,
                provider_response_id=provider_response_id,
                num_tokens_input=num_tokens_input,
                num_tokens_output=num_tokens_output,
                provenance_json=provenance_json,
                finished_at=datetime.now(timezone.utc),
            )
            .returning(FlowStepAttempts)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_attempt_db(row)
