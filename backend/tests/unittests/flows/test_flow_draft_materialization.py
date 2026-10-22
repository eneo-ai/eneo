"""Compiling an authoring spec into a new draft: one assistant per step, the
steps reading each other by their runtime aliases."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.application.flow_authoring_refusal import FlowAuthoringRefusalCode
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.main.exceptions import BadRequestException


def _step_spec(
    *,
    plan_step_ref: str = "step_a",
    existing_step_ref: str | None = None,
    name: str = "Draft step",
    instructions: str = "Use {{ step_a.output.text }}.",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    input_bindings: dict | None = None,
    output_config: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
        output_config=output_config,
    )


def test_compile_writes_the_form_and_turns_transcription_on() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Audio flow",
        flow_description="Transcribes audio",
        form_fields=[
            FormFieldSpec(
                name="case_id",
                type="text",
                label="Case id",
                required=True,
            )
        ],
        steps=[
            _step_spec(
                input_type=InputType.AUDIO,
                instructions="Transcribe this.",
            )
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec, default_transcription_model_id=uuid4()
    )

    assert changeset.metadata_json is not None
    assert changeset.metadata_json["form_schema"]["fields"][0]["name"] == "case_id"
    assert changeset.metadata_json["wizard"]["transcription_enabled"] is True
    assert "ai_builder" not in changeset.metadata_json


def test_shared_compile_rejects_create_spec_with_existing_step_ref() -> None:
    spec = FlowDraftSpecCore(
        flow_name="New flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec)

    assert exc_info.value.code is FlowAuthoringRefusalCode.INVALID_EXISTING_STEP_REF
    assert exc_info.value.context == {
        "reason": "create_cannot_use_existing_step_ref",
        "existing_step_ref": "existing_step_1",
    }


def test_shared_compile_preserves_source_refs_with_runtime_step_refs() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Source material flow",
        steps=[
            _step_spec(plan_step_ref="step_a", name="Collect"),
            _step_spec(
                plan_step_ref="step_b",
                name="Summarize",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={
                    "question": "Write the final memo.",
                    "source_refs": [
                        {
                            "step_ref": "step_a",
                            "output": "text",
                            "label": "Transcript",
                        },
                        {
                            "step_ref": "step_a",
                            "output": "structured",
                            "field_path": "decisions",
                            "label": "Decisions",
                        },
                    ],
                },
            ),
        ],
    )

    shared = compile_flow_draft_changeset(spec)

    assert shared.compiled_steps[1].input_bindings == {
        "question": "Write the final memo.",
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "text",
                "label": "Transcript",
            },
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "decisions",
                "label": "Decisions",
            },
        ],
    }


def test_shared_compile_leaves_unmapped_source_ref_unchanged() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Source material flow",
        steps=[
            _step_spec(
                plan_step_ref="step_b",
                name="Summarize",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={
                    "source_refs": [{"step_ref": "existing_step_1", "output": "text"}],
                },
            ),
        ],
    )

    shared = compile_flow_draft_changeset(spec)

    assert shared.compiled_steps[0].input_bindings == {
        "source_refs": [{"step_ref": "existing_step_1", "output": "text"}]
    }


def test_shared_compile_ignores_document_body_writer_refs() -> None:
    steps = [
        _step_spec(plan_step_ref="step_a"),
        _step_spec(plan_step_ref="step_b", input_source=InputSource.PREVIOUS_STEP),
    ]
    base = FlowDraftSpecCore(flow_name="Updated flow", steps=steps)
    with_refs = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=steps,
        document_body_writer_step_refs=("step_b",),
    )

    assert compile_flow_draft_changeset(with_refs) == compile_flow_draft_changeset(base)


@pytest.mark.parametrize(
    "input_config",
    [None, {"runtime_input": False}, {"runtime_input": {"enabled": False}}],
)
def test_shared_compile_preserves_authored_disabled_upload(
    input_config: dict | None,
) -> None:
    step = _step_spec(input_type=InputType.DOCUMENT).model_copy(
        update={"input_config": input_config}
    )
    changeset = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Authored flow", steps=[step])
    )

    assert changeset.compiled_steps[0].input_config == input_config
