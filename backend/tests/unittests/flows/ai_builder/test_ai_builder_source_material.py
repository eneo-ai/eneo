from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_source_material import (
    CompiledSourceMaterialBoundary,
    SourceMaterialBindingStatus,
    iter_compiled_source_material_boundaries,
    source_material_binding_status,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _step(
    *,
    ref: str,
    name: str,
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
    input_bindings: dict[str, object] | None = None,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=f"Run {name}."),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
    )


def _source_material_boundary(
    question: str | None,
) -> CompiledSourceMaterialBoundary:
    spec = FlowDraftSpecCore(
        flow_name="Contract report",
        steps=[
            _step(
                ref="step_a",
                name="Transcribe contract call",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            _step(
                ref="step_b",
                name="Extract contract facts",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_c",
                name="Extract delivery risks",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
            _step(
                ref="step_d",
                name="Write contract memo",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                input_bindings=(
                    {"question": question} if question is not None else None
                ),
            ),
        ],
    )
    return list(iter_compiled_source_material_boundaries(spec))[-1]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (None, SourceMaterialBindingStatus.NEEDS_COMPLETION),
        (
            "{{ step_c.output.structured.risk_summary }}",
            SourceMaterialBindingStatus.NEEDS_COMPLETION,
        ),
        (
            "Source material: {{ step_a.output.text }}",
            SourceMaterialBindingStatus.INTENTIONAL_PARTIAL,
        ),
        (
            "{{ step_c.output.structured }}\n\n"
            "Source material: {{ step_a.output.text }}",
            SourceMaterialBindingStatus.COMPLETE,
        ),
    ],
)
def test_source_material_binding_status_classifies_boundary_prompts(
    question: str | None,
    expected: SourceMaterialBindingStatus,
) -> None:
    boundary = _source_material_boundary(question)

    assert source_material_binding_status(boundary) is expected
