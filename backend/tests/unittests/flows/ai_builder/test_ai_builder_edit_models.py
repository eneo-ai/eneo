"""Tests for AI Builder edit-mode domain models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    BuilderPlanEditResult,
    CompiledEditResult,
    FlowEditDiff,
    FlowEditDraft,
    FlowMetadataPatch,
    FormFieldOperation,
    FormFieldSpec,
    RuntimeInputPatch,
    StepChange,
    StepEditOperation,
    StepPatch,
    StepPlacement,
    TranscriptionPatch,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    StepSpec,
)


def _make_add_payload(
    *,
    name: str,
    instructions: str,
    input_source: InputSource = InputSource.PREVIOUS_STEP,
    input_type: InputType = InputType.TEXT,
) -> AddStepPayload:
    return AddStepPayload(
        name=name,
        instructions=instructions,
        input_source=input_source,
        input_type=input_type,
    )


def _make_compiled_edit_result() -> CompiledEditResult:
    spec = FlowDraftSpecCore(
        flow_name="Test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="append"),
                add_payload=_make_add_payload(
                    name="Step A",
                    instructions="Do.",
                ),
            ),
        ],
    )
    diff = FlowEditDiff(
        step_changes=[StepChange(kind="added", step_name="Step A")],
        net_steps_added=1,
    )
    return CompiledEditResult(
        compiled_spec=spec,
        diff=diff,
        original_draft=draft,
        base_flow_revision=3,
        warnings=["New step uses default model"],
        risk_flags=[],
        confidence="ready",
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
            metadata_patch=FlowMetadataPatch(
                transcription=TranscriptionPatch(enabled=True),
                runtime_input=RuntimeInputPatch(enabled=True, max_files=5),
            ),
            assumptions=["Audio files are WAV or MP3"],
            plan_rationale="Adding transcription before analysis.",
        )
        assert len(draft.operations) == 2
        assert draft.operations[0].op == "add"
        assert draft.operations[1].op == "modify"
        assert len(draft.form_operations) == 1
        assert draft.metadata_patch is not None
        assert draft.metadata_patch.transcription.enabled is True


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


class TestCompiledEditResult:
    def test_compiled_result_roundtrip(self):
        result = _make_compiled_edit_result()
        assert result.base_flow_revision == 3
        assert result.confidence == "ready"
        assert len(result.warnings) == 1

        # Can serialize/deserialize
        serialized = result.model_dump_json()
        restored = CompiledEditResult.model_validate_json(serialized)
        assert restored.base_flow_revision == 3
        assert restored.diff.net_steps_added == 1


class TestBuilderPlanEditResult:
    def test_flag_only_manual_description_override_roundtrips(self):
        result = BuilderPlanEditResult(description_override_manual=True)

        serialized = result.model_dump(mode="json", exclude_none=True)
        assert serialized == {"description_override_manual": True}
        restored = BuilderPlanEditResult.model_validate(serialized)
        assert restored.compiled_edit is None
        assert restored.description_override_manual is True

    def test_flat_compiled_edit_shape_is_rejected_after_migration(self):
        compiled = _make_compiled_edit_result()

        with pytest.raises(ValidationError):
            BuilderPlanEditResult.model_validate(compiled.model_dump(mode="json"))

    def test_populated_compiled_edit_result_json_roundtrips(self):
        compiled = _make_compiled_edit_result()
        result = BuilderPlanEditResult(compiled_edit=compiled)

        serialized = result.model_dump(mode="json", exclude_none=True)
        json.dumps(serialized)
        restored = BuilderPlanEditResult.model_validate(serialized)

        assert restored.compiled_edit == compiled
        assert restored.description_override_manual is False

    def test_rejects_string_manual_description_override_flag(self):
        with pytest.raises(ValidationError):
            BuilderPlanEditResult.model_validate(
                {"description_override_manual": "true"}
            )
