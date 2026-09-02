"""Folding transcript corrections into a checkpoint's approved text."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_transcript_corrections_propagation import (
    build_folded_transcript,
)
from eneo.flows.domain.flow import FlowRunReviewCheckpoint
from eneo.flows.domain.transcript_corrections import (
    FlowTranscriptCorrectionSet,
    segments_content_hash,
)
from eneo.flows.enums import FlowOutputType, FlowRunReviewCheckpointState
from eneo.flows.flow_review_policy import FlowStepReviewMode

SEGMENTS = [
    {
        "file_index": 1,
        "start": 0.0,
        "end": 4.0,
        "speaker": "SPEAKER_00",
        "text": "Vi frågade sugary om planen.",
    },
    {
        "file_index": 1,
        "start": 4.0,
        "end": 8.0,
        "speaker": "SPEAKER_01",
        "text": "sugary svarade direkt.",
    },
]
RENDERED = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Vi frågade sugary om planen.",
        "[00:00:04 - 00:00:08] SPEAKER_01: sugary svarade direkt.",
    ]
)
OCCURRENCE = {
    "segment_index": 0,
    "char_start": 11,
    "char_end": 17,
    "original": "sugary",
    "corrected": "Çagri",
}
SPEAKER_EDIT = {
    "segment_index": 1,
    "char_start": None,
    "char_end": None,
    "original": None,
    "original_speaker": "SPEAKER_01",
    "speaker": "SPEAKER_03",
}


def _checkpoint(payload: dict[str, object] | None) -> FlowRunReviewCheckpoint:
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        original_payload_json=payload,
        current_payload_json=payload,
        step_label="Transkribera mötet",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.TEXT,
        output_contract_json=None,
        requester_user_id=uuid4(),
        requester_service_id=None,
        requester_principal_type=PrincipalType.USER,
        decided_by_user_id=None,
        decided_by_service_id=None,
        decided_by_principal_type=None,
        next_step_ids_json=[],
        resume_idempotency_key=None,
        edited_at=None,
        decided_at=None,
        resumed_at=None,
        expires_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _correction_set(
    *,
    occurrences_json: list[dict] | None = None,
    speaker_edits_json: list[dict] | None = None,
    segments_hash: str | None = None,
) -> FlowTranscriptCorrectionSet:
    return FlowTranscriptCorrectionSet(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        occurrences_json=occurrences_json if occurrences_json is not None else [],
        speaker_edits_json=(
            speaker_edits_json if speaker_edits_json is not None else []
        ),
        revision=1,
        schema_version=2,
        segments_hash=(
            segments_hash
            if segments_hash is not None
            else segments_content_hash(SEGMENTS)
        ),
        edited_by_user_id=uuid4(),
        edited_by_service_id=None,
        edited_by_principal_type=PrincipalType.USER,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _step_result(*, segments=SEGMENTS, attempt_no: int = 1):
    return SimpleNamespace(
        current_attempt_no=attempt_no,
        input_payload_json={"transcription": {"segments": segments}},
    )


def test_folds_corrections_and_speaker_edits_into_aligned_text() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint({"text": RENDERED, "provider": "kept"}),
        step_result=_step_result(),
        correction_set=_correction_set(
            occurrences_json=[OCCURRENCE], speaker_edits_json=[SPEAKER_EDIT]
        ),
    )

    assert outcome.propagated is True
    assert outcome.skip_reason is None
    assert outcome.previous_text == RENDERED
    assert outcome.folded_payload == {
        "text": "\n".join(
            [
                "[00:00:00 - 00:00:04] SPEAKER_00: Vi frågade Çagri om planen.",
                "[00:00:04 - 00:00:08] SPEAKER_03: sugary svarade direkt.",
            ]
        ),
        "provider": "kept",
    }


def test_skips_when_the_set_is_stale() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint({"text": RENDERED}),
        step_result=_step_result(),
        correction_set=_correction_set(
            occurrences_json=[OCCURRENCE], segments_hash="0" * 64
        ),
    )

    assert outcome.propagated is False
    assert outcome.skip_reason == "stale_corrections"


def test_skips_when_the_text_was_hand_edited() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint({"text": RENDERED.replace("svarade", "sa")}),
        step_result=_step_result(),
        correction_set=_correction_set(occurrences_json=[OCCURRENCE]),
    )

    assert outcome.propagated is False
    assert outcome.skip_reason == "text_not_aligned"


def test_skips_when_the_step_was_retried_after_the_checkpoint() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint({"text": RENDERED}),
        step_result=_step_result(attempt_no=2),
        correction_set=_correction_set(occurrences_json=[OCCURRENCE]),
    )

    assert outcome.propagated is False
    assert outcome.skip_reason == "attempt_mismatch"


def test_skips_when_the_step_stored_no_segments() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint({"text": RENDERED}),
        step_result=SimpleNamespace(current_attempt_no=1, input_payload_json={}),
        correction_set=_correction_set(occurrences_json=[OCCURRENCE]),
    )

    assert outcome.propagated is False
    assert outcome.skip_reason == "segments_unavailable"


def test_skips_when_the_checkpoint_has_no_payload() -> None:
    outcome = build_folded_transcript(
        checkpoint=_checkpoint(None),
        step_result=_step_result(),
        correction_set=_correction_set(occurrences_json=[OCCURRENCE]),
    )

    assert outcome.propagated is False
    assert outcome.skip_reason == "payload_missing"
