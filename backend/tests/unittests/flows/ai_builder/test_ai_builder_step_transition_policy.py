from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)


def _step(
    *,
    ref: str,
    name: str,
    input_source: InputSource,
    input_bindings: dict[str, object] | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=f"Run {name}."),
        input_source=input_source,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=OutputType.TEXT,
        input_bindings=input_bindings,
    )


def test_normalize_ai_builder_spec_rewires_repeated_all_previous_steps() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Linear report",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Analyze",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
            _step(
                ref="step_c",
                name="Summarize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert [step.input_source for step in normalized.steps] == [
        InputSource.FLOW_INPUT,
        InputSource.PREVIOUS_STEP,
        InputSource.ALL_PREVIOUS_STEPS,
    ]
    assert [
        change.code
        for _step_spec, change in changes
        if change.code == "input_source_all_previous_rewired"
    ] == ["input_source_all_previous_rewired"]


def test_normalize_ai_builder_spec_preserves_single_unbound_all_previous_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Final synthesis",
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Synthesize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert not any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_keeps_explicit_multi_step_fan_in() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Explicit synthesis",
        steps=[
            _step(ref="step_a", name="Extract A", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Extract B",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_c",
                name="Compare",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_bindings={
                    "question": ("{{ step_a.output.text }}\n\n{{ step_b.output.text }}")
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[2].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert not any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )


def test_normalize_ai_builder_spec_rewires_previous_only_binding() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Previous only",
        form_fields=[
            FormFieldSpec(
                name="audience",
                type="text",
                label="Audience",
            )
        ],
        steps=[
            _step(ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT),
            _step(
                ref="step_b",
                name="Analyze",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                ref="step_c",
                name="Summarize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_bindings={
                    "question": "{{ step_b.output.text }}\n\naudience: {{ audience }}"
                },
            ),
        ],
    )

    normalized, changes = normalize_ai_builder_spec(spec)

    assert normalized.steps[2].input_source == InputSource.PREVIOUS_STEP
    assert any(
        change.code == "input_source_all_previous_rewired"
        for _step_spec, change in changes
    )
