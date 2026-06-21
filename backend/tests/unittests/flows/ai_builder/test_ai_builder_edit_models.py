"""Tests for AI Builder edit-mode domain models."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    FormFieldOperation,
    FormFieldSpec,
    StepEditOperation,
    StepPatch,
    StepPlacement,
    validate_step_operation_shape,
)
from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    FlowEditDiff,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
)


def _make_add_payload(
    *,
    name: str,
    instructions: str,
    input_source: InputSource = InputSource.PREVIOUS_STEP,
    input_type: InputType = InputType.TEXT,
) -> NewStepDraft:
    return NewStepDraft(
        name=name,
        instructions=instructions,
        input_source=input_source,
        input_type=input_type,
    )


class TestStepEditOperation:
    def test_add_operation(self):
        op = StepEditOperation(
            op="add",
            placement=StepPlacement(position="before", anchor_ref="existing_step_1"),
            add_payload=_make_add_payload(
                name="Transcription",
                instructions="Transcribe audio.",
                input_source=InputSource.FLOW_INPUT,
            ),
        )
        assert op.op == "add"
        assert op.target_ref is None
        assert op.placement is not None
        assert op.placement.anchor_ref == "existing_step_1"
        assert op.add_payload is not None
        assert op.add_payload.name == "Transcription"

    def test_modify_operation(self):
        op = StepEditOperation(
            op="modify",
            target_ref="existing_step_2",
            patch=StepPatch(
                name="Updated Analysis",
                assistant_spec=AssistantSpec(instructions="New instructions."),
            ),
        )
        assert op.op == "modify"
        assert op.target_ref == "existing_step_2"
        assert op.patch is not None
        assert op.patch.name == "Updated Analysis"

    def test_remove_operation(self):
        op = StepEditOperation(
            op="remove",
            target_ref="existing_step_3",
        )
        assert op.op == "remove"
        assert op.target_ref == "existing_step_3"


class TestStepEditOperationShape:
    def test_reports_add_with_target_ref(self):
        issues = validate_step_operation_shape(
            StepEditOperation(
                op="add",
                target_ref="existing_step_1",
                placement=StepPlacement(position="append"),
                add_payload=_make_add_payload(
                    name="Summary", instructions="Summarize."
                ),
            ),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "add_with_target_ref",
                (
                    "operations[0]: 'add' operations must NOT have target_ref. "
                    "To modify an existing step, use op='modify' instead."
                ),
                None,
            )
        ]

    def test_reports_add_missing_payload(self):
        issues = validate_step_operation_shape(
            StepEditOperation(op="add", placement=StepPlacement(position="append")),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "add_missing_payload",
                (
                    "operations[0]: 'add' operations require add_payload with a "
                    "typed new-step draft."
                ),
                None,
            )
        ]

    def test_reports_before_after_placement_missing_anchor(self):
        issues = validate_step_operation_shape(
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="before"),
                add_payload=_make_add_payload(
                    name="Summary", instructions="Summarize."
                ),
            ),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "placement_missing_anchor",
                (
                    "operations[0]: placement position 'before' requires "
                    "anchor_ref. Valid refs: ['existing_step_1']"
                ),
                None,
            )
        ]

    def test_reports_all_add_shape_issues_without_short_circuiting(self):
        issues = validate_step_operation_shape(
            StepEditOperation(
                op="add",
                target_ref="existing_step_1",
                placement=StepPlacement(position="before"),
            ),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "add_with_target_ref",
                (
                    "operations[0]: 'add' operations must NOT have target_ref. "
                    "To modify an existing step, use op='modify' instead."
                ),
                None,
            ),
            (
                "add_missing_payload",
                (
                    "operations[0]: 'add' operations require add_payload with a "
                    "typed new-step draft."
                ),
                None,
            ),
            (
                "placement_missing_anchor",
                (
                    "operations[0]: placement position 'before' requires "
                    "anchor_ref. Valid refs: ['existing_step_1']"
                ),
                None,
            ),
        ]

    def test_reports_modify_missing_target_and_patch_without_short_circuiting(self):
        issues = validate_step_operation_shape(
            StepEditOperation(op="modify"),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "modify_missing_target",
                (
                    "operations[0]: 'modify' operations require target_ref. "
                    "Valid refs: ['existing_step_1']"
                ),
                None,
            ),
            (
                "modify_missing_patch",
                "operations[0]: 'modify' operations require a patch with at least one field.",
                None,
            ),
        ]

    def test_reports_remove_missing_target(self):
        issues = validate_step_operation_shape(
            StepEditOperation(op="remove"),
            label="operations[0]",
            valid_refs=["existing_step_1"],
        )

        assert [(issue.code, issue.message, issue.step_ref) for issue in issues] == [
            (
                "remove_missing_target",
                (
                    "operations[0]: 'remove' operations require target_ref. "
                    "Valid refs: ['existing_step_1']"
                ),
                None,
            )
        ]


class TestFlowEditDraft:
    def test_minimal_draft(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=_make_add_payload(
                        name="Summary",
                        instructions="Summarize.",
                    ),
                )
            ],
            plan_rationale="Adding a summary step.",
        )
        assert len(draft.operations) == 1
        assert draft.flow_name is None
        assert draft.form_operations == []
        assert draft.assumptions == []

    def test_full_draft(self):
        draft = FlowEditDraft(
            flow_name="Updated Flow",
            flow_description="New description",
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="before", anchor_ref="existing_step_1"
                    ),
                    add_payload=_make_add_payload(
                        name="Transcription",
                        instructions="Transcribe.",
                        input_source=InputSource.FLOW_INPUT,
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ),
            ],
            form_operations=[
                FormFieldOperation(
                    op="add",
                    field_name="case_id",
                    field_payload=FormFieldSpec(
                        label="Case ID", field_type="text", required=True
                    ),
                ),
            ],
            assumptions=["Audio files are WAV or MP3"],
            plan_rationale="Adding transcription before analysis.",
        )
        assert len(draft.operations) == 2
        assert draft.operations[0].op == "add"
        assert draft.operations[1].op == "modify"
        assert len(draft.form_operations) == 1


class TestFlowEditDiff:
    def test_diff_summary(self):
        diff = FlowEditDiff(
            step_changes=[
                StepChange(kind="added", step_name="Transcription", step_ref=None),
                StepChange(
                    kind="modified",
                    step_name="Analysis",
                    step_ref="existing_step_1",
                    details="input_source: flow_input → previous_step",
                ),
                StepChange(
                    kind="unchanged", step_name="Output", step_ref="existing_step_2"
                ),
            ],
            net_steps_added=1,
            net_steps_removed=0,
        )
        assert len(diff.step_changes) == 3
        assert diff.net_steps_added == 1
        added = [c for c in diff.step_changes if c.kind == "added"]
        assert len(added) == 1
