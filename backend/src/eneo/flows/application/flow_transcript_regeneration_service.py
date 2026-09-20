"""Create an explicitly requested downstream run from an immutable review snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any, NoReturn, cast
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_service import (
    CreateRunResult,
    FlowRunService,
    find_prefix_seed_replay,
)
from eneo.flows.application.flow_transcript_corrections_service import (
    extract_transcription_segments,
)
from eneo.flows.domain.flow import FlowRunStatus, FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.speaker_labels import apply_speaker_names, render_line_prefix
from eneo.flows.domain.speaker_review import attribution_text
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.domain.transcript_corrections import (
    SUPPORTED_TRANSCRIPT_CORRECTIONS_SCHEMA_VERSIONS,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptSpeakerEditInvalidError,
    apply_to_rendered_transcript,
    segments_content_hash,
    validate_correction_partitions,
    validate_occurrences,
    validate_speaker_edits,
)
from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
from eneo.flows.domain.transcript_words import locate_words
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_input_envelope import (
    read_semantic_flow_input_payload,
)
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_corrections_repo import (
    FlowTranscriptCorrectionsRepository,
)
from eneo.flows.infrastructure.flow_transcript_words_repo import (
    FlowTranscriptWordsRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.speaker_mapping_runtime import mapping_to_names
from eneo.main.exceptions import NotFoundException
from eneo.users.user import UserInDB


def _invalid(reason: str, *, conflict: bool = False) -> NoReturn:
    raise FlowBadRequestException(
        "The reviewed transcript cannot be regenerated with this request.",
        code=(
            FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION
            if conflict
            else FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE
        ),
        context={"reason": reason},
    )


def render_original_segments(segments: list[dict[str, Any]]) -> str:
    """Render immutable source evidence, even if an earlier approval changed output text."""
    lines: list[str] = []
    previous_file = None
    multiple = len({segment.get("file_index", 0) for segment in segments}) > 1
    for segment in segments:
        file_index = segment.get("file_index", 0)
        if (multiple or file_index != 0) and file_index != previous_file:
            if lines:
                lines.append("")
            lines.extend([f"## Del {file_index + 1}", ""])
        previous_file = file_index
        lines.append(
            render_line_prefix(segment["start"], segment["end"])
            + attribution_text(segment)
            + segment["text"]
        )
    return "\n".join(lines)


class FlowTranscriptRegenerationService:
    def __init__(
        self,
        *,
        user: UserInDB,
        run_service: FlowRunService,
        access_policy: FlowRunAccessPolicy,
        run_repo: FlowRunRepository,
        corrections_repo: FlowTranscriptCorrectionsRepository,
        words_repo: FlowTranscriptWordsRepository,
        audit_service: AuditService,
    ):
        self.user = user
        self.run_service = run_service
        self.access_policy = access_policy
        self.run_repo = run_repo
        self.corrections_repo = corrections_repo
        self.words_repo = words_repo
        self.audit_service = audit_service

    async def regenerate(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        expected_run_revision: int,
        expected_correction_revision: int | None,
        segments_hash: str,
        idempotency_key: str,
    ) -> CreateRunResult:
        source = await self.access_policy.load_run(
            flow_id=flow_id,
            run_id=run_id,
            access_kind="content",
        )
        key = idempotency_key.strip()
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": "transcript_regeneration_v1",
                    "source_run_id": str(run_id),
                    "step_id": str(step_id),
                    "run_revision": expected_run_revision,
                    "correction_revision": expected_correction_revision,
                    "segments_hash": segments_hash,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = await find_prefix_seed_replay(
            run_repo=self.run_repo,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            principal=FlowPrincipal.from_user(self.user),
            idempotency_key=key,
            request_hash=request_hash,
        )
        if existing is not None:
            return existing
        if source.status != FlowRunStatus.COMPLETED:
            _invalid("source_run_not_completed")
        if source.revision != expected_run_revision:
            _invalid("source_run_changed", conflict=True)
        result = await self.run_repo.get_step_result(
            run_id=source.id,
            tenant_id=self.user.tenant_id,
            step_id=step_id,
            for_update=True,
        )
        if result is None:
            raise NotFoundException("Flow run transcription step not found.")
        segments = extract_transcription_segments(result.input_payload_json)
        if not segments or segments_content_hash(segments) != segments_hash:
            _invalid("stale_segments", conflict=True)
        corrections = await self.corrections_repo.get_for_step(
            run_id=run_id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        if (
            corrections.revision if corrections else None
        ) != expected_correction_revision:
            _invalid("correction_revision_changed", conflict=True)
        if corrections and (
            corrections.segments_hash != segments_hash
            or corrections.schema_version
            not in SUPPORTED_TRANSCRIPT_CORRECTIONS_SCHEMA_VERSIONS
        ):
            _invalid("stale_or_unsupported_corrections", conflict=True)
        occurrences = corrections.occurrences() if corrections else []
        edits = corrections.speaker_edits() if corrections else []
        try:
            validate_occurrences(segments, occurrences)
            validate_speaker_edits(segments, edits)
            validate_correction_partitions(occurrences, edits)
        except (
            TranscriptCorrectionInvalidOccurrenceError,
            TranscriptSpeakerEditInvalidError,
        ):
            _invalid("invalid_correction_anchors", conflict=True)
        words = await self.words_repo.get_for_step(
            run_id=run_id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        words_by_segment = (
            {
                entry["segment_index"]: locate_words(
                    cast(str, segments[entry["segment_index"]]["text"]), entry["words"]
                )
                for entry in words.words_json
                if 0 <= entry["segment_index"] < len(segments)
            }
            if words and words.segments_hash == segments_hash
            else None
        )
        reviewed = apply_to_rendered_transcript(
            render_original_segments(segments),
            segments,
            occurrences,
            edits,
            words_by_segment,
        )
        if reviewed is None:
            _invalid("reviewed_transcript_not_renderable")
        view = await self.run_service.get_run_versioned_view(
            flow_id=flow_id, run_id=run_id
        )
        steps = sorted(
            view.published_definition.runtime_steps(), key=lambda step: step.step_order
        )
        # The versioned view carries step annotations only; the prefix replay
        # needs the persisted output payloads, so read the complete rows here.
        step_results = await self.run_repo.list_step_results(
            run_id=source.id, tenant_id=self.user.tenant_id
        )
        stored = {step.step_id: step for step in step_results}
        if not steps or steps[0].step_id != step_id:
            _invalid("transcription_must_be_first_step")
        # Reuse only the transcription and its immediate speaker naming checkpoint.
        # Arbitrary intermediate outputs may depend on old text and must execute again.
        prefix_steps = [steps[0]]
        if len(steps) > 1 and steps[1].output_mode == "speaker_mapping":
            prefix_steps.append(steps[1])
        downstream = steps[len(prefix_steps) :]
        if not downstream or any(
            step.input_type == "audio" or step.output_mode == "speaker_mapping"
            for step in downstream
        ):
            _invalid("unsupported_downstream_transcription")
        prefix: list[FlowStepResult] = []
        for step in prefix_steps:
            previous = stored.get(step.step_id)
            if previous is None or previous.status != FlowStepResultStatus.COMPLETED:
                _invalid("source_prefix_incomplete")
            payload = previous.output_payload_json or {}
            try:
                if isinstance(interpret_step_text(payload), FileBackedStepText):
                    _invalid("file_backed_prefix_unsupported")
            except StepOutputMetadataError:
                _invalid("invalid_prefix_output")
            if step.output_mode == "speaker_mapping":
                extension = payload.get("speaker_mapping")
                mapping = payload.get("structured")
                if (
                    not isinstance(extension, dict)
                    or cast(dict[str, Any], extension).get("source_step_id")
                    != str(step_id)
                    or cast(dict[str, Any], extension).get("source_attempt_no")
                    != result.current_attempt_no
                    or not isinstance(mapping, dict)
                ):
                    _invalid("speaker_mapping_source_changed", conflict=True)
                reviewed = apply_speaker_names(
                    reviewed, mapping_to_names(cast(dict[str, Any], mapping))
                )
                payload = {
                    **payload,
                    "text": reviewed,
                    "speaker_mapping": {
                        **cast(dict[str, Any], extension),
                        "source_attempt_no": 1,
                    },
                }
            else:
                payload = {**payload, "text": reviewed}
            prefix.append(previous.model_copy(update={"output_payload_json": payload}))
        provenance = {
            "version": 1,
            "source_run_id": str(source.id),
            "source_run_revision": source.revision,
            "source_flow_version": source.flow_version,
            "transcription_step_id": str(step_id),
            "correction_revision": expected_correction_revision,
            "segments_hash": segments_hash,
            "request_hash": request_hash,
            "reviewed_text_hash": hashlib.sha256(reviewed.encode()).hexdigest(),
            "first_regenerated_step_id": str(downstream[0].step_id),
        }
        files = await self.run_repo.list_current_step_input_file_ids_by_step_result_id(
            run_id=source.id,
            tenant_id=self.user.tenant_id,
            step_results=step_results,
        )
        step_inputs = {
            step.step_id: FlowRunStepInputFiles(file_ids=tuple(files[step.id]))
            for step in step_results
            if step.id is not None and files.get(step.id)
        }
        created = await self.run_service.create_run(
            flow_id=flow_id,
            run_label=source.run_label,
            input_payload_json=read_semantic_flow_input_payload(
                source.input_payload_json
            ),
            expected_flow_version=source.flow_version,
            step_inputs=step_inputs,
            idempotency_key=key,
            prefix_seed=FlowRunPrefixSeed(
                kind="reviewed_transcript_snapshot",
                source_run_id=source.id,
                transcript=reviewed,
                provenance=provenance,
                results=tuple(prefix),
            ),
        )
        if not created.created:
            return created
        if corrections:
            await self.corrections_repo.copy_snapshot(
                corrections=corrections, run_id=created.run.id
            )
        if words and words.segments_hash == segments_hash:
            await self.words_repo.upsert(
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                run_id=created.run.id,
                step_id=step_id,
                segments_hash=segments_hash,
                alignment=words.alignment,
                words_json=words.words_json,
            )
        try:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_CREATED,
                entity_type=EntityType.FLOW_RUN,
                entity_id=created.run.id,
                description="Created downstream run from a saved reviewed transcript",
                metadata=AuditMetadata.standard(
                    actor=self.user,
                    target=created.run,
                    extra={
                        "flow_id": str(flow_id),
                        "run_id": str(created.run.id),
                        "revision": created.run.revision,
                        "transcript_regeneration": provenance,
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
                run=created.run,
                action=ActionType.FLOW_RUN_CREATED,
                cause=exc,
            )
        return created
