"""Fold a step's transcript corrections into its review-approved text.

When a review checkpoint is approved, the corrections and speaker edits stored
for the transcript it reviews are folded into the two continuation surfaces the
rest of the run reads: the checkpoint's ``current_payload_json.text`` (mirrored
to the step result's output) and, via the caller, the run-level transcript
variable. The stored raw segments are never rewritten, so the correction set
stays valid as the display overlay for the segments view.

The transcript a checkpoint reviews is its own text for a transcription step.
For a speaker-mapping step it is the *source* transcription step's output: the
corrections are folded into that label-form text and the caller rebuilds the
names-applied payload from it.

Folding never blocks an approval: any foldability problem (stale set,
hand-edited text, file-backed output) is reported as a skip reason instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
from eneo.flows.domain.transcript_words import LocatedWord
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.main.exceptions import TypedIOValidationException

RebuildFoldedPayload = Callable[[str], FlowPersistedJsonObject]
"""Derive the checkpoint payload from the folded source text.

Used when the checkpoint text is itself derived from the transcript (a
speaker-mapping step renders names over it), so the folded source has to go
through the same derivation instead of replacing the text directly.
"""


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionsFoldOutcome:
    """What happened to a step's corrections when its checkpoint was approved."""

    correction_set: FlowTranscriptCorrectionSet
    """The set that existed for the reviewed transcript's step (never empty)."""
    previous_text: str | None
    """The checkpoint's inline text before folding, when it was readable."""
    folded_payload: FlowPersistedJsonObject | None
    """The checkpoint payload with the folded text, or None when skipped."""
    skip_reason: str | None

    @property
    def propagated(self) -> bool:
        return self.folded_payload is not None


def skip_folded_transcript(
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
    source_text: str | None = None,
    expected_attempt_no: int | None = None,
    rebuild_payload: RebuildFoldedPayload | None = None,
    words_by_segment: Mapping[int, Sequence[LocatedWord]] | None = None,
) -> TranscriptCorrectionsFoldOutcome:
    """Fold ``correction_set`` into the reviewed transcript, or skip.

    ``step_result`` is the transcription step the set anchors to. By default
    the corrections fold into the checkpoint's own inline text and the step
    must be at ``checkpoint.attempt_no``. With ``source_text`` they fold into
    that text instead (the source step's output, at ``expected_attempt_no``
    when known) and ``rebuild_payload`` derives the checkpoint payload from
    the folded result. ``words_by_segment`` (the step's stored word timings,
    located in the raw text) lets a segment split between speakers render
    one timestamp window per run instead of repeating the segment's.

    The fold requires the text to still align 1:1 with the stored raw
    segments (``apply_to_rendered_transcript``) and the set to anchor to the
    segments as currently stored (content hash). Nothing is ever
    partial-applied.
    """
    payload = checkpoint.current_payload_json
    if payload is None:
        return skip_folded_transcript(correction_set, "payload_missing")
    try:
        step_text = interpret_step_text(payload)
    except StepOutputMetadataError:
        return skip_folded_transcript(correction_set, "payload_invalid")
    if isinstance(step_text, FileBackedStepText):
        return skip_folded_transcript(correction_set, "file_backed_output")
    previous_text = step_text.text
    if step_result is None:
        return skip_folded_transcript(
            correction_set, "step_result_missing", previous_text
        )
    if source_text is None:
        fold_text = previous_text
        expected_attempt = checkpoint.attempt_no
    else:
        fold_text = source_text
        expected_attempt = expected_attempt_no
    if (
        expected_attempt is not None
        and step_result.current_attempt_no is not None
        and step_result.current_attempt_no != expected_attempt
    ):
        return skip_folded_transcript(correction_set, "attempt_mismatch", previous_text)
    segments = extract_transcription_segments(step_result.input_payload_json)
    if segments is None:
        return skip_folded_transcript(
            correction_set, "segments_unavailable", previous_text
        )
    if segments_content_hash(segments) != correction_set.segments_hash:
        return skip_folded_transcript(
            correction_set, "stale_corrections", previous_text
        )
    folded_text = apply_to_rendered_transcript(
        fold_text,
        segments,
        correction_set.occurrences(),
        correction_set.speaker_edits(),
        words_by_segment=words_by_segment,
    )
    if folded_text is None:
        return skip_folded_transcript(correction_set, "text_not_aligned", previous_text)
    if rebuild_payload is None:
        folded_payload: FlowPersistedJsonObject = {**payload, "text": folded_text}
    else:
        try:
            folded_payload = rebuild_payload(folded_text)
        except (TypedIOValidationException, FlowBadRequestException):
            return skip_folded_transcript(
                correction_set, "payload_rebuild_failed", previous_text
            )
    return TranscriptCorrectionsFoldOutcome(
        correction_set=correction_set,
        previous_text=previous_text,
        folded_payload=folded_payload,
        skip_reason=None,
    )
