from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_normalizer import (
    normalize_edit_draft_mechanics,
    strip_malformed_edit_mechanics,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_models import InputSource, OutputType
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.flow import FlowStep

VALID_REFS = ["existing_step_1", "existing_step_2", "existing_step_3"]


def _existing_step(
    *,
    step_order: int,
    output_type: str = "text",
    output_contract: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type=output_type,
        output_contract=output_contract,
        mcp_policy="inherit",
    )


def _field(name: str) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type="string",
        description=f"{name} field.",
    )


def _json_contract(*field_names: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in field_names},
    }


def test_strip_malformed_edit_mechanics_removes_nested_binding_noise() -> None:
    arguments = {
        "plan_rationale": "Update wiring.",
        "operations": [
            {
                "op": "add",
                "placement": {"position": "append"},
                "add_payload": {
                    "name": "New",
                    "instructions": "Do work.",
                    "input_source": "previous_step",
                    "uses_previous_fields": "summary",
                    "uses_form_fields": "case_id",
                },
            },
            {
                "op": "modify",
                "target_ref": "existing_step_2",
                "patch": {
                    "uses_previous_fields": [
                        {"from_step": 0, "field_path": "summary"},
                        {"from_step": 1, "field_path": "summary"},
                        {"from_step": 1, "field_path": "summary"},
                    ],
                    "uses_form_fields": ["case_id", "", "case_id", {"bad": True}],
                },
            },
        ],
    }

    cleaned = strip_malformed_edit_mechanics(arguments)

    assert "uses_previous_fields" not in cleaned["operations"][0]["add_payload"]
    assert "uses_form_fields" not in cleaned["operations"][0]["add_payload"]
    assert cleaned["operations"][1]["patch"]["uses_previous_fields"] == [
        {"from_step": 1, "field_path": "summary"},
    ]
    assert cleaned["operations"][1]["patch"]["uses_form_fields"] == ["case_id"]


def test_normalize_edit_draft_mechanics_prunes_invalid_nested_refs() -> None:
    current_steps = [
        _existing_step(
            step_order=1,
            output_type="json",
            output_contract=_json_contract("summary"),
        ),
        _existing_step(step_order=2),
        _existing_step(step_order=3),
    ]
    draft = FlowEditDraft(
        plan_rationale="Add and update low-level bindings.",
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="after", anchor_ref="existing_step_2"),
                add_payload=AddStepPayload(
                    name="Added step",
                    instructions="Use available context.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.TEXT,
                    uses_previous_fields=[
                        {"from_step": 1, "field_path": "summary"},
                        {"from_step": 1, "field_path": "invented"},
                        {"from_step": 2, "field_path": "summary"},
                        {"from_step": 3, "field_path": "summary"},
                    ],
                    uses_form_fields=["case_id", "invented_field"],
                ),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_3",
                patch=StepPatch(
                    uses_previous_fields=[
                        {"from_step": 1, "field_path": "summary"},
                        {"from_step": 2, "field_path": "summary"},
                        {"from_step": 3, "field_path": "summary"},
                    ],
                    uses_form_fields=["case_id", "invented_field"],
                ),
            ),
        ],
    )

    assert not validate_edit_draft(
        draft,
        VALID_REFS,
        current_steps=current_steps,
        current_metadata_json={
            "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
        },
    ).valid

    normalized = normalize_edit_draft_mechanics(
        draft,
        current_steps=current_steps,
        current_metadata_json={
            "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
        },
    )

    add_payload = normalized.operations[0].add_payload
    patch = normalized.operations[1].patch
    assert add_payload is not None
    assert patch is not None
    assert [
        (ref.from_step, ref.field_path) for ref in add_payload.uses_previous_fields
    ] == [
        (1, "summary"),
    ]
    assert add_payload.uses_form_fields == ["case_id"]
    assert [
        (ref.from_step, ref.field_path) for ref in patch.uses_previous_fields or []
    ] == [
        (1, "summary"),
    ]
    assert patch.uses_form_fields == ["case_id"]
    assert validate_edit_draft(
        normalized,
        VALID_REFS,
        current_steps=current_steps,
        current_metadata_json={
            "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
        },
    ).valid


def test_normalize_edit_draft_mechanics_honors_operation_order() -> None:
    current_steps = [
        _existing_step(step_order=1),
        _existing_step(step_order=2),
        _existing_step(step_order=3),
    ]
    draft = FlowEditDraft(
        plan_rationale="Add structured extraction before existing analysis.",
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(
                    position="before", anchor_ref="existing_step_1"
                ),
                add_payload=AddStepPayload(
                    name="Extract",
                    instructions="Extract structured fields.",
                    input_source=InputSource.FLOW_INPUT,
                    output_type=OutputType.JSON,
                    output_fields=[_field("summary")],
                ),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(
                    uses_previous_fields=[
                        {"from_step": 1, "field_path": "summary"},
                        {"from_step": 2, "field_path": "summary"},
                    ],
                ),
            ),
        ],
    )

    normalized = normalize_edit_draft_mechanics(
        draft,
        current_steps=current_steps,
        current_metadata_json=None,
    )

    patch = normalized.operations[1].patch
    assert patch is not None
    assert [
        (ref.from_step, ref.field_path) for ref in patch.uses_previous_fields or []
    ] == [
        (1, "summary"),
    ]
    assert validate_edit_draft(
        normalized,
        VALID_REFS,
        current_steps=current_steps,
    ).valid


def test_normalize_edit_draft_mechanics_does_not_clear_existing_bindings_on_noise() -> (
    None
):
    current_steps = [
        _existing_step(step_order=1, output_type="text"),
        _existing_step(step_order=2),
    ]
    draft = FlowEditDraft(
        plan_rationale="Malformed binding hints should become no-op.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(
                    uses_previous_fields=[
                        {"from_step": 1, "field_path": "invented"},
                    ],
                    uses_form_fields=["unknown_form"],
                ),
            ),
        ],
    )

    normalized = normalize_edit_draft_mechanics(
        draft,
        current_steps=current_steps,
        current_metadata_json=None,
    )

    patch = normalized.operations[0].patch
    assert patch is not None
    assert "uses_previous_fields" not in patch.model_fields_set
    assert "uses_form_fields" not in patch.model_fields_set
    assert validate_edit_draft(
        normalized,
        ["existing_step_1", "existing_step_2"],
        current_steps=current_steps,
    ).valid
