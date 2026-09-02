"""Fold a step's transcript corrections into its review-approved text.

When a review checkpoint is approved, the corrections and speaker edits stored
for that checkpoint's step are folded into the two continuation surfaces the
rest of the run reads: the checkpoint's ``current_payload_json.text`` (mirrored
to the step result's output) and, via the caller, the run-level transcript
variable. The stored raw segments are never rewritten, so the correction set
stays valid as the display overlay for the segments view.

Folding never blocks an approval: any foldability problem (stale set,
hand-edited text, file-backed output) is reported as a skip reason instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.application.flow_transcript_corrections_service import (
    extract_transcription_segments,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRunReviewCheckpoint,
    FlowStepResult,
)
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.domain.transcript_corrections import (
    FlowTranscriptCorrectionSet,
    apply_to_rendered_transcript,
    segments_content_hash,
)


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionsFoldOutcome:
    """What happened to a step's corrections when its checkpoint was approved."""

    correction_set: FlowTranscriptCorrectionSet
    """The set that existed for the checkpoint's step (never empty)."""
    previous_text: str | None
    """The checkpoint's inline text before folding, when it was readable."""
    folded_payload: FlowPersistedJsonObject | None
    """The checkpoint payload with the folded text, or None when skipped."""
    skip_reason: str | None

    @property
    def propagated(self) -> bool:
        return self.folded_payload is not None


def _skip(
    correction_set: FlowTranscriptCorrectionSet,
    reason: str,
    previous_text: str | None = None,
) -> TranscriptCorrectionsFoldOutcome:
    return TranscriptCorrectionsFoldOutcome(
        correction_set=correction_set,
        previous_text=previous_text,
        folded_payload=None,
        skip_reason=reason,
    )


def build_folded_transcript(
    *,
    checkpoint: FlowRunReviewCheckpoint,
    step_result: FlowStepResult | None,
    correction_set: FlowTranscriptCorrectionSet,
) -> TranscriptCorrectionsFoldOutcome:
    """Fold ``correction_set`` into the checkpoint's inline text, or skip.

    The fold requires the checkpoint text to still align 1:1 with the stored
    raw segments (``apply_to_rendered_transcript``) and the set to anchor to
    the segments as currently stored (content hash). Nothing is ever
    partial-applied.
    """
    payload = checkpoint.current_payload_json
    if payload is None:
        return _skip(correction_set, "payload_missing")
    try:
        step_text = interpret_step_text(payload)
    except StepOutputMetadataError:
        return _skip(correction_set, "payload_invalid")
    if isinstance(step_text, FileBackedStepText):
        return _skip(correction_set, "file_backed_output")
    previous_text = step_text.text
    if step_result is None:
        return _skip(correction_set, "step_result_missing", previous_text)
    if (
        step_result.current_attempt_no is not None
        and step_result.current_attempt_no != checkpoint.attempt_no
    ):
        return _skip(correction_set, "attempt_mismatch", previous_text)
    segments = extract_transcription_segments(step_result.input_payload_json)
    if segments is None:
        return _skip(correction_set, "segments_unavailable", previous_text)
    if segments_content_hash(segments) != correction_set.segments_hash:
        return _skip(correction_set, "stale_corrections", previous_text)
    folded_text = apply_to_rendered_transcript(
        previous_text,
        segments,
        correction_set.occurrences(),
        correction_set.speaker_edits(),
    )
    if folded_text is None:
        return _skip(correction_set, "text_not_aligned", previous_text)
    folded_payload: FlowPersistedJsonObject = {**payload, "text": folded_text}
    return TranscriptCorrectionsFoldOutcome(
        correction_set=correction_set,
        previous_text=previous_text,
        folded_payload=folded_payload,
        skip_reason=None,
    )
