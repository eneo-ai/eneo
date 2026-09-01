"""Application service for flow transcript corrections.

Corrections anchor to the structured transcript lines a transcription step
stored (``input_payload_json["transcription"]["segments"]``). The service
validates anchors against the current segment array at save time, stamps the
set with the array's content hash, and reports a set as stale when the stored
segments have since changed (in-run retry, re-transcription).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.domain.transcript_corrections import (
    FlowTranscriptCorrectionSet,
    FlowTranscriptCorrectionsStaleRevisionError,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    segments_content_hash,
    sort_occurrences,
    validate_occurrences,
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


def extract_transcription_segments(
    input_payload_json: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """The structured transcript lines a transcription step stored, or None.

    None covers every reader-fallback case: no transcription metadata, the
    engine produced no segments, or the array was omitted for size.
    """
    if not isinstance(input_payload_json, dict):
        return None
    transcription = input_payload_json.get("transcription")
    if not isinstance(transcription, dict):
        return None
    raw_segments = cast("dict[str, Any]", transcription).get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None
    segments: list[dict[str, Any]] = []
    for segment in cast("list[Any]", raw_segments):
        if not isinstance(segment, dict):
            return None
        segments.append(cast("dict[str, Any]", segment))
    return segments


class FlowTranscriptCorrectionsService:
    def __init__(
        self,
        *,
        user: UserInDB,
        transcript_corrections_repo: FlowTranscriptCorrectionsRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_repo: FlowRunRepository,
    ):
        self.user = user
        self.transcript_corrections_repo = transcript_corrections_repo
        self.access_policy = access_policy
        self.flow_run_repo = flow_run_repo

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
        for step_result in step_results:
            segments = extract_transcription_segments(step_result.input_payload_json)
            current_hash_by_step[step_result.step_id] = (
                segments_content_hash(segments) if segments is not None else None
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
    ) -> FlowTranscriptCorrectionsView:
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        step_result = await self.flow_run_repo.get_step_result(
            run_id=run.id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        if step_result is None:
            raise NotFoundException("Flow run step result not found.")
        segments = extract_transcription_segments(step_result.input_payload_json)
        if segments is None:
            raise FlowBadRequestException(
                "The step has no structured transcript lines to anchor corrections to.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE,
                context={"step_id": str(step_id)},
            )
        try:
            validate_occurrences(segments, occurrences)
        except TranscriptCorrectionInvalidOccurrenceError as exc:
            raise FlowBadRequestException(
                "A correction occurrence does not match the stored transcript.",
                code=FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE,
                context={"reason": exc.reason, **exc.context},
            ) from exc
        canonical = sort_occurrences(occurrences)
        try:
            saved = await self.transcript_corrections_repo.save(
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                run_id=run.id,
                step_id=step_id,
                occurrences_json=[occurrence.as_json() for occurrence in canonical],
                segments_hash=segments_content_hash(segments),
                expected_revision=expected_revision,
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
        return FlowTranscriptCorrectionsView(corrections=saved, stale=False)
