"""Publish refuses source refs the run would render wrongly or cannot resolve."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.flow_validators import validate_steps

_CONTRACT = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _step(step_order: int, **updates: object) -> FlowStep:
    step = FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Steg {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )
    return step.model_copy(update=updates)


def _flow(*source_refs: dict[str, str]) -> list[FlowStep]:
    return [
        _step(1, output_type="json", output_contract=_CONTRACT),
        _step(2),
        _step(3, input_bindings={"source_refs": list(source_refs)}),
    ]


def _publish(steps: list[FlowStep]) -> None:
    validate_steps(steps, require_complete_template_fill_config=True)


def test_publish_accepts_distinct_source_refs() -> None:
    _publish(
        _flow(
            {"step_ref": "step_1", "output": "structured", "field_path": "summary"},
            {"step_ref": "step_2", "output": "text"},
        )
    )


def test_publish_refuses_a_source_ref_listed_twice() -> None:
    ref = {"step_ref": "step_2", "output": "text"}

    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(ref, {**ref, "label": "Igen"}))

    assert caught.value.step_order == 3
    assert caught.value.context is not None
    assert caught.value.context["field"] == "input_bindings.source_refs"
    assert "more than once" in str(caught.value)


def test_draft_save_keeps_a_source_ref_listed_twice() -> None:
    ref = {"step_ref": "step_2", "output": "text"}

    validate_steps(_flow(ref, ref))


@pytest.mark.parametrize(
    ("ref", "detail"),
    [
        pytest.param(
            {"step_ref": "step_2", "output": "structured", "field_path": "summary"},
            "yields text",
            id="text-producer",
        ),
        pytest.param(
            {"step_ref": "step_1", "output": "structured", "field_path": "titel"},
            "titel",
            id="undeclared-field",
        ),
    ],
)
def test_publish_refuses_a_structured_source_ref_the_producer_lacks(
    ref: dict[str, str], detail: str
) -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(ref))

    assert caught.value.step_order == 3
    assert detail in str(caught.value)
