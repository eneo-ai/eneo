"""Saved steps outside the authoring vocabulary are listed, never a bare error."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.application.flow_authoring_description_semantics import (
    FlowSemanticSignature,
)
from eneo.flows.application.flow_authoring_snapshot import (
    UnsupportedSavedStepsError,
    current_flow_authoring_spec,
    flow_step_to_authoring_spec,
    unsupported_saved_steps,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import (
    FlowAuthoringInputSource,
    FlowAuthoringInputType,
    FlowAuthoringOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import CapabilityProjection, projection_cells
from eneo.flows.flow_validators import validate_steps

_CREDENTIAL = "sk-live-credential-looking-value"


def _step(order: int, **overrides: object) -> FlowStep:
    fields: dict[str, object] = {
        "id": uuid4(),
        "assistant_id": uuid4(),
        "step_order": order,
        "user_description": f"Step named {order}",
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    fields.update(overrides)
    return FlowStep.model_validate(fields)


# The one legal speaker-mapping cell: the Builder inserts it after a transcription.
_SPEAKER_MAPPING: dict[str, object] = {
    "input_source": "previous_step",
    "output_type": "json",
    "output_mode": "speaker_mapping",
}

_UNSUPPORTED: dict[str, dict[str, object]] = {
    "http_get_input": {
        "input_source": "http_get",
        "input_config": {
            "url": "https://example.org/a",
            "auth": {"token": _CREDENTIAL},
        },
    },
    "image_input": {"input_type": "image"},
    "http_post_output": {
        "output_mode": "http_post",
        "output_config": {
            "url": "https://example.org/b",
            "auth": {"token": _CREDENTIAL},
        },
    },
}
_OFFENDING_FIELD = {
    "http_get_input": ("input_source", "http_get"),
    "image_input": ("input_type", "image"),
    "http_post_output": ("output_mode", "http_post"),
}


@pytest.mark.parametrize("shape", sorted(_UNSUPPORTED))
def test_projection_raises_the_typed_error_naming_the_step_and_field(
    shape: str,
) -> None:
    step = _step(2, **_UNSUPPORTED[shape])

    with pytest.raises(UnsupportedSavedStepsError) as caught:
        flow_step_to_authoring_spec(step, plan_ref="step_2")

    assert isinstance(caught.value, ValueError)
    [described] = caught.value.steps
    assert described.step_order == 2
    assert described.existing_step_ref == "existing_step_2"
    assert described.name == "Step named 2"
    assert described.fields == (_OFFENDING_FIELD[shape],)
    assert _CREDENTIAL not in str(caught.value)


def test_the_listing_reports_every_offending_step_in_order_and_never_raises() -> None:
    steps = [
        _step(1),
        _step(2, **_UNSUPPORTED["image_input"]),
        _step(3, **_SPEAKER_MAPPING),
        _step(
            4,
            user_description=None,
            **_UNSUPPORTED["http_get_input"],
            **{"output_mode": "http_post"},
        ),
    ]

    listed = unsupported_saved_steps(steps)

    assert [(item.step_order, item.name, item.fields) for item in listed] == [
        (2, "Step named 2", (("input_type", "image"),)),
        (
            4,
            "existing_step_4",
            (("input_source", "http_get"), ("output_mode", "http_post")),
        ),
    ]
    assert unsupported_saved_steps([]) == ()


def test_a_speaker_mapping_step_and_authorable_steps_still_project() -> None:
    steps = [_step(1), _step(2, **_SPEAKER_MAPPING)]

    assert unsupported_saved_steps(steps) == ()
    spec = current_flow_authoring_spec(
        current_steps=steps,
        flow_name="f",
        flow_description="",
        assistant_snapshots=None,
    )
    assert [step.output_mode.value for step in spec.steps] == [
        "pass_through",
        "speaker_mapping",
    ]


def test_the_whole_flow_projection_fails_with_the_same_typed_error() -> None:
    with pytest.raises(UnsupportedSavedStepsError):
        current_flow_authoring_spec(
            current_steps=[_step(1), _step(2, **_UNSUPPORTED["image_input"])],
            flow_name="f",
            flow_description="",
            assistant_snapshots=None,
        )


def test_the_description_signature_reads_the_same_owner() -> None:
    with pytest.raises(UnsupportedSavedStepsError):
        FlowSemanticSignature.from_flow_steps(
            [_step(1), _step(2, **_UNSUPPORTED["http_get_input"]), _step(3)]
        )


def test_a_saved_step_is_listed_exactly_when_an_axis_value_is_outside_the_authoring_vocabulary() -> (
    None
):
    # A per-axis portability check against the authoring vocabulary. Every
    # inspectable cell is run through it: HTTP cells are inspectable but not
    # portable. Whether a combination may run is the platform validators' call.
    authorable = (
        {item.value for item in FlowAuthoringInputSource},
        {item.value for item in FlowAuthoringInputType},
        {item.value for item in FlowOutputType},
        {item.value for item in FlowAuthoringOutputMode},
    )
    for cell in projection_cells(CapabilityProjection.INSPECTABLE):
        step = _step(
            1,
            input_source=cell[0].value,
            input_type=cell[1].value,
            output_type=cell[2].value,
            output_mode=cell[3].value,
        )
        inside = all(
            member.value in allowed for member, allowed in zip(cell, authorable)
        )
        assert bool(unsupported_saved_steps([step])) is (not inside), cell


def test_a_json_step_followed_by_a_bound_all_previous_steps_json_step_projects() -> (
    None
):
    # The manifest has no cell for all_previous_steps + json (concatenated text
    # is not JSON) but the platform validators accept it when typed source_refs
    # and an input_contract supply the input. The listing is a per-axis
    # portability check, so such a step is portable although no cell covers it.
    producer_contract: dict[str, object] = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }
    bindings = {
        "source_refs": [
            {"step_ref": "step_1", "output": "structured", "field_path": "title"}
        ]
    }
    consumer_contract: dict[str, object] = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }
    steps = [
        _step(1, output_type="json", output_contract=producer_contract),
        _step(
            2,
            input_source="all_previous_steps",
            input_type="json",
            input_bindings=bindings,
            input_contract=consumer_contract,
        ),
    ]

    validate_steps(steps)
    assert unsupported_saved_steps(steps) == ()
    spec = current_flow_authoring_spec(
        current_steps=steps,
        flow_name="f",
        flow_description="",
        assistant_snapshots=None,
    )
    assert [step.input_type.value for step in spec.steps] == ["text", "json"]
    assert spec.steps[1].input_bindings == bindings
    assert spec.steps[1].input_contract == consumer_contract
