from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from intric.flows.domain.flow import RerunStepInputOverride
from intric.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS,
    RERUN_PRESERVED_INPUT_PAYLOAD_KEYS,
    FlowRunInputEnvelopePatch,
    RerunInputOverride,
    build_initial_run_input_envelope,
    build_rerun_execution_input_envelope,
    read_semantic_flow_input_payload,
)
from intric.flows.flow_run_payload_validation import reject_reserved_input_payload_keys
from intric.flows.runtime.step_input_resolution import resolve_input_source_text
from intric.main.exceptions import BadRequestException


def test_preserved_keys_include_runtime_transcription_cache() -> None:
    assert FLOW_INPUT_TRANSCRIPTION_KEY in RERUN_PRESERVED_INPUT_PAYLOAD_KEYS


def test_reserved_keys_include_runtime_transcription_cache() -> None:
    assert FLOW_INPUT_TRANSCRIPTION_KEY in FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS


def test_preserved_keys_exclude_removed_top_level_file_ids() -> None:
    assert "file_ids" not in RERUN_PRESERVED_INPUT_PAYLOAD_KEYS


def test_initial_run_input_envelope_stores_version_without_step_inputs() -> None:
    payload = build_initial_run_input_envelope(
        normalized_inline_payload={"case_id": "A-123"},
        flow_version=4,
    )

    assert payload == {
        "case_id": "A-123",
        "expected_flow_version": 4,
    }
    assert "file_ids" not in payload
    assert "step_inputs" not in payload


def test_read_semantic_flow_input_payload_strips_runtime_keys_and_returns_copy() -> (
    None
):
    payload = {
        "case_id": "A-123",
        "expected_flow_version": 4,
        "step_inputs": {
            "00000000-0000-0000-0000-000000000017": {
                "file_ids": ["00000000-0000-0000-0000-000000000018"]
            }
        },
        "file_ids": ["removed-top-level-file"],
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }

    semantic_payload = read_semantic_flow_input_payload(payload)
    semantic_payload["case_id"] = "changed"

    assert semantic_payload == {"case_id": "changed"}
    assert payload["case_id"] == "A-123"


def test_transcription_patch_has_named_merge_shape() -> None:
    patch = FlowRunInputEnvelopePatch.transcription(transcript="transcribed text")

    assert isinstance(patch, FlowRunInputEnvelopePatch)
    assert patch.to_merge_dict() == {FLOW_INPUT_TRANSCRIPTION_KEY: "transcribed text"}
    assert patch.apply_to({"case_id": "A-123"}) == {
        "case_id": "A-123",
        FLOW_INPUT_TRANSCRIPTION_KEY: "transcribed text",
    }


def test_transcription_patch_applies_and_survives_rerun_round_trip() -> None:
    current = {
        "case_id": "A-123",
        "expected_flow_version": 2,
        "step_inputs": {"step-a": {"file_ids": ["file-a"]}},
    }
    patched = {
        **current,
        **FlowRunInputEnvelopePatch.transcription(
            transcript="cached transcript"
        ).to_merge_dict(),
    }

    payload = build_rerun_execution_input_envelope(
        current=patched,
        override=RerunInputOverride(),
    )

    assert payload == {
        "case_id": "A-123",
        "expected_flow_version": 2,
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }
    assert payload is not patched


@pytest.mark.parametrize("reserved_key", sorted(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS))
def test_reserved_input_payload_keys_are_rejected_and_stripped(
    reserved_key: str,
) -> None:
    with pytest.raises(BadRequestException):
        reject_reserved_input_payload_keys({reserved_key: "value"})

    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "case_id": "A-123",
            reserved_key: "value",
        },
    )

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == '{"case_id": "A-123"}'


def test_rerun_execution_payload_preserves_current_payload_without_overrides() -> None:
    current = {
        "case_id": "case-123",
        "file_ids": ["historic-top-level-file"],
        "expected_flow_version": 3,
        "step_inputs": {"step-a": {"file_ids": ["file-a"]}},
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }

    payload = build_rerun_execution_input_envelope(
        current=current,
        override=RerunInputOverride(),
    )

    assert payload == {
        "case_id": "case-123",
        "expected_flow_version": 3,
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }
    assert payload is not current


def test_rerun_execution_payload_step_inputs_override_removes_runtime_file_keys() -> (
    None
):
    step_id = UUID("00000000-0000-0000-0000-000000000021")
    old_file_id = UUID("00000000-0000-0000-0000-000000000022")
    replacement_file_id = UUID("00000000-0000-0000-0000-000000000023")

    payload = build_rerun_execution_input_envelope(
        current={
            "case_id": "case-123",
            "file_ids": ["removed-top-level-file"],
            "expected_flow_version": 3,
            "step_inputs": {str(step_id): {"file_ids": [str(old_file_id)]}},
            FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
        },
        override=RerunInputOverride(
            root_step_input=RerunStepInputOverride(
                step_id=step_id,
                file_ids=(replacement_file_id,),
            ),
        ),
    )

    assert payload == {
        "case_id": "case-123",
        "expected_flow_version": 3,
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }


def test_rerun_execution_payload_replaces_semantic_keys_and_preserves_runtime_cache() -> (
    None
):
    payload = build_rerun_execution_input_envelope(
        current={
            "name": "alice",
            "obsolete": True,
            "expected_flow_version": 3,
            "file_ids": ["removed-top-level-file"],
            "step_inputs": {"step-a": {"file_ids": ["file-a"]}},
            FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
        },
        override=RerunInputOverride(inline_payload_json={"name": "bob"}),
    )

    assert payload == {
        "name": "bob",
        "expected_flow_version": 3,
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }


def test_rerun_execution_payload_combined_override_removes_top_level_file_ids() -> None:
    step_id = UUID("00000000-0000-0000-0000-000000000041")
    replacement_file_id = UUID("00000000-0000-0000-0000-000000000042")

    payload = build_rerun_execution_input_envelope(
        current={
            "case_id": "case-123",
            "obsolete": True,
            "file_ids": ["removed-top-level-file"],
            "step_inputs": {str(step_id): {"file_ids": ["file-a"]}},
            FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
        },
        override=RerunInputOverride(
            inline_payload_json={"case_id": "case-456"},
            root_step_input=RerunStepInputOverride(
                step_id=step_id,
                file_ids=(replacement_file_id,),
            ),
        ),
    )

    assert payload == {
        "case_id": "case-456",
        FLOW_INPUT_TRANSCRIPTION_KEY: "cached transcript",
    }


def test_rerun_execution_payload_strips_stale_step_inputs_by_step_id() -> None:
    root_step_id = UUID("00000000-0000-0000-0000-000000000051")
    downstream_step_id = UUID("00000000-0000-0000-0000-000000000052")

    payload = build_rerun_execution_input_envelope(
        current={
            "case_id": "case-123",
            "step_inputs": {
                str(root_step_id): {"file_ids": ["file-a"], "api_key": "old"},
                str(downstream_step_id): {"file_ids": ["file-b"]},
            },
        },
        override=RerunInputOverride(
            root_step_input=RerunStepInputOverride(
                step_id=root_step_id,
                file_ids=(),
            ),
        ),
    )

    assert payload == {
        "case_id": "case-123",
    }


def test_rerun_execution_payload_builds_from_empty_current_payload() -> None:
    step_id = UUID("00000000-0000-0000-0000-000000000061")
    file_id = UUID("00000000-0000-0000-0000-000000000062")

    payload = build_rerun_execution_input_envelope(
        current=None,
        override=RerunInputOverride(
            inline_payload_json={"case_id": "case-456"},
            root_step_input=RerunStepInputOverride(
                step_id=step_id,
                file_ids=(file_id,),
            ),
        ),
    )

    assert payload == {
        "case_id": "case-456",
    }
