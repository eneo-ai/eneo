from __future__ import annotations

from uuid import UUID, uuid4

from intric.flows.ai_builder.ai_builder_materializer import compile_changeset
from intric.flows.application.flow_draft_materialization import (
    FlowDraftStepChangeKind,
    compile_flow_draft_changeset,
)
from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


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
        mcp_policy="inherit",
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


def _without_ai_builder_metadata(changeset_dump: dict) -> dict:
    result = dict(changeset_dump)
    result.pop("description_override_manual", None)
    metadata = result.get("metadata_json")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        metadata.pop("ai_builder", None)
        result["metadata_json"] = metadata or None
    return result


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


def test_shared_compile_matches_ai_builder_compile_for_generic_changeset_shape() -> None:
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

    shared = compile_flow_draft_changeset(spec, current_flow=current_flow)
    ai_builder = compile_changeset(spec, current_flow=current_flow)

    assert _without_ai_builder_metadata(
        ai_builder.model_dump(mode="json")
    ) == _without_ai_builder_metadata(shared.model_dump(mode="json"))
    assert shared.compiled_steps[0].change_kind is FlowDraftStepChangeKind.MODIFIED
    assert shared.compiled_steps[1].change_kind is FlowDraftStepChangeKind.ADDED
    assert len(shared.assistants_to_delete) == 1
