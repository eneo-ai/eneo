"""Tests for AI Builder edit-mode validators."""

from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    FormFieldOperation,
    FormFieldSpec,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_models import (
    InputSource,
    InputType,
)
from intric.flows.flow import FlowStep

VALID_REFS = ["existing_step_1", "existing_step_2", "existing_step_3"]


def _existing_step(
    *, step_order: int, output_type: str = "text", output_contract=None
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


def _add_op(
    *,
    position: str = "append",
    anchor_ref: str | None = None,
    name: str = "New Step",
    target_ref: str | None = None,
) -> StepEditOperation:
    return StepEditOperation(
        op="add",
        target_ref=target_ref,
        placement=StepPlacement(position=position, anchor_ref=anchor_ref),
        add_payload=AddStepPayload(
            name=name,
            instructions="Do something.",
            input_source=InputSource.PREVIOUS_STEP,
        ),
    )


def _modify_op(
    target_ref: str,
    *,
    name: str | None = None,
    input_type: InputType | None = None,
) -> StepEditOperation:
    return StepEditOperation(
        op="modify",
        target_ref=target_ref,
        patch=StepPatch(name=name, input_type=input_type),
    )


def _remove_op(target_ref: str) -> StepEditOperation:
    return StepEditOperation(op="remove", target_ref=target_ref)


def _error_codes(result) -> list[str]:
    return [e.code for e in result.errors]


def _warning_codes(result) -> list[str]:
    return [w.code for w in result.warnings]


class TestValidAddOperations:
    def test_add_append_valid(self):
        draft = FlowEditDraft(operations=[_add_op()])
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid

    def test_add_before_valid(self):
        draft = FlowEditDraft(
            operations=[_add_op(position="before", anchor_ref="existing_step_1")]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid

    def test_add_with_target_ref_is_error(self):
        draft = FlowEditDraft(operations=[_add_op(target_ref="existing_step_1")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "add_with_target_ref" in _error_codes(result)

    def test_add_missing_payload_is_error(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(op="add", placement=StepPlacement(position="append"))
            ]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "add_missing_payload" in _error_codes(result)

    def test_add_before_without_anchor_is_error(self):
        draft = FlowEditDraft(operations=[_add_op(position="before")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "placement_missing_anchor" in _error_codes(result)

    def test_add_with_invalid_anchor_is_error(self):
        draft = FlowEditDraft(
            operations=[_add_op(position="after", anchor_ref="existing_step_99")]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "invalid_placement_anchor" in _error_codes(result)

    def test_add_previous_fields_must_reference_earlier_steps_in_resulting_order(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="before", anchor_ref="existing_step_1"
                    ),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}],
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "invalid_previous_field_source" in _error_codes(result)

    def test_add_previous_fields_reject_removed_source_steps(self):
        draft = FlowEditDraft(
            operations=[
                _remove_op("existing_step_1"),
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="after", anchor_ref="existing_step_2"
                    ),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}],
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "removed_previous_field_source" in _error_codes(result)

    def test_add_previous_fields_with_invalid_anchor_does_not_crash(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="after", anchor_ref="existing_step_99"
                    ),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_previous_fields=[{"from_step": 99, "field_path": "risk"}],
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "invalid_placement_anchor" in _error_codes(result)
        assert "invalid_previous_field_source" in _error_codes(result)

    def test_add_previous_fields_accept_valid_json_source(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="after", anchor_ref="existing_step_1"
                    ),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}],
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert result.valid

    def test_add_uses_form_fields_rejects_unknown_form_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_form_fields=["saknas"],
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json={
                "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
            },
        )
        assert not result.valid
        assert "unknown_form_field_reference" in _error_codes(result)

    def test_add_uses_form_fields_accepts_existing_form_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_form_fields=["referensnummer"],
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json={
                "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
            },
        )
        assert result.valid

    def test_add_uses_form_fields_accepts_fields_added_by_form_operations(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=AddStepPayload(
                        name="Nytt steg",
                        instructions="Bygg nytt steg.",
                        input_source=InputSource.PREVIOUS_STEP,
                        uses_form_fields=["uppföljningsperiod"],
                    ),
                )
            ],
            form_operations=[
                FormFieldOperation(
                    op="add",
                    field_name="uppföljningsperiod",
                    field_payload=FormFieldSpec(
                        label="Uppföljningsperiod",
                        field_type="date",
                        required=True,
                    ),
                )
            ],
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json=None,
        )
        assert result.valid


class TestValidModifyOperations:
    def test_modify_valid(self):
        draft = FlowEditDraft(
            operations=[_modify_op("existing_step_1", name="Renamed")]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid

    def test_modify_missing_target_is_error(self):
        draft = FlowEditDraft(
            operations=[StepEditOperation(op="modify", patch=StepPatch(name="X"))]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "modify_missing_target" in _error_codes(result)

    def test_modify_invalid_target_is_error(self):
        draft = FlowEditDraft(operations=[_modify_op("existing_step_99", name="X")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "invalid_target_ref" in _error_codes(result)

    def test_modify_missing_patch_is_error(self):
        draft = FlowEditDraft(
            operations=[StepEditOperation(op="modify", target_ref="existing_step_1")]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "modify_missing_patch" in _error_codes(result)

    def test_modify_file_type_warns(self):
        draft = FlowEditDraft(
            operations=[_modify_op("existing_step_1", input_type=InputType.FILE)]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid  # warning, not error
        assert "type_downgrade_risk" in _warning_codes(result)

    def test_modify_previous_field_reference_requires_earlier_target(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 3, "field_path": "risk"}]
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "invalid_previous_field_source" in _error_codes(result)

    def test_modify_uses_form_fields_rejects_unknown_form_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(uses_form_fields=["saknas"]),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json={
                "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
            },
        )
        assert not result.valid
        assert "unknown_form_field_reference" in _error_codes(result)

    def test_modify_uses_form_fields_accepts_existing_form_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(uses_form_fields=["referensnummer"]),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json={
                "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
            },
        )
        assert result.valid

    def test_modify_uses_form_fields_rejects_fields_removed_in_same_draft(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(uses_form_fields=["referensnummer"]),
                )
            ],
            form_operations=[
                FormFieldOperation(op="remove", field_name="referensnummer"),
            ],
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
            current_metadata_json={
                "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
            },
        )
        assert not result.valid
        assert "unknown_form_field_reference" in _error_codes(result)

    def test_modify_upstream_output_contract_then_reference_new_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_type="json",
                        output_contract={
                            "type": "object",
                            "properties": {"risk": {"type": "string"}},
                        },
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1, output_type="text"),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert result.valid

    def test_modify_upstream_output_contract_ordering_is_honored(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_type="json",
                        output_contract={
                            "type": "object",
                            "properties": {"risk": {"type": "string"}},
                        },
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1, output_type="text"),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "previous_field_source_requires_json_output" in _error_codes(result)

    def test_modify_upstream_output_contract_narrowing_rejects_removed_field(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_contract={
                            "type": "object",
                            "properties": {"summary": {"type": "string"}},
                        },
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "unknown_previous_field_reference" in _error_codes(result)

    def test_add_json_step_can_become_previous_field_source_for_later_modify(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="before", anchor_ref="existing_step_1"
                    ),
                    add_payload=AddStepPayload(
                        name="Extrahera risk",
                        instructions="Extrahera risk.",
                        input_source=InputSource.FLOW_INPUT,
                        input_type="text",
                        output_type="json",
                        output_fields=[
                            {
                                "name": "risk",
                                "field_type": "string",
                                "description": "Risk",
                            }
                        ],
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1, output_type="text"),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert result.valid

    def test_modify_upstream_output_contract_handles_composite_schema(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_type="json",
                        output_contract={
                            "allOf": [
                                {
                                    "type": "object",
                                    "properties": {"summary": {"type": "string"}},
                                },
                                {
                                    "type": "object",
                                    "properties": {"risk": {"type": "string"}},
                                },
                            ]
                        },
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=1, output_type="text"),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert result.valid

    def test_modify_previous_field_resolution_sorts_unsafely_ordered_current_steps(
        self,
    ):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_3",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 2, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(step_order=3),
                _existing_step(
                    step_order=2,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=1),
            ],
        )
        assert result.valid

    def test_modify_previous_field_reference_must_point_to_earlier_step(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 3, "field_path": "risk"}]
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(
                    step_order=3,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
            ],
        )
        assert not result.valid
        assert "invalid_previous_field_source" in _error_codes(result)

    def test_modify_previous_field_reference_rejects_removed_source_steps(self):
        draft = FlowEditDraft(
            operations=[
                _remove_op("existing_step_1"),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_3",
                    patch=StepPatch(
                        uses_previous_fields=[{"from_step": 1, "field_path": "risk"}]
                    ),
                ),
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {"risk": {"type": "string"}},
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "removed_previous_field_source" in _error_codes(result)

    def test_modify_previous_field_reference_requires_numeric_array_index(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[
                            {"from_step": 1, "field_path": "risker.rubrik"}
                        ]
                    ),
                )
            ]
        )
        result = validate_edit_draft(
            draft,
            VALID_REFS,
            current_steps=[
                _existing_step(
                    step_order=1,
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {
                            "risker": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"rubrik": {"type": "string"}},
                                },
                            }
                        },
                    },
                ),
                _existing_step(step_order=2),
                _existing_step(step_order=3),
            ],
        )
        assert not result.valid
        assert "unknown_previous_field_reference" in _error_codes(result)


class TestValidRemoveOperations:
    def test_remove_valid(self):
        draft = FlowEditDraft(operations=[_remove_op("existing_step_2")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid

    def test_remove_missing_target_is_error(self):
        draft = FlowEditDraft(operations=[StepEditOperation(op="remove")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "remove_missing_target" in _error_codes(result)

    def test_remove_invalid_target_is_error(self):
        draft = FlowEditDraft(operations=[_remove_op("existing_step_99")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "invalid_target_ref" in _error_codes(result)


class TestDuplicateTargetRef:
    def test_duplicate_target_ref_is_error(self):
        draft = FlowEditDraft(
            operations=[
                _modify_op("existing_step_1", name="A"),
                _modify_op("existing_step_1", name="B"),
            ]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "duplicate_target_ref" in _error_codes(result)


class TestMixedOperations:
    def test_add_modify_remove_together_valid(self):
        draft = FlowEditDraft(
            operations=[
                _add_op(position="before", anchor_ref="existing_step_1"),
                _modify_op("existing_step_2", name="Updated"),
                _remove_op("existing_step_3"),
            ]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid
        assert len(result.errors) == 0
