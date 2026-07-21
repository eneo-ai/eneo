from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_draft_materialization import (
    FlowDraftStepChangeKind,
    compile_flow_draft_changeset,
)
from eneo.flows.domain.flow import Flow, FlowStep
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


def _flow_step(
    *,
    step_order: int,
    assistant_id: UUID | None = None,
    output_mode: str = "pass_through",
    output_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id or uuid4(),
        step_order=step_order,
        user_description=f"Existing {step_order}",
        input_source="flow_input",
        input_type="text",
        output_mode=output_mode,
        output_type="text",
        output_config=output_config,
    )


def _flow(*steps: FlowStep, metadata_json: dict | None = None) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        description="Existing description",
        steps=list(steps),
        metadata_json=metadata_json,
    )


def test_shared_compile_does_not_stamp_ai_builder_metadata() -> None:
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
        spec,
        current_flow=None,
        default_transcription_model_id=uuid4(),
    )

    assert changeset.metadata_json is not None
    assert changeset.metadata_json["form_schema"]["fields"][0]["name"] == "case_id"
    assert changeset.metadata_json["wizard"]["transcription_enabled"] is True
    assert "ai_builder" not in changeset.metadata_json


def test_shared_compile_distinguishes_absent_and_empty_form_fields() -> None:
    existing_form_schema = {
        "fields": [
            {
                "name": "case_id",
                "type": "text",
                "label": "Case id",
                "required": True,
            }
        ]
    }
    current_flow = _flow(metadata_json={"form_schema": existing_form_schema})

    absent_fields = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Updated flow", steps=[], form_fields=None),
        current_flow=current_flow,
    )
    empty_fields = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Updated flow", steps=[], form_fields=[]),
        current_flow=current_flow,
    )

    assert absent_fields.metadata_json is not None
    assert absent_fields.metadata_json["form_schema"] == existing_form_schema
    assert empty_fields.metadata_json is not None
    assert empty_fields.metadata_json["form_schema"] == {"fields": []}


def test_shared_compile_preserves_output_config_when_output_mode_is_unchanged() -> None:
    existing_config = {"template_asset_id": "template-a"}
    existing_step = _flow_step(
        step_order=1,
        output_mode="pass_through",
        output_config=existing_config,
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(
                existing_step_ref="existing_step_1",
                output_mode=OutputMode.PASS_THROUGH,
                output_config=None,
            )
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=_flow(existing_step))

    assert changeset.compiled_steps[0].output_config == existing_config


def test_shared_compile_drops_output_config_when_output_mode_changes() -> None:
    existing_step = _flow_step(
        step_order=1,
        output_mode="pass_through",
        output_config={"template_asset_id": "template-a"},
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(
                existing_step_ref="existing_step_1",
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
                output_config=None,
            )
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=_flow(existing_step))

    assert changeset.compiled_steps[0].output_config is None


def test_shared_compile_preserves_every_existing_step_without_removals() -> None:
    current_flow = _flow(_flow_step(step_order=1), _flow_step(step_order=2))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_2"),
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert len(changeset.assistants_to_delete) == 0
    assert [step.change_kind for step in changeset.compiled_steps] == [
        FlowDraftStepChangeKind.MODIFIED,
        FlowDraftStepChangeKind.MODIFIED,
    ]


def test_shared_compile_deletes_only_explicit_removed_existing_step() -> None:
    removed_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2, assistant_id=removed_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=current_flow,
        removed_existing_step_refs=frozenset({"existing_step_2"}),
    )

    assert len(changeset.assistants_to_delete) == 1
    assert changeset.assistants_to_delete[0].assistant_id == removed_assistant_id


def test_shared_compile_rejects_omitted_existing_step_without_explicit_removal() -> (
    None
):
    current_flow = _flow(_flow_step(step_order=1), _flow_step(step_order=2))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "missing_existing_step_ref",
        "missing_refs": ["existing_step_2"],
    }


def test_shared_compile_rejects_unknown_removed_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_99"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "unknown_removed_existing_step_ref",
        "unknown_refs": ["existing_step_99"],
    }


def test_shared_compile_rejects_unknown_preserved_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_99"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "unknown_existing_step_ref",
        "unknown_refs": ["existing_step_99"],
        "valid_refs": ["existing_step_1"],
    }


def test_shared_compile_rejects_preserved_and_removed_existing_ref_overlap() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "preserved_and_removed_existing_step_ref",
        "overlap_refs": ["existing_step_1"],
    }


def test_shared_compile_rejects_duplicate_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "duplicate_existing_step_ref",
        "duplicate_refs": ["existing_step_1"],
    }


def test_shared_compile_reorder_preserves_existing_step_identity() -> None:
    first_assistant_id = uuid4()
    second_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(step_order=1, assistant_id=first_assistant_id),
        _flow_step(step_order=2, assistant_id=second_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_2"),
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert [step.assistant_id for step in changeset.compiled_steps] == [
        second_assistant_id,
        first_assistant_id,
    ]
    assert len(changeset.assistants_to_delete) == 0


def test_shared_compile_rejects_create_spec_with_existing_step_ref() -> None:
    spec = FlowDraftSpecCore(
        flow_name="New flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=None)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "create_cannot_use_existing_step_ref",
        "existing_step_ref": "existing_step_1",
    }


def test_shared_compile_rejects_create_with_removed_existing_step_refs() -> None:
    spec = FlowDraftSpecCore(
        flow_name="New flow",
        steps=[_step_spec(plan_step_ref="step_a")],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=None,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "create_cannot_remove_existing_step_refs",
        "removed_refs": ["existing_step_1"],
    }


def test_shared_compile_compiles_generic_edit_changeset_shape() -> None:
    existing_assistant_id = uuid4()
    removed_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(
            step_order=1,
            assistant_id=existing_assistant_id,
            output_config={"template_asset_id": "template-a"},
        ),
        _flow_step(step_order=2, assistant_id=removed_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        flow_description="Updated description",
        form_fields=[FormFieldSpec(name="case_id", type="text", label="Case id")],
        steps=[
            _step_spec(
                plan_step_ref="collect",
                existing_step_ref="existing_step_1",
                name="Collect",
                input_bindings={"question": "Use {{ collect.output.text }}"},
            ),
            _step_spec(
                plan_step_ref="summarize",
                name="Summarize",
                instructions="Summarize {{ collect.output.text }}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    removed_refs = frozenset({"existing_step_2"})
    shared = compile_flow_draft_changeset(
        spec,
        current_flow=current_flow,
        removed_existing_step_refs=removed_refs,
    )
    assert shared.metadata_json is not None
    assert shared.metadata_json["form_schema"]["fields"][0]["name"] == "case_id"
    assert shared.compiled_steps[0].change_kind is FlowDraftStepChangeKind.MODIFIED
    assert shared.compiled_steps[1].change_kind is FlowDraftStepChangeKind.ADDED
    assert len(shared.assistants_to_delete) == 1


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

    shared = compile_flow_draft_changeset(spec, current_flow=None)

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

    shared = compile_flow_draft_changeset(spec, current_flow=None)

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

    assert compile_flow_draft_changeset(
        with_refs,
        current_flow=None,
    ) == compile_flow_draft_changeset(base, current_flow=None)
