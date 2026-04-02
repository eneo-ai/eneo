"""Eval harness for AI Builder deterministic scenarios.

These tests verify the AI Builder's compilation and validation pipeline
against known-good scenarios WITHOUT calling the LLM. They test the
framework's correctness independently of model output quality.

Run with: uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_eval_harness.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_materializer import compile_changeset
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.flow import FlowStep
from intric.main.exceptions import BadRequestException


def _step(order: int, name: str, **kwargs) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=order,
        user_description=name,
        input_source=kwargs.get("input_source", "flow_input" if order == 1 else "previous_step"),
        input_type=kwargs.get("input_type", "text"),
        output_mode=kwargs.get("output_mode", "pass_through"),
        output_type=kwargs.get("output_type", "text"),
        mcp_policy=kwargs.get("mcp_policy", "inherit"),
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


class TestEvalScenarioCreateMode:
    """Deterministic create-mode scenarios."""

    def test_simple_2_step_flow_validates(self):
        spec = FlowDraftSpecCore(
            flow_name="Enkel analys",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera",
                    assistant_spec=AssistantSpec(instructions="Extrahera fakta från dokumentet."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.DOCUMENT,
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Sammanfatta",
                    assistant_spec=AssistantSpec(instructions="Sammanfatta de extraherade fakta."),
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        result = validate_spec(spec)
        assert result.valid, f"Errors: {[e.message for e in result.errors]}"

    def test_transcription_pipeline_validates(self):
        spec = FlowDraftSpecCore(
            flow_name="Transkription",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Transkribera",
                    assistant_spec=AssistantSpec(instructions="Transkribera ljudfilen."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Sammanfatta",
                    assistant_spec=AssistantSpec(instructions="Sammanfatta transkriptionen."),
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        result = validate_spec(spec)
        assert result.valid, f"Errors: {[e.message for e in result.errors]}"

    def test_json_output_contract_validates(self):
        spec = FlowDraftSpecCore(
            flow_name="JSON-analys",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera struktur",
                    assistant_spec=AssistantSpec(instructions="Extrahera och returnera JSON."),
                    input_source=InputSource.FLOW_INPUT,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Document title"},
                            "summary": {"type": "string", "description": "Brief summary"},
                        },
                        "required": ["title", "summary"],
                    },
                ),
            ],
        )
        result = validate_spec(spec)
        assert result.valid, f"Errors: {[e.message for e in result.errors]}"


class TestEvalScenarioEditMode:
    """Deterministic edit-mode scenarios covering the original bug."""

    def test_insert_before_step_1_preserves_existing(self):
        """THE ORIGINAL BUG: inserting before step 1 should create a new step,
        not modify the existing one."""
        existing = [_step(1, "Analysera dokument")]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="before", anchor_ref="existing_step_1"),
                    add_payload=_make_add_payload(
                        name="Transkribera",
                        instructions="Transkribera ljud.",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                    ),
                ),
            ],
        )

        # Validate
        valid_refs = [f"existing_step_{s.step_order}" for s in existing]
        validation = validate_edit_draft(draft, valid_refs)
        assert validation.valid

        # Compile
        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert len(result.compiled_spec.steps) == 2
        assert result.compiled_spec.steps[0].existing_step_ref is None  # NEW
        assert result.compiled_spec.steps[1].existing_step_ref == "existing_step_1"  # PRESERVED

    def test_remove_middle_step_keeps_others(self):
        existing = [_step(1, "A"), _step(2, "B"), _step(3, "C")]
        draft = FlowEditDraft(
            operations=[StepEditOperation(op="remove", target_ref="existing_step_2")],
        )
        valid_refs = ["existing_step_1", "existing_step_2", "existing_step_3"]
        assert validate_edit_draft(draft, valid_refs).valid

        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert len(result.compiled_spec.steps) == 2
        names = [s.name for s in result.compiled_spec.steps]
        assert "A" in names
        assert "C" in names
        assert "B" not in names

    def test_modify_only_changes_targeted_step(self):
        existing = [_step(1, "A"), _step(2, "B")]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(name="A-Updated"),
                ),
            ],
        )
        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert result.compiled_spec.steps[0].name == "A-Updated"
        assert result.compiled_spec.steps[1].name == "B"

    def test_invalid_ref_rejected_by_validator(self):
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(op="remove", target_ref="existing_step_99"),
            ],
        )
        result = validate_edit_draft(draft, ["existing_step_1"])
        assert not result.valid
        assert any("existing_step_99" in e.message for e in result.errors)

    def test_invalid_ref_rejected_by_materializer(self):
        """Phase 1.1 fix: compile_changeset hard-fails on invalid refs."""
        spec = FlowDraftSpecCore(
            flow_name="Bad edit",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    existing_step_ref="existing_step_99",
                    name="Ghost",
                    assistant_spec=AssistantSpec(instructions="Do."),
                    input_source=InputSource.FLOW_INPUT,
                ),
            ],
        )
        existing = [_step(1, "Real step")]
        from intric.flows.flow import Flow
        flow = Flow(
            id=uuid4(),
            space_id=uuid4(),
            tenant_id=uuid4(),
            name="Test",
            steps=existing,
        )
        with pytest.raises(BadRequestException, match="existing_step_99"):
            compile_changeset(spec, flow)
