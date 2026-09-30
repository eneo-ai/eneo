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
        _step(3, output_mode="speaker_mapping"),
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
    steps = [_step(1), _step(2, output_mode="speaker_mapping")]

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
