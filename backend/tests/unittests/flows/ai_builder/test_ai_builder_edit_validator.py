"""Tests for AI Builder edit-mode validators."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_models import (
    InputSource,
    InputType,
)

VALID_REFS = ["existing_step_1", "existing_step_2", "existing_step_3"]


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
        draft = FlowEditDraft(
            operations=[_add_op(target_ref="existing_step_1")]
        )
        result = validate_edit_draft(draft, VALID_REFS)
        assert not result.valid
        assert "add_with_target_ref" in _error_codes(result)

    def test_add_missing_payload_is_error(self):
        draft = FlowEditDraft(
            operations=[StepEditOperation(op="add", placement=StepPlacement(position="append"))]
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
        draft = FlowEditDraft(
            operations=[_modify_op("existing_step_99", name="X")]
        )
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


class TestValidRemoveOperations:
    def test_remove_valid(self):
        draft = FlowEditDraft(operations=[_remove_op("existing_step_2")])
        result = validate_edit_draft(draft, VALID_REFS)
        assert result.valid

    def test_remove_missing_target_is_error(self):
        draft = FlowEditDraft(
            operations=[StepEditOperation(op="remove")]
        )
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
