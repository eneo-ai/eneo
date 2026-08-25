"""Review edits of a speaker-mapping step re-derive the transcript from the mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_review_checkpoint_service import (
    FlowRunReviewCheckpointService,
    build_edited_review_payload,
)
from eneo.flows.domain.flow import FlowRunReviewCheckpoint, FlowStepResult
from eneo.flows.domain.speaker_labels import SPEAKER_MAPPING_OUTPUT_CONTRACT
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunReviewCheckpointState,
    FlowStepResultStatus,
)
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.main.exceptions import NotFoundException, TypedIOValidationException

SOURCE = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej.",
        "[00:00:05 - 00:00:09] SPEAKER_01: Hallå.",
    ]
)
INVENTORY = [
    {
        "label": "SPEAKER_00",
        "file_index": 0,
        "file_id": None,
        "line_count": 1,
        "samples": ["Hej."],
    },
    {
        "label": "SPEAKER_01",
        "file_index": 0,
        "file_id": None,
        "line_count": 1,
        "samples": ["Hallå."],
    },
]
PROPOSAL = {
    "speakers": [
        {"label": "SPEAKER_00", "name": "Anna", "confidence": "high", "evidence": ""},
        {"label": "SPEAKER_01", "name": None, "confidence": "low", "evidence": ""},
    ]
}
SOURCE_STEP_ID = uuid4()


def _payload(text: str) -> dict[str, object]:
    return {
        "text": text,
        "structured": PROPOSAL,
        "speaker_mapping": {
            "source_step_id": str(SOURCE_STEP_ID),
            "source_step_order": 1,
            "source_attempt_no": 1,
            "participants": ["Anna", "Bo"],
            "participants_field": "deltagare",
            "inventory": INVENTORY,
        },
    }


def _checkpoint(payload: dict[str, object]) -> FlowRunReviewCheckpoint:
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=2,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        original_payload_json=payload,
        current_payload_json=payload,
        step_label="Namnge talare",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.JSON,
        output_contract_json=SPEAKER_MAPPING_OUTPUT_CONTRACT,
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


EDITED = {
    "speakers": [
        {"label": "SPEAKER_00", "name": "Anna", "confidence": "high", "evidence": ""},
        {
            "label": "SPEAKER_01",
            "name": "Okänd gäst",
            "confidence": "low",
            "evidence": "",
        },
    ]
}


def test_edit_reapplies_the_mapping_to_the_source_transcript() -> None:
    checkpoint = _checkpoint(_payload("[00:00:00 - 00:00:04] Anna: Hej.\n..."))

    payload = build_edited_review_payload(
        checkpoint=checkpoint, edited_value=EDITED, source_text=SOURCE
    )

    assert payload["text"] == "\n".join(
        [
            "[00:00:00 - 00:00:04] Anna: Hej.",
            "[00:00:05 - 00:00:09] Okänd gäst: Hallå.",
        ]
    )
    assert payload["structured"] == EDITED
    # The extension survives the edit so later edits can still find the source.
    assert payload["speaker_mapping"]["source_step_id"] == str(SOURCE_STEP_ID)


def test_edit_without_source_transcript_is_rejected() -> None:
    with pytest.raises(TypedIOValidationException):
        build_edited_review_payload(
            checkpoint=_checkpoint(_payload("x")), edited_value=EDITED, source_text=None
        )


def test_edit_with_unknown_label_is_rejected() -> None:
    bad = {"speakers": [{"label": "SPEAKER_07", "name": "Anna", "confidence": "high"}]}
    with pytest.raises(TypedIOValidationException):
        build_edited_review_payload(
            checkpoint=_checkpoint(_payload("x")), edited_value=bad, source_text=SOURCE
        )


def test_plain_json_checkpoints_are_unchanged() -> None:
    plain = {"text": "{}", "structured": {"a": 1}}
    checkpoint = _checkpoint(plain).model_copy(update={"output_contract_json": None})

    payload = build_edited_review_payload(checkpoint=checkpoint, edited_value={"a": 2})

    assert payload == {"text": '{"a": 2}', "structured": {"a": 2}}


def _service(checkpoint: FlowRunReviewCheckpoint, run, flow_run_repo):
    user = SimpleNamespace(id=uuid4(), tenant_id=checkpoint.tenant_id)
    checkpoint_repo = AsyncMock()
    checkpoint_repo.get_review_checkpoint_for_edit = AsyncMock(return_value=checkpoint)
    checkpoint_repo.edit_review_checkpoint_payload = AsyncMock(
        side_effect=lambda **kwargs: checkpoint.model_copy(
            update={"current_payload_json": kwargs["current_payload_json"]}
        )
    )
    access_policy = AsyncMock()
    access_policy.load_run = AsyncMock(return_value=run)
    return FlowRunReviewCheckpointService(
        user=user,  # type: ignore[arg-type]
        flow_run_review_checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
        flow_run_terminalizer=AsyncMock(),
        flow_run_repo=flow_run_repo,
    )


def _source_result(checkpoint: FlowRunReviewCheckpoint, text: str, attempt: int = 1):
    return FlowStepResult(
        flow_run_id=checkpoint.flow_run_id,
        flow_id=checkpoint.flow_id,
        tenant_id=checkpoint.tenant_id,
        step_id=SOURCE_STEP_ID,
        step_order=1,
        current_attempt_no=attempt,
        output_payload_json={"text": text},
        status=FlowStepResultStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def test_service_loads_source_and_syncs_run_transcript() -> None:
    checkpoint = _checkpoint(_payload("[00:00:00 - 00:00:04] Anna: Hej.\n..."))
    run = SimpleNamespace(
        id=checkpoint.flow_run_id,
        tenant_id=checkpoint.tenant_id,
        flow_id=checkpoint.flow_id,
        input_payload_json={"transkribering": SOURCE, "deltagare": "Anna, Bo"},
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get_step_result = AsyncMock(
        return_value=_source_result(checkpoint, SOURCE)
    )
    flow_run_repo.update_input_payload = AsyncMock(
        return_value={"transkribering": "new"}
    )
    service = _service(checkpoint, run, flow_run_repo)

    edited = await service.edit_review_checkpoint(
        flow_id=checkpoint.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=1,
        edited_value=EDITED,
    )

    assert "Okänd gäst: Hallå." in str(edited.current_payload_json["text"])
    patch = flow_run_repo.update_input_payload.await_args.kwargs["input_payload_patch"]
    assert (
        patch.to_merge_dict()["transkribering"] == edited.current_payload_json["text"]
    )


async def test_service_leaves_a_foreign_run_transcript_alone() -> None:
    checkpoint = _checkpoint(_payload("previous rendering"))
    run = SimpleNamespace(
        id=checkpoint.flow_run_id,
        tenant_id=checkpoint.tenant_id,
        flow_id=checkpoint.flow_id,
        input_payload_json={"transkribering": "something a later step wrote"},
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get_step_result = AsyncMock(
        return_value=_source_result(checkpoint, SOURCE)
    )
    service = _service(checkpoint, run, flow_run_repo)

    await service.edit_review_checkpoint(
        flow_id=checkpoint.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=1,
        edited_value=EDITED,
    )

    flow_run_repo.update_input_payload.assert_not_awaited()


async def test_service_rejects_missing_or_rerun_source_step() -> None:
    checkpoint = _checkpoint(_payload("x"))
    run = SimpleNamespace(
        id=checkpoint.flow_run_id,
        tenant_id=checkpoint.tenant_id,
        flow_id=checkpoint.flow_id,
        input_payload_json={},
    )
    missing = AsyncMock()
    missing.get_step_result = AsyncMock(return_value=None)
    with pytest.raises(NotFoundException):
        await _service(checkpoint, run, missing).edit_review_checkpoint(
            flow_id=checkpoint.flow_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=1,
            edited_value=EDITED,
        )

    rerun = AsyncMock()
    rerun.get_step_result = AsyncMock(
        return_value=_source_result(checkpoint, SOURCE, attempt=2)
    )
    with pytest.raises(FlowBadRequestException):
        await _service(checkpoint, run, rerun).edit_review_checkpoint(
            flow_id=checkpoint.flow_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=1,
            edited_value=EDITED,
        )
