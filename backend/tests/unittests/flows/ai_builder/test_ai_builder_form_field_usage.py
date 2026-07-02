from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_form_field_usage import (
    find_unused_form_fields,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    StepSpec,
)


def _field(name: str) -> FormFieldSpec:
    return FormFieldSpec(name=name, type="text", label=name)


def _step(
    instructions: str,
    *,
    input_bindings: dict[str, object] | None = None,
    output_config: dict[str, object] | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Skriv svar",
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=InputSource.FLOW_INPUT,
        input_bindings=input_bindings,
        output_config=output_config,
    )


@pytest.mark.parametrize(
    ("form_fields", "step", "expected"),
    [
        ([], _step("Skriv svar."), []),
        ([_field("audience")], _step("Skriv för {{ audience }}."), []),
        ([_field("audience")], _step("Skriv för {{ flow_input.audience }}."), []),
        (
            [_field("audience")],
            _step("Skriv svar.", input_bindings={"question": "{{ audience }}"}),
            [],
        ),
        (
            [_field("audience")],
            _step(
                "Skriv svar.", input_bindings={"question": "{{ form_fields.audience }}"}
            ),
            ["audience"],
        ),
        (
            [_field("doc_id")],
            _step("Skriv svar.", output_config={"filename": "{{ doc_id }}.docx"}),
            [],
        ),
        ([_field("priority")], _step("Skriv svar."), ["priority"]),
        (
            [_field("z_field"), _field("used"), _field("a_field"), _field("   ")],
            _step("Skriv för {{ used }}."),
            ["a_field", "z_field"],
        ),
    ],
)
def test_find_unused_form_fields(
    form_fields: list[FormFieldSpec],
    step: StepSpec,
    expected: list[str],
) -> None:
    spec = FlowDraftSpecCore(
        flow_name="Form field usage",
        form_fields=form_fields,
        steps=[step],
    )

    assert find_unused_form_fields(spec) == expected


def test_find_unused_form_fields_scans_all_steps() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Multi-step form field usage",
        form_fields=[_field("audience"), _field("doc_id"), _field("priority")],
        steps=[
            _step("Klassificera för {{ audience }}."),
            _step("Skriv svar.", input_bindings={"question": "{{ doc_id }}"}),
        ],
    )

    assert find_unused_form_fields(spec) == ["priority"]
