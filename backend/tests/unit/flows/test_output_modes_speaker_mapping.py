from __future__ import annotations

import pytest

from eneo.flows.enums import FlowInputType, FlowOutputMode, FlowOutputType
from eneo.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    supports_step_io_tuple,
)
from eneo.flows.output_modes import speaker_mapping_violation


@pytest.mark.parametrize(
    ("input_source", "input_type", "output_type", "ok"),
    [
        ("previous_step", "text", "json", True),
        ("flow_input", "text", "json", False),
        ("previous_step", "audio", "json", False),
        ("previous_step", "text", "text", False),
    ],
)
def test_speaker_mapping_requires_previous_step_text_to_json(
    input_source: str, input_type: str, output_type: str, ok: bool
) -> None:
    error = speaker_mapping_violation(
        step_order=2,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_mode="speaker_mapping",
    )
    assert (error is None) is ok


def test_other_modes_are_not_affected() -> None:
    assert (
        speaker_mapping_violation(
            step_order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="text",
            output_mode="transcribe_only",
        )
        is None
    )


def test_manifest_io_rule_and_exposure() -> None:
    assert supports_step_io_tuple(
        input_type=FlowInputType.TEXT,
        output_type=FlowOutputType.JSON,
        output_mode=FlowOutputMode.SPEAKER_MAPPING,
    )
    assert not supports_step_io_tuple(
        input_type=FlowInputType.TEXT,
        output_type=FlowOutputType.TEXT,
        output_mode=FlowOutputMode.SPEAKER_MAPPING,
    )
    capability = CAPABILITY_REGISTRY["output_mode_speaker_mapping"]
    assert capability.exposure == "not_exposed"
    assert capability.not_exposed_reason
    assert "temporary" not in capability.not_exposed_reason.lower()
