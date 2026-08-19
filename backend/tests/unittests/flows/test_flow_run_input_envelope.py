from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS,
    FlowRunInputEnvelopePatch,
    build_initial_run_input_envelope,
    read_semantic_flow_input_payload,
)
from eneo.flows.flow_run_payload_validation import reject_reserved_input_payload_keys
from eneo.flows.runtime.step_input_resolution import resolve_input_source_text
from eneo.main.exceptions import BadRequestException


def test_reserved_keys_include_runtime_transcription_cache() -> None:
    assert FLOW_INPUT_TRANSCRIPTION_KEY in FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS


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
