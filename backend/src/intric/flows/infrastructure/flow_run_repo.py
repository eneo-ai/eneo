from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence, TypedDict, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.auth_models import ApiKeyPermission
from intric.authentication.principal_types import PrincipalType
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRunWebhookDeliveries,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.tenant_table import Tenants
from intric.files.file_models import FileType
from intric.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowRunTokenUsage,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from intric.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES,
    CANCELLABLE_FLOW_RUN_STATUSES,
    OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES,
    TERMINAL_FLOW_RUN_STATUSES,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_run_error import FlowRunError, dump_flow_run_error
from intric.flows.flow_run_input_envelope import (
    FlowRunInputEnvelopePatch,
)
from intric.flows.flow_run_provenance import (
    AttemptStartProvenance,
    FlowAttemptProvenance,
)
from intric.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from intric.flows.flow_run_step_inputs import FlowRunStepInputFileProjection
from intric.flows.flow_run_step_result_file import (
    FlowRunStepResultFile,
    FlowRunStepResultFileAvailability,
    FlowRunStepResultFileSource,
)
from intric.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from intric.flows.infrastructure.flow_run_step_input_file_rows import (
    build_step_input_file_rows,
    insert_step_input_file_rows,
)
from intric.flows.infrastructure.flow_step_attempt_numbering import (
    next_step_attempt_no,
)
from intric.flows.principal import FlowPrincipal


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int


def _current_step_attempt_pairs_by_result_id(
    step_results: Sequence[FlowStepResult],
) -> tuple[dict[tuple[UUID, int], UUID], list[tuple[UUID, int]]]:
    step_result_id_by_step_attempt: dict[tuple[UUID, int], UUID] = {}
    current_attempt_pairs: list[tuple[UUID, int]] = []
    for result in step_results:
        if result.id is None or result.current_attempt_no is None:
            continue
        pair = (result.step_id, result.current_attempt_no)
        step_result_id_by_step_attempt[pair] = result.id
        current_attempt_pairs.append(pair)
    return step_result_id_by_step_attempt, current_attempt_pairs


_CANCELLABLE_RUN_STATUSES = tuple(
    status.value for status in CANCELLABLE_FLOW_RUN_STATUSES
)


class FlowRunRepository:
    """Tenant-scoped repository for flow run lifecycle and run evidence."""

    _ACTIVE_STATUSES = tuple(status.value for status in ACTIVE_FLOW_RUN_STATUSES)

    def __init__(
        self,
        session: AsyncSession,
        factory: FlowFactory,
        audit_outbox_repo: FlowRunAuditOutboxRepository | None = None,
    ):
        self.session = session
        self.factory = factory
        self.audit_outbox_repo = audit_outbox_repo or FlowRunAuditOutboxRepository(
            session=session
        )

    async def create(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        principal_type: str = "user",
        principal_user_id: UUID | None = None,
        principal_service_id: UUID | None = None,
        created_by_api_key_id: UUID | None = None,
        runtime_service_permission: ApiKeyPermission | None = None,
        tenant_id: UUID,
        input_payload_json: dict[str, Any] | None,
        preseed_steps: Sequence["PreseedStep"],
        step_input_files: Sequence[FlowRunStepInputFileProjection] | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> FlowRun:
        principal = FlowPrincipal(
            principal_type=PrincipalType(principal_type),
            principal_user_id=principal_user_id,
            principal_service_id=principal_service_id,
            actor_api_key_id=created_by_api_key_id,
        )
        run_row = await self.session.scalar(
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                principal_type=principal.principal_type.value,
                principal_user_id=principal.principal_user_id,
                principal_service_id=principal.principal_service_id,
                created_by_api_key_id=principal.actor_api_key_id,
                runtime_service_permission=(
                    runtime_service_permission.value
                    if runtime_service_permission is not None
                    else None
                ),
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
            raise FlowRunPersistenceInvariantError(
                operation="create_flow_run",
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

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

        step_input_file_rows = build_step_input_file_rows(
            flow_run_id=run_row.id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            attempt_no=1,
            projections=step_input_files,
        )
        await insert_step_input_file_rows(
            session=self.session,
            rows=step_input_file_rows,
        )

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
            raise FlowRunNotFoundError(
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        return self.factory.from_flow_run_db(run_row)

    async def get_idempotent_run(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        idempotency_key: str,
        principal: FlowPrincipal,
    ) -> tuple[FlowRun, str | None] | None:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.idempotency_key == idempotency_key)
            .where(FlowRuns.principal_type == principal.principal_type.value)
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal.principal_user_id)
        if principal.principal_service_id is not None:
            stmt = stmt.where(
                FlowRuns.principal_service_id == principal.principal_service_id
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
        principal_service_id: UUID | None = None,
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
        if principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal_user_id)
        if principal_service_id is not None:
            stmt = stmt.where(FlowRuns.principal_service_id == principal_service_id)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_token_usage_for_runs(
        self,
        *,
        run_ids: Sequence[UUID],
        tenant_id: UUID,
    ) -> dict[UUID, FlowRunTokenUsage]:
        if not run_ids:
            return {}

        input_tokens = sa.func.coalesce(
            sa.func.sum(sa.func.coalesce(FlowStepAttempts.num_tokens_input, 0)),
            0,
        )
        output_tokens = sa.func.coalesce(
            sa.func.sum(sa.func.coalesce(FlowStepAttempts.num_tokens_output, 0)),
            0,
        )
        total_tokens = input_tokens + output_tokens
        stmt = (
            sa.select(
                FlowStepAttempts.flow_run_id,
                input_tokens.label("num_tokens_input"),
                output_tokens.label("num_tokens_output"),
            )
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.flow_run_id.in_(tuple(run_ids)))
            .group_by(FlowStepAttempts.flow_run_id)
            .having(total_tokens > 0)
        )

        rows = await self.session.execute(stmt)
        usage_by_run_id: dict[UUID, FlowRunTokenUsage] = {}
        for row in rows:
            run_input_tokens = int(row.num_tokens_input or 0)
            run_output_tokens = int(row.num_tokens_output or 0)
            usage_by_run_id[row.flow_run_id] = FlowRunTokenUsage.from_counts(
                num_tokens_input=run_input_tokens,
                num_tokens_output=run_output_tokens,
            )
        return usage_by_run_id

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
            .where(
                ~sa.select(FlowRunWebhookDeliveries.id)
                .where(FlowRunWebhookDeliveries.flow_run_id == FlowRuns.id)
                .where(FlowRunWebhookDeliveries.tenant_id == FlowRuns.tenant_id)
                .where(
                    FlowRunWebhookDeliveries.delivery_status
                    == FlowOutboxDeliveryStatus.PENDING.value
                )
                .exists()
            )
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
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRun | None:
        if target_status not in TERMINAL_FLOW_RUN_STATUSES:
            raise ValueError("target_status must be terminal")

        values: dict[str, Any] = {
            "status": target_status.value,
            "error_json": dump_flow_run_error(error),
            "output_payload_json": output_payload_json,
            "finished_at": datetime.now(timezone.utc),
        }
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at

        source_statuses = (
            _CANCELLABLE_RUN_STATUSES
            if target_status == FlowRunStatus.CANCELLED
            else self._ACTIVE_STATUSES
        )
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(source_statuses))
        )
        if stale_before is not None:
            stmt = stmt.where(FlowRuns.updated_at <= stale_before)
        run_row = await self.session.scalar(stmt.values(**values).returning(FlowRuns))
        if run_row is None:
            return None
        return self.factory.from_flow_run_db(run_row)

    async def count_active_step_results(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES))
        )
        return int(count or 0)

    async def count_open_step_attempts(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
        )
        return int(count or 0)

    async def close_active_step_results_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepResultStatus,
        error_code: str | None,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES))
            .values(
                status=target_status.value,
                error_code=error_code,
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
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
            .values(
                status=target_status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def update_input_payload(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        input_payload_patch: FlowRunInputEnvelopePatch,
    ) -> FlowPersistedJsonObject:
        current_payload = await self.session.scalar(
            sa.select(FlowRuns.input_payload_json)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        updated_payload = input_payload_patch.apply_to(current_payload)
        await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(input_payload_json=updated_payload)
        )
        return updated_payload

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

    async def list_step_input_file_ids(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        attempt_no: int,
    ) -> list[UUID]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunStepInputFiles.file_id)
                    .where(FlowRunStepInputFiles.flow_run_id == run_id)
                    .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                    .where(FlowRunStepInputFiles.step_id == step_id)
                    .where(FlowRunStepInputFiles.attempt_no == attempt_no)
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def list_current_step_input_file_ids_by_step_result_id(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_results: Sequence[FlowStepResult],
    ) -> dict[UUID, Sequence[UUID]]:
        step_result_id_by_step_attempt, current_attempt_pairs = (
            _current_step_attempt_pairs_by_result_id(step_results)
        )
        if not current_attempt_pairs:
            return {}

        rows = (
            await self.session.execute(
                sa.select(
                    FlowRunStepInputFiles.step_id,
                    FlowRunStepInputFiles.attempt_no,
                    FlowRunStepInputFiles.file_id,
                )
                .where(FlowRunStepInputFiles.flow_run_id == run_id)
                .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                .where(
                    sa.tuple_(
                        FlowRunStepInputFiles.step_id,
                        FlowRunStepInputFiles.attempt_no,
                    ).in_(current_attempt_pairs)
                )
                .order_by(
                    FlowRunStepInputFiles.step_order.asc(),
                    FlowRunStepInputFiles.attempt_no.asc(),
                    FlowRunStepInputFiles.ordinal.asc(),
                )
            )
        ).all()

        file_ids_by_step_result_id: dict[UUID, list[UUID]] = {}
        for step_id, attempt_no, file_id in rows:
            step_result_id = step_result_id_by_step_attempt.get((step_id, attempt_no))
            if step_result_id is None:
                continue
            file_ids_by_step_result_id.setdefault(step_result_id, []).append(file_id)

        return {
            step_result_id: tuple(file_ids)
            for step_result_id, file_ids in file_ids_by_step_result_id.items()
        }

    async def list_current_step_input_file_metadata_by_step_result_id(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_results: Sequence[FlowStepResult],
    ) -> dict[UUID, tuple[FlowRunStepInputFileMetadata, ...]]:
        step_result_id_by_step_attempt, current_attempt_pairs = (
            _current_step_attempt_pairs_by_result_id(step_results)
        )
        if not current_attempt_pairs:
            return {}

        text_length = sa.func.length(Files.text).label("text_length")
        has_text = (
            sa.func.length(sa.func.btrim(sa.func.coalesce(Files.text, ""))) > 0
        ).label("has_text")
        has_transcription = (
            sa.func.length(sa.func.btrim(sa.func.coalesce(Files.transcription, ""))) > 0
        ).label("has_transcription")
        rows = (
            await self.session.execute(
                sa.select(
                    FlowRunStepInputFiles.step_id,
                    FlowRunStepInputFiles.attempt_no,
                    FlowRunStepInputFiles.file_id,
                    Files.name,
                    Files.checksum,
                    Files.size,
                    Files.mimetype,
                    Files.file_type,
                    text_length,
                    has_text,
                    has_transcription,
                )
                .join(Files, Files.id == FlowRunStepInputFiles.file_id)
                .where(FlowRunStepInputFiles.flow_run_id == run_id)
                .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                .where(
                    sa.tuple_(
                        FlowRunStepInputFiles.step_id,
                        FlowRunStepInputFiles.attempt_no,
                    ).in_(current_attempt_pairs)
                )
                .order_by(
                    FlowRunStepInputFiles.step_order.asc(),
                    FlowRunStepInputFiles.attempt_no.asc(),
                    FlowRunStepInputFiles.ordinal.asc(),
                )
            )
        ).all()

        metadata_by_step_result_id: dict[UUID, list[FlowRunStepInputFileMetadata]] = {}
        for row in rows:
            step_result_id = step_result_id_by_step_attempt.get(
                (row.step_id, row.attempt_no)
            )
            if step_result_id is None:
                continue
            metadata_by_step_result_id.setdefault(step_result_id, []).append(
                FlowRunStepInputFileMetadata(
                    file_id=row.file_id,
                    name=row.name,
                    checksum=row.checksum,
                    size=row.size,
                    mimetype=row.mimetype,
                    file_type=FileType(row.file_type),
                    text_length=row.text_length,
                    has_text=bool(row.has_text),
                    has_transcription=bool(row.has_transcription),
                )
            )

        return {
            step_result_id: tuple(metadata)
            for step_result_id, metadata in metadata_by_step_result_id.items()
        }

    async def list_result_files(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowRunStepResultFile]:
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .order_by(
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            _result_file_from_rows(result_file_row, file_row)
            for result_file_row, file_row in rows
        ]

    async def list_result_files_for_runs(
        self,
        *,
        run_ids: Sequence[UUID],
        tenant_id: UUID,
    ) -> list[FlowRunStepResultFile]:
        unique_run_ids = list(dict.fromkeys(run_ids))
        if not unique_run_ids:
            return []
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id.in_(unique_run_ids))
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .order_by(
                FlowRunStepResultFiles.flow_run_id.asc(),
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            _result_file_from_rows(result_file_row, file_row)
            for result_file_row, file_row in rows
        ]

    async def get_result_file(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        file_id: UUID,
    ) -> FlowRunStepResultFile | None:
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .where(FlowRunStepResultFiles.file_id == file_id)
            .order_by(
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        result_file_row, file_row = row
        return _result_file_from_rows(result_file_row, file_row)

    async def mark_running_if_claimable(self, *, run_id: UUID, tenant_id: UUID) -> bool:
        now_utc = datetime.now(timezone.utc)
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .values(
                status=FlowRunStatus.RUNNING.value,
                started_at=sa.func.coalesce(FlowRuns.started_at, now_utc),
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
                error_code=None,
                error_message=None,
                started_at=sa.func.coalesce(FlowStepResults.started_at, now_utc),
                finished_at=None,
            )
            .returning(FlowStepResults)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def allocate_next_attempt_no(
        self,
        *,
        tenant_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
    ) -> int:
        return await next_step_attempt_no(
            self.session,
            tenant_id=tenant_id,
            flow_run_id=flow_run_id,
            step_id=step_id,
        )

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
        rerun_operation_id: UUID | None = None,
        predecessor_attempt_id: UUID | None = None,
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
                rerun_operation_id=rerun_operation_id,
                predecessor_attempt_id=predecessor_attempt_id,
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
            raise FlowRunPersistenceInvariantError(
                operation="create_flow_step_attempt",
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        return self.factory.from_flow_step_attempt_db(row)

    async def copy_step_input_files_from_predecessor_attempt(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        predecessor_attempt_id: UUID | None,
        target_attempt_no: int,
    ) -> None:
        if predecessor_attempt_id is None:
            return
        target_exists = await self.session.scalar(
            sa.select(sa.literal(True))
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .where(FlowRunStepInputFiles.tenant_id == tenant_id)
            .where(FlowRunStepInputFiles.step_id == step_id)
            .where(FlowRunStepInputFiles.attempt_no == target_attempt_no)
            .limit(1)
        )
        if target_exists:
            return

        source_attempt_no = await self.session.scalar(
            sa.select(FlowStepAttempts.attempt_no)
            .where(FlowStepAttempts.id == predecessor_attempt_id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.flow_id == flow_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.step_id == step_id)
        )
        if source_attempt_no is None:
            return

        file_ids = (
            (
                await self.session.execute(
                    sa.select(FlowRunStepInputFiles.file_id)
                    .where(FlowRunStepInputFiles.flow_run_id == run_id)
                    .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                    .where(FlowRunStepInputFiles.step_id == step_id)
                    .where(FlowRunStepInputFiles.attempt_no == source_attempt_no)
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        if not file_ids:
            return

        rows = build_step_input_file_rows(
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            attempt_no=target_attempt_no,
            projections=[
                {
                    "step_id": step_id,
                    "step_order": step_order,
                    "file_ids": list(file_ids),
                }
            ],
        )
        # The source attempt row already holds the runtime-upload FK, so the
        # referenced upload cannot disappear while this copy is inserted.
        await self.session.execute(
            pg_insert(FlowRunStepInputFiles)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_flow_run_step_input_files_run_step_attempt_file"
            )
        )

    async def record_attempt_start_provenance(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        requested_model: str | None,
        provider: str | None,
        attempt_start: AttemptStartProvenance,
    ) -> FlowStepAttempt | None:
        provenance_json = FlowAttemptProvenance(
            attempt_start=attempt_start
        ).to_payload()
        row = await self.session.scalar(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
            .values(
                requested_model=requested_model,
                provider=provider,
                provenance_json=provenance_json,
            )
            .returning(FlowStepAttempts)
        )
        if row is None:
            return None
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
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
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
        if status == FlowStepAttemptStatus.COMPLETED:
            await self._mark_predecessor_superseded_by_attempt(
                completed_attempt_row=row,
                tenant_id=tenant_id,
            )
        return self.factory.from_flow_step_attempt_db(row)

    async def _mark_predecessor_superseded_by_attempt(
        self,
        *,
        completed_attempt_row: FlowStepAttempts,
        tenant_id: UUID,
    ) -> None:
        if completed_attempt_row.predecessor_attempt_id is None:
            return
        await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == completed_attempt_row.predecessor_attempt_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(
                sa.or_(
                    FlowStepAttempts.superseded_by_attempt_id.is_(None),
                    FlowStepAttempts.superseded_by_attempt_id
                    == completed_attempt_row.id,
                )
            )
            .values(superseded_by_attempt_id=completed_attempt_row.id)
        )


def _result_file_from_rows(
    result_file_row: FlowRunStepResultFiles,
    file_row: Files,
) -> FlowRunStepResultFile:
    return FlowRunStepResultFile(
        flow_run_id=result_file_row.flow_run_id,
        flow_id=result_file_row.flow_id,
        tenant_id=result_file_row.tenant_id,
        step_result_id=result_file_row.step_result_id,
        step_id=result_file_row.step_id,
        step_order=result_file_row.step_order,
        attempt_no=result_file_row.attempt_no,
        file_id=result_file_row.file_id,
        ordinal=result_file_row.ordinal,
        source=cast(FlowRunStepResultFileSource, result_file_row.source),
        name=file_row.name,
        checksum=file_row.checksum,
        size=file_row.size,
        mimetype=file_row.mimetype,
        file_type=FileType(file_row.file_type),
        availability=_file_availability(file_row),
    )


def _file_availability(file_row: Files) -> FlowRunStepResultFileAvailability:
    if file_row.blob is not None or file_row.text is not None:
        return "available"
    return "content_purged"
