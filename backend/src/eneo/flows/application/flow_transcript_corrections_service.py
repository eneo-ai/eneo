"""Validate correction anchors against the immutable source of the current attempt."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_source_service import (
    FlowTranscriptSourceService,
)
from eneo.flows.domain.transcript_corrections import (
    FlowTranscriptCorrectionSet,
    FlowTranscriptCorrectionsStaleRevisionError,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
    TranscriptSpeakerEditInvalidError,
    sort_occurrences,
    sort_speaker_edits,
    validate_correction_partitions,
    validate_occurrences,
    validate_speaker_edits,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_corrections_repo import (
    FlowTranscriptCorrectionsRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import NotFoundException
from eneo.users.user import UserInDB


@dataclass(frozen=True, slots=True)
class FlowTranscriptCorrectionsView:
    corrections: FlowTranscriptCorrectionSet
    stale: bool


class FlowTranscriptCorrectionsService:
    def __init__(
        self,
        *,
        user: UserInDB,
        transcript_corrections_repo: FlowTranscriptCorrectionsRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_repo: FlowRunRepository,
        audit_service: AuditService,
        transcript_source_service: FlowTranscriptSourceService,
    ):
        self.user = user
        self.transcript_corrections_repo = transcript_corrections_repo
        self.access_policy = access_policy
        self.flow_run_repo = flow_run_repo
        self.audit_service = audit_service
        self.transcript_source_service = transcript_source_service

    async def list_for_run(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> list[FlowTranscriptCorrectionsView]:
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        correction_sets = await self.transcript_corrections_repo.list_for_run(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        if not correction_sets:
            return []
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        current_hash_by_step: dict[UUID, str | None] = {}
        corrected_steps = {item.step_id for item in correction_sets}
        for step_result in step_results:
            if step_result.step_id not in corrected_steps:
                continue
            source = (
                await self.transcript_source_service.get_reference_for_attempt(
                    flow_id=flow_id,
                    run_id=run.id,
                    step_id=step_result.step_id,
                    attempt_no=step_result.current_attempt_no,
                )
                if step_result.current_attempt_no is not None
                else None
            )
            current_hash_by_step[step_result.step_id] = (
                source.source_hash
                if source is not None and source.bounds.segments_omitted_reason is None
                else None
            )
        return [
            FlowTranscriptCorrectionsView(
                corrections=correction_set,
                stale=(
                    correction_set.segments_hash
                    != current_hash_by_step.get(correction_set.step_id)
                ),
            )
            for correction_set in correction_sets
        ]

    async def save(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        expected_revision: int | None,
        occurrences: list[TranscriptCorrectionOccurrence],
        speaker_edits: list[TranscriptSpeakerEdit] | None = None,
        schema_version: int = 2,
        expected_segments_hash: str,
    ) -> FlowTranscriptCorrectionsView:
        if schema_version not in (2, 3):
            raise FlowBadRequestException(
                "Unsupported transcript correction schema version.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT,
                context={"reason": "client_upgrade_required"},
            )
        speaker_edits = speaker_edits or []
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        step_result = await self.flow_run_repo.get_step_result(
            run_id=run.id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
            for_update=True,
        )
        if step_result is None:
            raise NotFoundException("Flow run step result not found.")
        source = (
            await self.transcript_source_service.get_for_attempt(
                flow_id=flow_id,
                run_id=run.id,
                step_id=step_id,
                attempt_no=step_result.current_attempt_no,
            )
            if step_result.current_attempt_no is not None
            else None
        )
        if (
            source is None
            or source.status != "present"
            or source.source.segments is None
        ):
            raise FlowBadRequestException(
                "The step has no structured transcript lines to anchor corrections to.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE,
                context={"step_id": str(step_id)},
            )
        segments = source.source.segments
        current_hash = source.source.source_hash
        if current_hash is None or expected_segments_hash != current_hash:
            raise FlowBadRequestException(
                "The source transcript changed. Reload before reviewing.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION,
                context={"reason": "stale_segments"},
            )
        existing = await self.transcript_corrections_repo.get_for_step(
            run_id=run.id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        if existing is not None and existing.schema_version >= 3 and schema_version < 3:
            raise FlowBadRequestException(
                "This correction set requires a version 3 client.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION,
                context={"reason": "client_upgrade_required"},
            )
        try:
            validate_occurrences(segments, occurrences)
            if schema_version >= 3:
                validate_correction_partitions(occurrences, speaker_edits)
        except TranscriptCorrectionInvalidOccurrenceError as exc:
            raise FlowBadRequestException(
                "A correction occurrence does not match the stored transcript.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE,
                context={"reason": exc.reason, **exc.context},
            ) from exc
        if schema_version < 3 and any(
            edit.decision != "confirmed"
            or edit.speaker == edit.original_speaker
            or edit.original_speaker is None
            for edit in speaker_edits
        ):
            raise FlowBadRequestException(
                "Speaker review decisions require schema version 3.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT,
                context={
                    "reason": "speaker_unchanged"
                    if any(
                        edit.speaker == edit.original_speaker for edit in speaker_edits
                    )
                    else "client_upgrade_required"
                },
            )
        try:
            validate_speaker_edits(segments, speaker_edits)
        except TranscriptSpeakerEditInvalidError as exc:
            raise FlowBadRequestException(
                "A speaker edit does not match the stored transcript.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT,
                context={"reason": exc.reason, **exc.context},
            ) from exc
        canonical = sort_occurrences(occurrences)
        canonical_speaker_edits = sort_speaker_edits(speaker_edits)
        try:
            saved = await self.transcript_corrections_repo.save(
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                run_id=run.id,
                step_id=step_id,
                occurrences_json=[occurrence.as_json() for occurrence in canonical],
                speaker_edits_json=[edit.as_json() for edit in canonical_speaker_edits],
                segments_hash=current_hash,
                expected_revision=expected_revision,
                schema_version=schema_version,
                principal=FlowPrincipal.from_user(self.user),
            )
        except FlowTranscriptCorrectionsStaleRevisionError as exc:
            raise FlowBadRequestException(
                "Transcript corrections revision is stale.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION,
                context={
                    "expected_revision": exc.expected_revision,
                    "current_revision": exc.current_revision,
                },
            ) from exc
        try:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDITED,
                entity_type=EntityType.FLOW_RUN,
                entity_id=run.id,
                description="Replaced transcript corrections for a flow run step",
                metadata=AuditMetadata.standard(
                    actor=self.user,
                    target=saved,
                    extra={
                        "flow_id": str(flow_id),
                        "run_id": str(run.id),
                        "step_id": str(step_id),
                        "occurrence_count": len(saved.occurrences_json),
                        "speaker_edit_count": len(saved.speaker_edits_json),
                        "revision": saved.revision,
                        "schema_version": saved.schema_version,
                    },
                ),
                required=True,
            )
        except Exception as exc:
            from eneo.flows.application.flow_trace_audit import (
                raise_flow_trace_audit_unavailable,
            )

            raise_flow_trace_audit_unavailable(
                user=self.user,
                run=run,
                action=ActionType.FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDITED,
                cause=exc,
            )
        return FlowTranscriptCorrectionsView(corrections=saved, stale=False)
