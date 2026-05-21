from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_normalizer import (
    canonicalize_duplicate_modify_operations,
    normalize_edit_draft_mechanics,
    normalize_loose_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
    OutputType,
)

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


def test_normalize_loose_edit_arguments_removes_nested_binding_noise() -> None:
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

    cleaned = normalize_loose_edit_arguments(arguments)

    assert "uses_previous_fields" not in cleaned["operations"][0]["add_payload"]
    assert "uses_form_fields" not in cleaned["operations"][0]["add_payload"]
    assert cleaned["operations"][1]["patch"]["uses_previous_fields"] == [
        {"from_step": 1, "field_path": "summary"},
    ]
    assert cleaned["operations"][1]["patch"]["uses_form_fields"] == ["case_id"]


def test_normalize_loose_edit_arguments_recovers_malformed_output_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    arguments = {
        "plan_rationale": "Add review step.",
        "operations": [
            {
                "op": "add",
                "placement": {"position": "before", "anchor_ref": "existing_step_3"},
                "add_payload": {
                    "name": "Granska underlag",
                    "instructions": "Kontrollera att varje rubrik har underlag.",
                    "input_source": "previous_step",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "rubriker",
                            "field_type": "array",
                            "description": "Rubriker som ska granskas.",
                            "item_fields": [
                                {
                                    "name": "rubrik",
                                    "field_type": "string",
                                    "description": "Rubriknamn.",
                                },
                                {
                                    "name": "underlag",
                                    "field_type": "object",
                                    "description": "Underlag per rubrik.",
                                },
                            ],
                        },
                        {
                            "name": "granskning",
                            "field_type": "object",
                            "description": "Granskningsresultat.",
                            "fields": [
                                {
                                    "name": "status",
                                    "field_type": "string",
                                    "description": "Granskningsstatus.",
                                },
                                {
                                    "name": "json_underlag",
                                    "field_type": "object",
                                    "description": "JSON-underlag.",
                                },
                            ],
                        },
                    ],
                },
            }
        ],
    }

    with pytest.raises(ValidationError, match="Object fields must declare"):
        FlowEditDraft.model_validate(arguments)

    caplog.set_level(logging.INFO)
    cleaned = normalize_loose_edit_arguments(arguments)
    draft = FlowEditDraft.model_validate(cleaned)

    payload = draft.operations[0].add_payload
    assert payload is not None
    assert payload.output_fields is not None
    rubriker = payload.output_fields[0]
    granskning = payload.output_fields[1]
    assert rubriker.field_type == "array"
    assert rubriker.item_fields is not None
    assert [(field.name, field.field_type) for field in rubriker.item_fields] == [
        ("rubrik", "string"),
        ("underlag", "string"),
    ]
    assert granskning.field_type == "object"
    assert granskning.fields is not None
    assert [(field.name, field.field_type) for field in granskning.fields] == [
        ("status", "string"),
        ("json_underlag", "string"),
    ]
    assert "ai_builder_structured_field_object_downgraded" in caplog.text
    assert "Underlag per rubrik" not in caplog.text
    assert "JSON-underlag" not in caplog.text


def test_normalize_loose_edit_arguments_preserves_valid_output_fields() -> None:
    arguments = {
        "plan_rationale": "Add valid structured step.",
        "operations": [
            {
                "op": "add",
                "placement": {"position": "append"},
                "add_payload": {
                    "name": "Valid",
                    "instructions": "Return valid JSON.",
                    "input_source": "previous_step",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "review",
                            "field_type": "object",
                            "description": "Review.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "status",
                                    "field_type": "string",
                                    "description": "Status.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)

    assert cleaned == arguments
    assert FlowEditDraft.model_validate(cleaned).operations[0].add_payload is not None


def test_normalize_loose_edit_arguments_keeps_modify_patch_output_fields_out_of_scope() -> (
    None
):
    arguments = {
        "plan_rationale": "Modify bindings.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_2",
                "patch": {
                    "uses_previous_fields": [
                        {"from_step": 0, "field_path": "summary"},
                        {"from_step": 1, "field_path": "summary"},
                    ],
                    "output_fields": [
                        {"name": "ignored", "field_type": "object"},
                    ],
                },
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)
    draft = FlowEditDraft.model_validate(cleaned)

    assert cleaned["operations"][0]["patch"]["uses_previous_fields"] == [
        {"from_step": 1, "field_path": "summary"}
    ]
    assert cleaned["operations"][0]["patch"]["output_fields"] == [
        {"name": "ignored", "field_type": "object"}
    ]
    patch = draft.operations[0].patch
    assert patch is not None
    assert [(ref.from_step, ref.field_path) for ref in patch.uses_previous_fields] == [
        (1, "summary")
    ]
    assert not hasattr(patch, "output_fields")


def test_normalize_loose_edit_arguments_logs_when_output_fields_are_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    arguments = {
        "plan_rationale": "Add malformed field list.",
        "operations": [
            {
                "op": "add",
                "placement": {"position": "append"},
                "add_payload": {
                    "name": "Malformed",
                    "instructions": "Return JSON.",
                    "input_source": "previous_step",
                    "output_type": "json",
                    "output_fields": [None, 3],
                },
            }
        ],
    }

    caplog.set_level(logging.INFO)
    cleaned = normalize_loose_edit_arguments(arguments)

    assert "output_fields" not in cleaned["operations"][0]["add_payload"]
    assert "ai_builder_structured_field_list_dropped" in caplog.text


def test_normalize_loose_edit_arguments_recovers_live_patch_output_mode_aliases() -> (
    None
):
    arguments = {
        "plan_rationale": "Improve review and final document steps.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_4",
                "patch": {"output_mode": "view"},
            },
            {
                "op": "modify",
                "target_ref": "existing_step_7",
                "patch": {"output_mode": "generated", "output_type": "docx"},
            },
        ],
    }

    with pytest.raises(ValidationError, match="output_mode"):
        FlowEditDraft.model_validate(arguments)

    cleaned = normalize_loose_edit_arguments(arguments)
    draft = FlowEditDraft.model_validate(cleaned)

    review_patch = draft.operations[0].patch
    document_patch = draft.operations[1].patch
    assert review_patch is not None
    assert document_patch is not None
    assert review_patch.output_mode is None
    assert review_patch.review_mode == "view"
    assert document_patch.output_mode is None
    assert document_patch.document_delivery_mode == "generated"
    assert document_patch.output_type == OutputType.DOCX


def test_normalize_loose_edit_arguments_keeps_existing_review_mode_on_alias_conflict() -> (
    None
):
    arguments = {
        "plan_rationale": "Keep explicit review mode.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_2",
                "patch": {"output_mode": "view", "review_mode": "edit"},
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)
    draft = FlowEditDraft.model_validate(cleaned)

    patch = draft.operations[0].patch
    assert patch is not None
    assert patch.output_mode is None
    assert patch.review_mode == "edit"


def test_normalize_loose_edit_arguments_preserves_unknown_output_mode_alias() -> None:
    arguments = {
        "plan_rationale": "Unknown alias should still fail strict validation.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_2",
                "patch": {"output_mode": "totally_made_up"},
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)

    assert cleaned == arguments
    with pytest.raises(ValidationError, match="totally_made_up"):
        FlowEditDraft.model_validate(cleaned)


def test_normalize_loose_edit_arguments_does_not_rewrite_add_payload_output_mode() -> (
    None
):
    arguments = {
        "plan_rationale": "Add payload must stay on the new-step contract.",
        "operations": [
            {
                "op": "add",
                "placement": {"position": "append"},
                "add_payload": {
                    "name": "Skapa rapport",
                    "instructions": "Skapa en rapport.",
                    "input_source": "previous_step",
                    "output_type": "docx",
                    "output_mode": "generated",
                },
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)

    assert cleaned["operations"][0]["add_payload"]["output_mode"] == "generated"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FlowEditDraft.model_validate(cleaned)


def test_normalize_loose_edit_arguments_combines_patch_alias_and_ref_cleanup() -> None:
    arguments = {
        "plan_rationale": "Update review and context.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_3",
                "patch": {
                    "output_mode": "view",
                    "uses_previous_fields": [
                        {"from_step": 0, "field_path": "summary"},
                        {"from_step": 2, "field_path": "summary"},
                    ],
                },
            }
        ],
    }

    cleaned = normalize_loose_edit_arguments(arguments)
    draft = FlowEditDraft.model_validate(cleaned)

    patch = draft.operations[0].patch
    assert patch is not None
    assert patch.review_mode == "view"
    assert patch.output_mode is None
    assert patch.uses_previous_fields is not None
    assert [(ref.from_step, ref.field_path) for ref in patch.uses_previous_fields] == [
        (2, "summary")
    ]


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


def test_canonicalize_duplicate_modify_operations_merges_disjoint_patch_fields() -> (
    None
):
    draft = FlowEditDraft(
        plan_rationale="Update final report step.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Skapa DOCX-rapport"),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(output_type=OutputType.DOCX),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    operation = result.draft.operations[0]
    assert operation.patch is not None
    assert operation.patch.name == "Skapa DOCX-rapport"
    assert operation.patch.output_type == OutputType.DOCX
    assert validate_edit_draft(result.draft, ["existing_step_2"]).valid


def test_canonicalize_duplicate_modify_operations_merges_three_disjoint_patches() -> (
    None
):
    draft = FlowEditDraft(
        plan_rationale="Update the same step across several compatible patches.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Reviewed output"),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(output_type=OutputType.JSON),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(review_mode="edit"),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    patch = result.draft.operations[0].patch
    assert patch is not None
    assert patch.name == "Reviewed output"
    assert patch.output_type == OutputType.JSON
    assert patch.review_mode == "edit"


def test_canonicalize_duplicate_modify_operations_unions_underlag_refs() -> None:
    draft = FlowEditDraft(
        plan_rationale="Use reviewed JSON and text.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_3",
                patch=StepPatch(
                    uses_previous_fields=[
                        {"from_step": 1, "field_path": "meeting_context"}
                    ],
                    uses_form_fields=["report_title"],
                ),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_3",
                patch=StepPatch(
                    uses_previous_fields=[
                        {"from_step": 2, "field_path": "reviewed_facts"},
                        {"from_step": 1, "field_path": "meeting_context"},
                    ],
                    uses_form_fields=["report_language", "report_title"],
                ),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    patch = result.draft.operations[0].patch
    assert patch is not None
    assert [(ref.from_step, ref.field_path) for ref in patch.uses_previous_fields] == [
        (1, "meeting_context"),
        (2, "reviewed_facts"),
    ]
    assert patch.uses_form_fields == ["report_title", "report_language"]


def test_canonicalize_duplicate_modify_operations_accepts_equal_assistant_spec() -> (
    None
):
    assistant_spec = AssistantSpec(
        instructions="Write a concise report.",
        model_ref="main",
    )
    draft = FlowEditDraft(
        plan_rationale="Duplicate equal assistant spec is harmless.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(assistant_spec=assistant_spec),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(assistant_spec=assistant_spec),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    patch = result.draft.operations[0].patch
    assert patch is not None
    assert patch.assistant_spec == assistant_spec


def test_canonicalize_duplicate_modify_operations_reports_assistant_spec_conflict() -> (
    None
):
    draft = FlowEditDraft(
        plan_rationale="Assistant spec conflicts stay compiler-owned.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(instructions="Write a report.")
                ),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(
                        instructions="Write a report with citations."
                    )
                ),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.draft == draft
    assert [
        (conflict.target_ref, conflict.field_name) for conflict in result.conflicts
    ] == [("existing_step_2", "assistant_spec")]


def test_canonicalize_duplicate_modify_operations_preserves_add_order() -> None:
    draft = FlowEditDraft(
        plan_rationale="Patch, add, then patch same step.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(output_type=OutputType.JSON),
            ),
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="after", anchor_ref="existing_step_2"),
                add_payload=AddStepPayload(
                    name="Use structured result",
                    instructions="Use the reviewed structured output.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.TEXT,
                ),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Reviewed facts"),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert [operation.op for operation in result.draft.operations] == ["modify", "add"]
    first_patch = result.draft.operations[0].patch
    assert first_patch is not None
    assert first_patch.output_type == OutputType.JSON
    assert first_patch.name == "Reviewed facts"


def test_canonicalize_duplicate_modify_operations_reports_scalar_conflict() -> None:
    draft = FlowEditDraft(
        plan_rationale="Conflicting names.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Rapport"),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Slutdokument"),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.draft == draft
    assert [
        (conflict.target_ref, conflict.field_name) for conflict in result.conflicts
    ] == [("existing_step_2", "name")]


def test_canonicalize_duplicate_modify_operations_treats_explicit_clear_as_conflict() -> (
    None
):
    draft = FlowEditDraft(
        plan_rationale="Clear conflicts with set.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(output_config={"format": "docx"}),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(output_config=None),
            ),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.draft == draft
    assert [
        (conflict.target_ref, conflict.field_name) for conflict in result.conflicts
    ] == [("existing_step_2", "output_config")]


def test_canonicalize_duplicate_modify_operations_drops_patch_for_removed_step() -> (
    None
):
    draft = FlowEditDraft(
        plan_rationale="Remove and modify same step.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_2",
                patch=StepPatch(name="Updated"),
            ),
            StepEditOperation(op="remove", target_ref="existing_step_2"),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    assert result.draft.operations[0].op == "remove"
    assert result.draft.operations[0].target_ref == "existing_step_2"
    validation = validate_edit_draft(result.draft, ["existing_step_2"])
    assert validation.valid


def test_canonicalize_duplicate_modify_operations_drops_duplicate_remove() -> None:
    draft = FlowEditDraft(
        plan_rationale="Remove the same step once.",
        operations=[
            StepEditOperation(op="remove", target_ref="existing_step_2"),
            StepEditOperation(op="remove", target_ref="existing_step_2"),
        ],
    )

    result = canonicalize_duplicate_modify_operations(draft)

    assert result.conflicts == ()
    assert len(result.draft.operations) == 1
    assert result.draft.operations[0].op == "remove"
    validation = validate_edit_draft(result.draft, ["existing_step_2"])
    assert validation.valid
