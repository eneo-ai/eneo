from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_edit_mechanics import fill_edit_draft_mechanics
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_models import InputSource, InputType
from intric.flows.domain.flow import FlowStep


def _existing_step(*, step_order: int, input_source: str = "flow_input") -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        mcp_policy="inherit",
    )


def test_fill_edit_draft_mechanics_defaults_first_file_flow_input() -> None:
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(
                    position="before", anchor_ref="existing_step_1"
                ),
                add_payload=AddStepPayload(
                    name="Transkribera ljud",
                    instructions="Transkribera ljudfilen.",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                ),
            )
        ]
    )

    filled = fill_edit_draft_mechanics(
        draft,
        current_steps=[_existing_step(step_order=1, input_source="previous_step")],
    )

    add_payload = filled.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.runtime_upload is True
    assert add_payload.runtime_required is True


def test_fill_edit_draft_mechanics_repairs_invalid_first_audio_step_mechanics() -> None:
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="append"),
                add_payload=AddStepPayload(
                    name="Transkribera ljud",
                    instructions="Transkribera ljudfilen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.AUDIO,
                    runtime_upload=False,
                ),
            )
        ]
    )

    filled = fill_edit_draft_mechanics(draft, current_steps=[])

    add_payload = filled.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.input_source == InputSource.FLOW_INPUT
    assert add_payload.runtime_upload is True
    assert add_payload.runtime_required is True


def test_flow_edit_draft_accepts_null_resource_ref_lists_as_empty_lists() -> None:
    draft = FlowEditDraft.model_validate(
        {
            "operations": [
                {
                    "op": "add",
                    "placement": {"position": "append"},
                    "add_payload": {
                        "name": "Transkribera ljud",
                        "instructions": "Transkribera ljudfilen.",
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "knowledge_refs": None,
                        "mcp_server_refs": None,
                        "mcp_tool_refs": None,
                    },
                }
            ]
        }
    )

    add_payload = draft.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.knowledge_refs == []
    assert add_payload.mcp_server_refs == []
    assert add_payload.mcp_tool_refs == []


def test_fill_edit_draft_mechanics_preserves_explicit_runtime_choices() -> None:
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(
                    position="before", anchor_ref="existing_step_1"
                ),
                add_payload=AddStepPayload(
                    name="Ladda upp dokument",
                    instructions="Läs dokumentet.",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.DOCUMENT,
                    runtime_upload=True,
                    runtime_required=False,
                    runtime_max_files=3,
                ),
            )
        ]
    )

    filled = fill_edit_draft_mechanics(
        draft,
        current_steps=[_existing_step(step_order=1, input_source="previous_step")],
    )

    add_payload = filled.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.runtime_upload is True
    assert add_payload.runtime_required is False
    assert add_payload.runtime_max_files == 3


def test_fill_edit_draft_mechanics_does_not_default_non_first_file_step() -> None:
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="append"),
                add_payload=AddStepPayload(
                    name="Extra ljudsteg",
                    instructions="Bearbeta ljud.",
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                ),
            )
        ]
    )

    filled = fill_edit_draft_mechanics(
        draft,
        current_steps=[_existing_step(step_order=1), _existing_step(step_order=2)],
    )

    add_payload = filled.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.runtime_upload is False
    assert add_payload.runtime_required is False
