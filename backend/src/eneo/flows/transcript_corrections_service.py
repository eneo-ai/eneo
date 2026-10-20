"""Transcript corrections of a run's transcribe steps: read, apply, replace.

Reading a run's transcript needs read access to the flow, as every run read
does; replacing corrections needs the same (a reviewer corrects what the
run produced), and a service principal reaches only its own runs. Every
replace is a compare-and-swap on the stored revision, anchored to the
segment array by its hash, so two reviewers cannot overwrite each other
and a re-made transcript never receives stale anchors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.definition import StepKind
from eneo.flows.flow_models import (
    FlowTranscriptCorrectionsPublic,
    FlowTranscriptPublic,
    PrincipalType,
    TranscriptCorrectionOccurrencePublic,
    TranscriptSpeakerEditPublic,
)
from eneo.flows.transcript_corrections import (
    SUPPORTED_SCHEMA_VERSIONS,
    TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
    TranscriptSpeakerEditInvalidError,
    apply_corrections_and_speaker_edits,
    normalize_speaker_names,
    render_corrected_transcript,
    segments_content_hash,
    sort_occurrences,
    sort_speaker_edits,
    validate_correction_partitions,
    validate_occurrences,
    validate_speaker_edits,
)
from eneo.main.exceptions import BadRequestException, NotFoundException

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.database.tables.flow_tables import FlowRuns, FlowTranscriptCorrections
    from eneo.flows.flow_repo import FlowRepository
    from eneo.flows.flow_run_service import FlowRunService

STALE_REVISION = "flow_transcript_corrections_stale_revision"
SEGMENTS_UNAVAILABLE = "flow_transcript_corrections_segments_unavailable"
INVALID_OCCURRENCE = "flow_transcript_corrections_invalid_occurrence"
INVALID_SPEAKER_EDIT = "flow_transcript_corrections_invalid_speaker_edit"


class TranscriptCorrectionsRejected(BadRequestException):
    """A 400 with the machine-readable ``code`` and ``context`` the old API carried."""

    def __init__(self, code: str, message: str, context: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


class FlowTranscriptCorrectionsService:
    def __init__(
        self,
        repo: FlowRepository,
        run_service: FlowRunService,
        audit_service: AuditService,
    ):
        self.repo = repo
        self.run_service = run_service
        self.audit_service = audit_service

    @property
    def user(self):
        return self.run_service.user

    # --- Reads ---

    async def _transcript_segments(
        self, run: FlowRuns, step_id: UUID
    ) -> tuple[list[dict[str, Any]], dict[str, Optional[str]]]:
        """The stored segments of a transcribe step, and the names its
        speaker mapping gave; raises when the step has no transcript."""
        definition = await self.run_service._definition_for(run)  # pyright: ignore[reportPrivateUsage]
        step = definition.step_by_id(step_id)
        if step is None or step.kind != StepKind.TRANSCRIBE:
            raise NotFoundException("Flow run step result not found.")
        result = await self.repo.get_step_result(run.id, step_id)
        payload = (result.input_payload_json if result is not None else None) or {}
        transcription = cast(dict[str, Any], payload.get("transcription") or {})
        segments = cast(list[dict[str, Any]] | None, transcription.get("segments"))
        if not segments:
            raise TranscriptCorrectionsRejected(
                SEGMENTS_UNAVAILABLE,
                "The step has no transcript segments to correct.",
                {"step_id": str(step_id)},
            )
        names = cast(dict[str, Optional[str]], transcription.get("speaker_names") or {})
        return segments, names

    @staticmethod
    def _public(
        row: FlowTranscriptCorrections, *, stale: bool
    ) -> FlowTranscriptCorrectionsPublic:
        return FlowTranscriptCorrectionsPublic(
            schema_version=row.schema_version,
            segments_hash=row.segments_hash,
            flow_run_id=row.flow_run_id,
            step_id=row.step_id,
            occurrences=[
                TranscriptCorrectionOccurrencePublic.model_validate(item)
                for item in row.occurrences_json
            ],
            speaker_edits=[
                TranscriptSpeakerEditPublic.model_validate(item)
                for item in row.speaker_edits_json
            ],
            speaker_names=cast(dict[str, Optional[str]], row.speaker_names or {}),
            revision=row.revision,
            stale=stale,
            edited_by_principal_type=PrincipalType(row.edited_by_principal_type),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_for_run(
        self, run_id: UUID, *, flow_id: UUID | None = None
    ) -> list[FlowTranscriptCorrectionsPublic]:
        run = await self.run_service._require_run(run_id, flow_id=flow_id)  # pyright: ignore[reportPrivateUsage]
        views: list[FlowTranscriptCorrectionsPublic] = []
        for row in await self.repo.list_transcript_corrections(run.id):
            try:
                segments, _ = await self._transcript_segments(run, row.step_id)
                stale = segments_content_hash(segments) != row.segments_hash
            except (NotFoundException, BadRequestException):
                stale = True
            views.append(self._public(row, stale=stale))
        return views

    async def get_transcript(
        self, run_id: UUID, step_id: UUID, *, flow_id: UUID | None = None
    ) -> FlowTranscriptPublic:
        """The step's transcript with its current corrections applied."""
        run = await self.run_service._require_run(run_id, flow_id=flow_id)  # pyright: ignore[reportPrivateUsage]
        segments, mapped_names = await self._transcript_segments(run, step_id)
        segments_hash = segments_content_hash(segments)
        row = await self.repo.get_transcript_corrections(run.id, step_id)
        occurrences: list[TranscriptCorrectionOccurrence] = []
        edits: list[TranscriptSpeakerEdit] = []
        names: dict[str, Optional[str]] = dict(mapped_names)
        revision: Optional[int] = None
        if row is not None and row.segments_hash == segments_hash:
            occurrences = [
                TranscriptCorrectionOccurrence.from_json(item)
                for item in row.occurrences_json
            ]
            edits = [
                TranscriptSpeakerEdit.from_json(item) for item in row.speaker_edits_json
            ]
            names.update(cast(dict[str, Optional[str]], row.speaker_names or {}))
            revision = row.revision
        corrected, _, _ = apply_corrections_and_speaker_edits(
            segments, occurrences, edits
        )
        return FlowTranscriptPublic(
            flow_run_id=run.id,
            step_id=step_id,
            segments_hash=segments_hash,
            segments=corrected,
            speaker_names=names,
            text=render_corrected_transcript(segments, occurrences, edits, names),
            corrections_revision=revision,
        )

    # --- Replace ---

    async def save(
        self,
        run_id: UUID,
        step_id: UUID,
        *,
        flow_id: UUID | None = None,
        schema_version: int,
        segments_hash: str,
        expected_revision: Optional[int],
        occurrences: Sequence[TranscriptCorrectionOccurrencePublic | Mapping[str, Any]],
        speaker_edits: Sequence[TranscriptSpeakerEditPublic | Mapping[str, Any]],
        speaker_names: Optional[Mapping[str, Optional[str]]],
        channel: str = "api",
    ) -> FlowTranscriptCorrectionsPublic:
        run = await self.run_service._require_run(run_id, flow_id=flow_id)  # pyright: ignore[reportPrivateUsage]
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise BadRequestException(f"Unsupported schema_version {schema_version}.")
        segments, _ = await self._transcript_segments(run, step_id)
        current_hash = segments_content_hash(segments)
        if segments_hash != current_hash:
            raise TranscriptCorrectionsRejected(
                STALE_REVISION,
                "The transcript changed since the corrections were written.",
                {
                    "expected_segments_hash": segments_hash,
                    "segments_hash": current_hash,
                },
            )
        parsed_occurrences = sort_occurrences(
            [
                TranscriptCorrectionOccurrence.from_json(
                    TranscriptCorrectionOccurrencePublic.model_validate(o).model_dump()
                )
                for o in occurrences
            ]
        )
        parsed_edits = sort_speaker_edits(
            [
                TranscriptSpeakerEdit.from_json(
                    TranscriptSpeakerEditPublic.model_validate(e).model_dump()
                )
                for e in speaker_edits
            ]
        )
        try:
            validate_occurrences(segments, parsed_occurrences)
            validate_speaker_edits(segments, parsed_edits)
            validate_correction_partitions(parsed_occurrences, parsed_edits)
            names = normalize_speaker_names(
                speaker_names or {}, segments=segments, speaker_edits=parsed_edits
            )
        except TranscriptCorrectionInvalidOccurrenceError as exc:
            raise TranscriptCorrectionsRejected(
                INVALID_OCCURRENCE,
                f"A correction does not fit the transcript: {exc.reason}.",
                {"reason": exc.reason, **exc.context},
            ) from exc
        except TranscriptSpeakerEditInvalidError as exc:
            raise TranscriptCorrectionsRejected(
                INVALID_SPEAKER_EDIT,
                f"A speaker edit does not fit the transcript: {exc.reason}.",
                {"reason": exc.reason, **exc.context},
            ) from exc

        saved = await self.repo.save_transcript_corrections(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=step_id,
            expected_revision=expected_revision,
            occurrences_json=[o.as_json() for o in parsed_occurrences],
            speaker_edits_json=[e.as_json() for e in parsed_edits],
            speaker_names=names,
            segments_hash=current_hash,
            schema_version=TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION,
            principal_type=self.run_service._principal_type.value,  # pyright: ignore[reportPrivateUsage]
            principal_user_id=self.run_service._principal_user_id,  # pyright: ignore[reportPrivateUsage]
            principal_service_id=self.run_service.service_key_id,
        )
        if saved is None:
            current = await self.repo.get_transcript_corrections(run.id, step_id)
            raise TranscriptCorrectionsRejected(
                STALE_REVISION,
                "The corrections changed since they were read.",
                {
                    "expected_revision": expected_revision,
                    "current_revision": current.revision if current else None,
                },
            )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDITED,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description="Replaced transcript corrections of a flow run step",
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=run,
                extra={
                    "channel": channel,
                    "flow_id": str(run.flow_id),
                    "step_id": str(step_id),
                    "revision": saved.revision,
                    "occurrence_count": len(parsed_occurrences),
                    "speaker_edit_count": len(parsed_edits),
                    "speaker_name_count": len(names),
                },
            ),
        )
        return self._public(saved, stale=False)
