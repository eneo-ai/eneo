"""Uploads and mapped steps the run can execute as authored."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from eneo.files.text import TEXT_EXTRACTION_WARNINGS
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
)
from eneo.flows.flow_validators import validate_steps


def _step(step_order: int, **updates: object) -> FlowStep:
    step = FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Steg {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
    )
    return step.model_copy(update=updates)


def _array_of_objects(key: str, **item_properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": item_properties,
                    "required": list(item_properties),
                },
            }
        },
        "required": [key],
    }


_DOCUMENTS = _array_of_objects(
    "documents",
    summary={"type": "string"},
    source_label={"type": "string"},
    source_file_id={"type": "string"},
    extraction_warnings={
        "type": "array",
        "items": {"type": "string", "enum": sorted(TEXT_EXTRACTION_WARNINGS)},
    },
)
_ITEMS = _array_of_objects("items", title={"type": "string"})
_TRANSCRIBED = {
    "wizard": {
        "transcription_enabled": True,
        "transcription_model": {"id": str(uuid4())},
        "transcription_language": "sv",
    }
}


def _reader(output_contract: dict[str, Any] | None) -> FlowStep:
    return _step(
        1,
        input_type="document",
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "execution_mode": "per_source",
                "max_files": 2,
            }
        },
        output_contract=output_contract,
    )


def _item_map(
    input_contract: dict[str, Any] | None, output_contract: dict[str, Any] | None
) -> FlowStep:
    return _step(
        2,
        input_type="json",
        input_config={"item_map": {"enabled": True, "max_items": 2}},
        input_contract=input_contract,
        output_contract=output_contract,
    )


def _publish(steps: list[FlowStep]) -> None:
    validate_steps(steps, require_complete_template_fill_config=True)


def test_publish_accepts_mapped_steps_with_mappable_contracts() -> None:
    _publish([_reader(_DOCUMENTS), _item_map(_DOCUMENTS, _ITEMS)])


@pytest.mark.parametrize(
    ("steps", "field"),
    [
        pytest.param([_reader(_ITEMS)], "output_contract", id="reader-not-documents"),
        pytest.param([_reader(None)], "output_contract", id="reader-no-contract"),
        pytest.param(
            [_reader(_DOCUMENTS), _item_map(None, _ITEMS)],
            "input_contract",
            id="map-no-input-array",
        ),
        pytest.param(
            [_reader(_DOCUMENTS), _item_map(_DOCUMENTS, None)],
            "output_contract",
            id="map-no-output-array",
        ),
    ],
)
def test_publish_refuses_mapped_steps_the_run_cannot_map(
    steps: list[FlowStep], field: str
) -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(steps)

    assert caught.value.code == FlowGraphIssueCode.FLOW_STEP_INVALID.value
    assert caught.value.context is not None
    assert caught.value.context["field"] == field


def test_draft_save_keeps_a_mapped_step_without_its_contracts() -> None:
    validate_steps([_reader(None), _item_map(None, None)])


@pytest.mark.parametrize("input_format", ["document", "file"])
def test_save_refuses_an_audio_step_that_takes_other_uploads(input_format: str) -> None:
    step = _step(
        1,
        input_type="audio",
        output_type="text",
        input_config={"runtime_input": {"enabled": True, "input_format": input_format}},
    )

    with pytest.raises(FlowStepValidationError) as caught:
        validate_steps([step], metadata_json=_TRANSCRIBED)

    assert caught.value.context is not None
    assert caught.value.context["field"] == "input_config.runtime_input.input_format"


@pytest.mark.parametrize(
    ("input_type", "input_format"),
    [("text", "document"), ("document", "audio"), ("audio", "audio")],
)
def test_save_lets_a_step_take_uploads_it_can_read(
    input_type: str, input_format: str
) -> None:
    validate_steps(
        [
            _step(
                1,
                input_type=input_type,
                output_type="text",
                input_config={
                    "runtime_input": {"enabled": True, "input_format": input_format}
                },
            )
        ],
        metadata_json=_TRANSCRIBED,
    )
