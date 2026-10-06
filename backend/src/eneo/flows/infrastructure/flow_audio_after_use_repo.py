"""Bounded discovery and source-run locks for transcription audio reclamation."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.principal import Principal
from eneo.authentication.principal_types import PrincipalType
from eneo.data_retention.domain.retention import RetentionKeyset, RetentionPolicySource
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowStepResults,
    FlowStepTranscriptSources,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES, FlowStepResultStatus
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_run_held_predicate
from eneo.flows.infrastructure.flow_run_retention_policy_query import (
    effective_transcription_audio_after_use_sql,
)


@dataclass(frozen=True, slots=True)
class AudioInputBinding:
    position: RetentionKeyset
    run_id: UUID
    step_id: UUID
    file_id: UUID


@dataclass(frozen=True, slots=True)
class AudioSourceRun:
    id: UUID
    flow_id: UUID
    tenant_id: UUID
    version: int
    principal: Principal
    held: bool
    policy_source: RetentionPolicySource
    policy_scope_id: UUID
    anchor_at: datetime


class AudioSourceAvailability(StrEnum):
    MISSING = "missing"
    INELIGIBLE = "ineligible"
    RETENTION_ACTIVE = "retention_active"
    BUSY = "busy"


def _eligible_source() -> sa.ColumnElement[bool]:
    return sa.and_(
        FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
        _audio_policy(),
        FlowRuns.retention_receipt_id.is_(None),
    )


def _audio_policy() -> sa.ColumnElement[bool]:
    return effective_transcription_audio_after_use_sql(
        organization=Tenants.delete_transcription_audio_after_use,
        space=Spaces.delete_transcription_audio_after_use,
        flow=Flows.delete_transcription_audio_after_use,
    )


class FlowAudioAfterUseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_binding(
        self, after: RetentionKeyset | None
    ) -> AudioInputBinding | None:
        statement = (
            sa.select(FlowRunStepInputFiles)
            .order_by(FlowRunStepInputFiles.created_at, FlowRunStepInputFiles.id)
            .limit(1)
        )
        if after is not None:
            statement = statement.where(
                sa.tuple_(FlowRunStepInputFiles.created_at, FlowRunStepInputFiles.id)
                > sa.tuple_(
                    sa.literal(after.at, type_=sa.DateTime(timezone=True)),
                    sa.literal(after.id, type_=sa.UUID()),
                )
            )
        row = await self.session.scalar(statement)
        if row is None:
            return None
        return AudioInputBinding(
            RetentionKeyset(row.created_at, row.id),
            row.flow_run_id,
            row.step_id,
            row.file_id,
        )

    async def lock_source(self, run_id: UUID) -> AudioSourceRun | None:
        source = sa.cast(
            sa.case(
                (
                    Flows.delete_transcription_audio_after_use.is_not(None),
                    sa.literal("flow"),
                ),
                (
                    Spaces.delete_transcription_audio_after_use.is_not(None),
                    sa.literal("space"),
                ),
                else_=sa.literal("organization"),
            ),
            sa.String(),
        )
        row = (
            (
                await self.session.execute(
                    sa.select(
                        FlowRuns,
                        Spaces.id,
                        source,
                        flow_run_held_predicate(
                            run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                        ),
                    )
                    .join(Flows, Flows.id == FlowRuns.flow_id)
                    .join(Spaces, Spaces.id == Flows.space_id)
                    .join(Tenants, Tenants.id == FlowRuns.tenant_id)
                    .where(FlowRuns.id == run_id, _eligible_source())
                    .with_for_update(of=FlowRuns, skip_locked=True)
                )
            )
            .tuples()
            .first()
        )
        if row is None:
            return None
        run, space_id, policy_source, held = row
        scope = RetentionPolicySource(policy_source)
        scope_id = (
            run.flow_id
            if scope is RetentionPolicySource.FLOW
            else (space_id if scope is RetentionPolicySource.SPACE else run.tenant_id)
        )
        return AudioSourceRun(
            run.id,
            run.flow_id,
            run.tenant_id,
            run.flow_version,
            Principal(
                PrincipalType(run.principal_type),
                run.principal_user_id,
                run.principal_service_id,
            ),
            held,
            scope,
            scope_id,
            run.finished_at or run.created_at,
        )

    async def source_availability(self, run_id: UUID) -> AudioSourceAvailability:
        # Classify an excluded source without blocking active run writes.
        state = await self.session.scalar(
            sa.select(
                sa.cast(
                    sa.case(
                        (
                            FlowRuns.retention_receipt_id.is_not(None),
                            AudioSourceAvailability.RETENTION_ACTIVE.value,
                        ),
                        (_eligible_source(), AudioSourceAvailability.BUSY.value),
                        else_=AudioSourceAvailability.INELIGIBLE.value,
                    ),
                    sa.String(),
                )
            )
            .select_from(FlowRuns)
            .join(Flows, Flows.id == FlowRuns.flow_id)
            .join(Spaces, Spaces.id == Flows.space_id)
            .join(Tenants, Tenants.id == FlowRuns.tenant_id)
            .where(FlowRuns.id == run_id)
        )
        return (
            AudioSourceAvailability(state)
            if state is not None
            else AudioSourceAvailability.MISSING
        )

    async def transcript_safe_to_release(self, run_id: UUID, step_id: UUID) -> bool:
        row = (
            (
                await self.session.execute(
                    sa.select(
                        FlowStepResults.status,
                        sa.select(FlowStepTranscriptSources.id)
                        .where(
                            FlowStepTranscriptSources.flow_run_id
                            == FlowStepResults.flow_run_id,
                            FlowStepTranscriptSources.step_id
                            == FlowStepResults.step_id,
                            FlowStepTranscriptSources.attempt_no
                            == FlowStepResults.current_attempt_no,
                            FlowStepTranscriptSources.source_hash.is_not(None),
                            FlowStepTranscriptSources.segments_json.is_not(None),
                        )
                        .exists(),
                    ).where(
                        FlowStepResults.flow_run_id == run_id,
                        FlowStepResults.step_id == step_id,
                    )
                )
            )
            .tuples()
            .first()
        )
        return row is not None and (
            FlowStepResultStatus(row[0]) is not FlowStepResultStatus.COMPLETED or row[1]
        )

    async def removable_uploads(
        self, source: AudioSourceRun, members: list[UUID], *, limit: int
    ) -> tuple[UUID, ...]:
        rows = await self.session.scalars(
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .where(
                uuid_in(FlowRuntimeUploadedFiles.file_id, members),
                FlowRuntimeUploadedFiles.flow_id == source.flow_id,
                FlowRuntimeUploadedFiles.owner_type
                == source.principal.principal_type.value,
                FlowRuntimeUploadedFiles.owner_user_id
                == source.principal.principal_user_id,
                FlowRuntimeUploadedFiles.owner_service_id
                == source.principal.principal_service_id,
                ~sa.select(FlowRunStepInputFiles.id)
                .where(
                    FlowRunStepInputFiles.file_id == FlowRuntimeUploadedFiles.file_id,
                    FlowRunStepInputFiles.flow_run_id != source.id,
                )
                .exists(),
            )
            .order_by(FlowRuntimeUploadedFiles.file_id)
            .limit(limit + 1)
            .with_for_update(of=FlowRuntimeUploadedFiles, skip_locked=True)
        )
        return tuple(rows)

    async def detach(
        self, *, run_id: UUID, members: list[UUID], uploads: tuple[UUID, ...]
    ) -> tuple[int, int]:
        inputs = await self.session.scalars(
            sa.delete(FlowRunStepInputFiles)
            .where(
                FlowRunStepInputFiles.flow_run_id == run_id,
                uuid_in(FlowRunStepInputFiles.file_id, members),
            )
            .returning(FlowRunStepInputFiles.id)
        )
        bindings = await self.session.scalars(
            sa.delete(FlowRuntimeUploadedFiles)
            .where(uuid_in(FlowRuntimeUploadedFiles.file_id, uploads))
            .returning(FlowRuntimeUploadedFiles.file_id)
        )
        return len(inputs.all()), len(bindings.all())
