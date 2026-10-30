"""Publish refuses a prompt or HTTP request read the run cannot resolve."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
)
from eneo.flows.flow_validators import validate_steps

_FORM = {"form_schema": {"fields": [{"name": "kund", "type": "text"}]}}
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


def _flow() -> list[FlowStep]:
    return [
        _step(1, output_type="json", output_contract=_CONTRACT),
        _step(2),
        _step(3),
    ]


def _publish(steps: list[FlowStep], prompts: dict[int, str]) -> None:
    validate_steps(
        steps,
        metadata_json=_FORM,
        require_complete_template_fill_config=True,
        prompt_templates=prompts,
    )


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param("Kund: {{ kund }} och {{ flow_input.kund }}", id="form-field"),
        pytest.param("{{ step_1.output.structured.summary }}", id="declared-field"),
        pytest.param("{{ step_1.output.structured }}", id="structured"),
        pytest.param("{{ step_1.output.text }} {{ step_1 }}", id="text"),
        pytest.param("{{ step_1.status }} {{ step_1.error_message }}", id="status"),
        pytest.param("{{ Steg 1 }}", id="step-name"),
        pytest.param("{{ föregående_steg }} {{ datum }}", id="runtime"),
        pytest.param("{{ step_input.text }}", id="own-upload"),
    ],
)
def test_publish_accepts_prompt_reads_the_run_resolves(prompt: str) -> None:
    _publish(_flow(), {2: prompt})


@pytest.mark.parametrize(
    ("prompt", "code", "reference"),
    [
        pytest.param(
            "{{ step_3.output.text }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE,
            "step_3.output.text",
            id="later-step",
        ),
        pytest.param(
            "{{ step_2.output.text }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE,
            "step_2.output.text",
            id="own-result",
        ),
        pytest.param(
            "{{ Steg 3 }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE,
            "Steg 3",
            id="later-step-by-name",
        ),
        pytest.param(
            "{{ step_7.output.text }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER,
            "step_7.output.text",
            id="missing-step",
        ),
        pytest.param(
            "{{ kunden }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE,
            "kunden",
            id="undeclared-name",
        ),
        pytest.param(
            "{{ step_one.output.text }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE,
            "step_one.output.text",
            id="malformed-alias",
        ),
        pytest.param(
            "{{ Steg 1.output.text }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE,
            "Steg 1.output.text",
            id="path-below-step-name",
        ),
        pytest.param(
            "{{ flow_input.okänt }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            "flow_input.okänt",
            id="undeclared-run-input-key",
        ),
        pytest.param(
            "{{ kund.namn }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            "kund.namn",
            id="path-below-form-field",
        ),
        pytest.param(
            "{{ step_1.output.summary }}",
            FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            "step_1.output.summary",
            id="unsupported-step-path",
        ),
    ],
)
def test_publish_refuses_prompt_reads_the_run_cannot_resolve(
    prompt: str, code: FlowGraphIssueCode, reference: str
) -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(), {2: f"Läs {prompt}."})

    assert caught.value.code == code.value
    assert caught.value.step_order == 2
    assert caught.value.context is not None
    assert caught.value.context["field"] == "prompt"
    assert reference in str(caught.value)


def test_publish_refuses_previous_step_read_on_the_first_step() -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(), {1: "{{ föregående_steg }}"})

    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER.value
    )
    assert "previous step" in str(caught.value)


def test_publish_refuses_structured_read_of_a_text_step() -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(), {3: "{{ step_2.output.structured.summary }}"})

    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value
    )
    assert caught.value.step_order == 3
    assert "yields text" in str(caught.value)


def test_publish_refuses_structured_read_of_an_undeclared_field() -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish(_flow(), {2: "{{ step_1.output.structured.sammanfattning }}"})

    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value
    )
    assert "sammanfattning" in str(caught.value)


def test_draft_save_keeps_a_prompt_that_reads_a_later_step() -> None:
    validate_steps(_flow(), metadata_json=_FORM, prompt_templates={2: "{{ step_3 }}"})


def test_publish_ignores_the_prompt_of_a_step_without_a_model() -> None:
    steps = [
        _step(1, input_type="json", output_type="json"),
        _step(2, input_type="json", output_mode="copy_input", output_type="json"),
    ]

    _publish(steps, {2: "{{ step_5.output.text }}"})


def test_publish_refuses_an_http_request_that_reads_a_later_step() -> None:
    steps = [
        _step(1),
        _step(
            2,
            input_source="http_get",
            input_config={
                "url": "https://example.org/{{ step_3.output.text }}",
                "auth": {"mode": "none"},
            },
        ),
        _step(3),
    ]

    with pytest.raises(FlowStepValidationError) as caught:
        _publish(steps, {})

    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE.value
    )
    assert caught.value.context is not None
    assert caught.value.context["field"] == "input_config.url"


def test_publish_lets_a_webhook_read_its_own_step_result() -> None:
    def webhook(template: str) -> FlowStep:
        return _step(
            2,
            output_mode="http_post",
            output_config={
                "url": "https://example.org/hook",
                "auth": {"mode": "none"},
                "body": {"mode": "text_template", "template": template},
            },
        )

    _publish([_step(1), webhook("{{ step_2.output.text }}")], {})
    with pytest.raises(FlowStepValidationError) as caught:
        _publish([_step(1), webhook("{{ step_3.output.text }}")], {})

    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER.value
    )
    assert caught.value.context is not None
    assert caught.value.context["field"] == "output_config.body.template"


def _template_fill(binding: str) -> FlowStep:
    return _step(
        2,
        output_mode="template_fill",
        output_type="docx",
        output_config={
            "template_asset_id": str(uuid4()),
            "bindings": {"sammanfattning": binding},
        },
    )


def test_publish_fills_a_template_field_from_an_earlier_step_by_its_name() -> None:
    _publish([_step(1), _template_fill("{{ Steg 1 }}")], {})


def test_publish_refuses_a_template_field_read_below_a_step_name() -> None:
    with pytest.raises(FlowStepValidationError) as caught:
        _publish([_step(1), _template_fill("{{ Steg 1.output.text }}")], {})

    assert caught.value.step_order == 2
    assert caught.value.context is not None
    assert caught.value.context["placeholder"] == "sammanfattning"


@pytest.mark.parametrize("mode", [None, "summarize", "process_each_section"])
def test_publish_lets_only_a_sectioned_prompt_read_the_section_index(
    mode: str | None,
) -> None:
    records = {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {"type": "object", "properties": {"t": {"type": "string"}}},
            }
        },
    }
    step = _step(
        1,
        output_type="json",
        output_contract=records,
        # Uploads give the sections their one material.
        input_config=(
            {"text_processing": {"mode": mode}, "runtime_input": {"enabled": True}}
            if mode
            else None
        ),
    )
    prompts = {1: "Avsnitt {{ section_index }}"}

    if mode == "process_each_section":
        _publish([step], prompts)
        return
    with pytest.raises(FlowStepValidationError) as caught:
        _publish([step], prompts)
    assert caught.value.code == (
        FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value
    )
