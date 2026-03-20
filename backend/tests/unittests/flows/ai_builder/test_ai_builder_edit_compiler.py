"""Tests for AI Builder edit compiler."""

from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    FormFieldOperation,
    FormFieldSpec as EditFormFieldSpec,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_reference_rewriter import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.flow import FlowStep


def _make_flow_step(
    *,
    step_order: int,
    user_description: str = "Step",
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    mcp_policy: str = "inherit",
    input_bindings: dict | None = None,
    output_contract: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
        output_contract=output_contract,
        mcp_policy=mcp_policy,
    )


def _make_assistant_snapshots(*steps: FlowStep) -> dict:
    snapshots = {}
    for index, step in enumerate(steps, start=1):
        snapshots[step.assistant_id] = {
            "instructions": f"Original prompt {index}",
            "model_ref": str(uuid4()),
            "knowledge_refs": [f"kb-{index}"],
        }
    return snapshots


class TestAddBeforeExistingStep:
    """The original bug: adding a step before existing step 1."""

    def test_add_before_step_1_creates_new_step_and_preserves_existing(self):
        """Adding a transcription step before existing analysis should:
        - Create a NEW step at position 1
        - Preserve the existing step at position 2
        - Not modify the existing step's identity
        """
        existing = [
            _make_flow_step(step_order=1, user_description="Analysera dokument"),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="before", anchor_ref="existing_step_1"),
                    add_payload=AddStepPayload(
                        name="Transkribera ljud",
                        assistant_spec=AssistantSpec(instructions="Transkribera ljudfilen."),
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                    ),
                ),
            ],
            plan_rationale="Add transcription before analysis.",
        )

        result = compile_edit_draft(
            draft, existing, base_flow_revision=1, flow_name="Test Flow",
        )

        assert len(result.compiled_spec.steps) == 2
        # New step is first
        step1 = result.compiled_spec.steps[0]
        assert step1.name == "Transkribera ljud"
        assert step1.existing_step_ref is None  # NEW step
        assert step1.input_source == InputSource.FLOW_INPUT
        assert step1.input_type == InputType.AUDIO

        # Existing step preserved at position 2
        step2 = result.compiled_spec.steps[1]
        assert step2.name == "Analysera dokument"
        assert step2.existing_step_ref == "existing_step_1"  # PRESERVED

        # Diff
        assert result.diff.net_steps_added == 1
        assert result.diff.net_steps_removed == 0
        added = [c for c in result.diff.step_changes if c.kind == "added"]
        unchanged = [c for c in result.diff.step_changes if c.kind == "unchanged"]
        assert len(added) == 1
        assert added[0].step_name == "Transkribera ljud"
        assert len(unchanged) == 1
        assert unchanged[0].step_ref == "existing_step_1"


class TestUntouchedStepsPreserved:
    def test_modify_one_step_preserves_others(self):
        existing = [
            _make_flow_step(step_order=1, user_description="First"),
            _make_flow_step(step_order=2, user_description="Second"),
            _make_flow_step(step_order=3, user_description="Third"),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(name="Updated Second"),
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=2)

        assert len(result.compiled_spec.steps) == 3
        assert result.compiled_spec.steps[0].name == "First"
        assert result.compiled_spec.steps[1].name == "Updated Second"
        assert result.compiled_spec.steps[2].name == "Third"

        # All existing refs preserved
        for step in result.compiled_spec.steps:
            assert step.existing_step_ref is not None

        unchanged = [c for c in result.diff.step_changes if c.kind == "unchanged"]
        assert len(unchanged) == 2  # First and Third


class TestRemoveStep:
    def test_remove_only_targeted_step(self):
        existing = [
            _make_flow_step(step_order=1, user_description="First"),
            _make_flow_step(step_order=2, user_description="Second"),
            _make_flow_step(step_order=3, user_description="Third"),
        ]

        draft = FlowEditDraft(
            operations=[StepEditOperation(op="remove", target_ref="existing_step_2")],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=1)

        assert len(result.compiled_spec.steps) == 2
        assert result.compiled_spec.steps[0].name == "First"
        assert result.compiled_spec.steps[1].name == "Third"

        assert result.diff.net_steps_removed == 1
        removed = [c for c in result.diff.step_changes if c.kind == "removed"]
        assert len(removed) == 1
        assert removed[0].step_name == "Second"
        assert "step_removal" in result.risk_flags


class TestCompiledResultApproval:
    def test_stored_result_matches_preview(self):
        """The compiled result should be deterministic — what you preview
        is what gets applied."""
        existing = [
            _make_flow_step(step_order=1, user_description="Analysis"),
        ]

        draft = FlowEditDraft(
            flow_name="Renamed Flow",
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=AddStepPayload(
                        name="Summary",
                        assistant_spec=AssistantSpec(instructions="Summarize."),
                    ),
                ),
            ],
        )

        result1 = compile_edit_draft(
            draft, existing, base_flow_revision=5, flow_name="Old Name",
        )
        result2 = compile_edit_draft(
            draft, existing, base_flow_revision=5, flow_name="Old Name",
        )

        # Deterministic compilation
        assert result1.compiled_spec.flow_name == result2.compiled_spec.flow_name
        assert len(result1.compiled_spec.steps) == len(result2.compiled_spec.steps)
        assert result1.base_flow_revision == 5

        # Flow name change in diff
        assert "flow_name" in result1.diff.flow_property_changes
        old, new = result1.diff.flow_property_changes["flow_name"]
        assert old == "Old Name"
        assert new == "Renamed Flow"

    def test_output_only_edit_preserves_description_and_emits_advisory(self):
        """Output type change preserves description verbatim, emits advisory."""
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Skriv beslutsunderlag",
                output_type="text",
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        output_type=OutputType.DOCX,
                    ),
                ),
            ],
        )

        original_desc = (
            "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
            "svenskt beslutsunderlag i textformat."
        )
        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=5,
            flow_name="Beslutsunderlag",
            flow_description=original_desc,
        )

        # Description is NOT mutated — advisory instead
        assert result.compiled_spec.flow_description == original_desc
        assert "flow_description" not in result.diff.flow_property_changes
        assert any(a.code == "flow_description_update_required" for a in result.advisories)

    def test_preserves_existing_form_fields_in_compiled_preview(self):
        existing = [
            _make_flow_step(step_order=1, user_description="Analysis"),
        ]

        draft = FlowEditDraft(operations=[])

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Brukarens namn",
                            "type": "text",
                            "label": "Brukarens namn",
                            "required": True,
                        },
                        {
                            "name": "Handläggningskontext",
                            "type": "text",
                            "label": "Handläggningskontext",
                            "required": False,
                        },
                    ]
                }
            },
        )

        assert result.compiled_spec.form_fields == [
            FormFieldSpec(
                name="Brukarens namn",
                type="text",
                label="Brukarens namn",
                required=True,
            ),
            FormFieldSpec(
                name="Handläggningskontext",
                type="text",
                label="Handläggningskontext",
                required=False,
            ),
        ]

    def test_applies_form_operations_on_top_of_existing_form_fields(self):
        existing = [
            _make_flow_step(step_order=1, user_description="Analysis"),
        ]

        draft = FlowEditDraft(
            operations=[],
            form_operations=[
                FormFieldOperation(
                    op="modify",
                    field_name="Brukarens namn",
                    field_payload=EditFormFieldSpec(required=False, label="Brukarens fullständiga namn"),
                ),
                FormFieldOperation(
                    op="add",
                    field_name="Uppföljningsperiod",
                    field_payload=EditFormFieldSpec(
                        label="Uppföljningsperiod",
                        field_type="date",
                        required=True,
                    ),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Brukarens namn",
                            "type": "text",
                            "label": "Brukarens namn",
                            "required": True,
                        },
                    ]
                }
            },
        )

        assert result.compiled_spec.form_fields == [
            FormFieldSpec(
                name="Brukarens namn",
                type="text",
                label="Brukarens fullständiga namn",
                required=False,
            ),
            FormFieldSpec(
                name="Uppföljningsperiod",
                type="date",
                label="Uppföljningsperiod",
                required=True,
            ),
        ]
        assert [(change.kind, change.field_name) for change in result.diff.form_changes] == [
            ("modified", "Brukarens namn"),
            ("added", "Uppföljningsperiod"),
        ]

    def test_canonicalizes_existing_runtime_aliases_when_inserting_before_first_step(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="IBIC-extraktion",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "brukare": {
                            "type": "object",
                            "properties": {
                                "kan_uttrycka_behov_sjalv": {"type": "boolean"},
                            },
                        }
                    },
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Genomförandeplan",
                input_source="previous_step",
                input_type="json",
                output_type="docx",
                input_bindings={
                    "question": (
                        "Brukare: {{ Brukarens namn }}\n"
                        "Kontext: {{ Handläggningskontext }}\n"
                        "Behov: {{ step_1.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
                    )
                },
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="before", anchor_ref="existing_step_1"),
                    add_payload=AddStepPayload(
                        name="Transkribera ljud",
                        assistant_spec=AssistantSpec(instructions="Transkribera ljud."),
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                    ),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Brukarens namn",
                            "type": "text",
                            "label": "Brukarens namn",
                        },
                        {
                            "name": "Handläggningskontext",
                            "type": "text",
                            "label": "Handläggningskontext",
                        },
                    ]
                }
            },
        )

        generated_docx_step = result.compiled_spec.steps[2]
        assert generated_docx_step.input_bindings is not None
        assert (
            generated_docx_step.input_bindings["question"]
            == "Brukare: {{ Brukarens namn }}\n"
            "Kontext: {{ Handläggningskontext }}\n"
            "Behov: {{ step_b.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
        )

        validation = validate_spec(result.compiled_spec)
        assert validation.valid

        rewritten = rewrite_step_spec_variables(
            generated_docx_step,
            build_ref_to_order(result.compiled_spec.steps),
        )
        assert rewritten.input_bindings is not None
        assert (
            rewritten.input_bindings["question"]
            == "Brukare: {{ Brukarens namn }}\n"
            "Kontext: {{ Handläggningskontext }}\n"
            "Behov: {{ step_2.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
        )


class TestConfidence:
    def test_simple_add_is_ready(self):
        existing = [_make_flow_step(step_order=1, user_description="Step")]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=AddStepPayload(
                        name="New",
                        assistant_spec=AssistantSpec(instructions="Do."),
                    ),
                ),
            ],
        )
        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert result.confidence == "ready"

    def test_many_operations_needs_review(self):
        existing = [_make_flow_step(step_order=i, user_description=f"Step {i}") for i in range(1, 8)]
        ops = [
            StepEditOperation(
                op="modify",
                target_ref=f"existing_step_{i}",
                patch=StepPatch(name=f"Updated {i}"),
            )
            for i in range(1, 7)
        ]
        draft = FlowEditDraft(operations=ops)
        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert result.confidence == "needs_review"


class TestMixedOperations:
    def test_add_modify_remove_combined(self):
        existing = [
            _make_flow_step(step_order=1, user_description="Transcribe", input_source="flow_input", input_type="audio"),
            _make_flow_step(step_order=2, user_description="Analyze", input_source="previous_step"),
            _make_flow_step(step_order=3, user_description="Format", input_source="previous_step"),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="after", anchor_ref="existing_step_2"),
                    add_payload=AddStepPayload(
                        name="Classify",
                        assistant_spec=AssistantSpec(instructions="Classify the analysis."),
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(name="Deep Analysis"),
                ),
                StepEditOperation(
                    op="remove",
                    target_ref="existing_step_3",
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=3)

        # 3 existing - 1 removed + 1 added = 3 steps
        assert len(result.compiled_spec.steps) == 3
        assert result.compiled_spec.steps[0].name == "Transcribe"
        assert result.compiled_spec.steps[1].name == "Deep Analysis"
        assert result.compiled_spec.steps[2].name == "Classify"

        assert result.diff.net_steps_added == 1
        assert result.diff.net_steps_removed == 1


class TestAssistantSnapshotPreservation:
    def test_output_only_edit_preserves_existing_assistant_snapshot(self):
        existing = [
            _make_flow_step(step_order=1, user_description="Skriv beslutsunderlag"),
        ]
        assistant_snapshots = _make_assistant_snapshots(*existing)

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(output_type=OutputType.DOCX),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            assistant_snapshots=assistant_snapshots,
        )

        assistant_spec = result.compiled_spec.steps[0].assistant_spec
        assert assistant_spec.instructions == "Original prompt 1"
        assert assistant_spec.model_ref == assistant_snapshots[existing[0].assistant_id]["model_ref"]
        assert assistant_spec.knowledge_refs == ["kb-1"]

    def test_partial_assistant_patch_merges_with_existing_snapshot(self):
        existing = [
            _make_flow_step(step_order=1, user_description="IBIC-extraktion"),
        ]
        assistant_snapshots = _make_assistant_snapshots(*existing)

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        assistant_spec=AssistantSpec(
                            instructions="Uppdaterad prompt för IBIC-analys.",
                        ),
                    ),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            assistant_snapshots=assistant_snapshots,
        )

        assistant_spec = result.compiled_spec.steps[0].assistant_spec
        assert assistant_spec.instructions == "Uppdaterad prompt för IBIC-analys."
        assert assistant_spec.model_ref == assistant_snapshots[existing[0].assistant_id]["model_ref"]
        assert assistant_spec.knowledge_refs == ["kb-1"]


class TestFlowDescriptionSemantics:
    """Description is never mutated by regex. Semantic changes produce advisories."""

    def test_semantic_change_without_description_produces_advisory(self):
        """Audio→document with no new description → advisory, description preserved."""
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Transkribera",
                input_source="flow_input",
                input_type="audio",
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(
                        name="Analysera dokument",
                        input_type=InputType.DOCUMENT,
                    ),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_name="Transkribering",
            flow_description="Tar emot ljudfiler och transkriberar dem till text.",
        )

        # Description is NOT mutated — no regex replacement
        assert result.compiled_spec.flow_description == "Tar emot ljudfiler och transkriberar dem till text."
        # Advisory tells the user the description may be stale
        assert any(a.code == "flow_description_update_required" for a in result.advisories)

    def test_semantic_change_with_description_no_advisory(self):
        """When the LLM provides a new description, no advisory needed."""
        existing = [
            _make_flow_step(
                step_order=1,
                input_source="flow_input",
                input_type="audio",
            ),
        ]

        draft = FlowEditDraft(
            flow_description="Tar emot dokument och analyserar dem.",
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(input_type=InputType.DOCUMENT),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_description="Tar emot ljudfiler och transkriberar dem till text.",
        )

        assert result.compiled_spec.flow_description == "Tar emot dokument och analyserar dem."
        assert not any(a.code == "flow_description_update_required" for a in result.advisories)

    def test_preserves_description_when_no_semantic_change(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Analysera",
                input_source="flow_input",
                input_type="document",
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(name="Bättre namn"),
                ),
            ],
        )

        original_desc = "Tar emot dokument och analyserar dem."
        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_description=original_desc,
        )

        assert result.compiled_spec.flow_description == original_desc
        assert not any(a.code == "flow_description_update_required" for a in result.advisories)

    def test_explicit_flow_description_in_draft_takes_precedence(self):
        existing = [
            _make_flow_step(
                step_order=1,
                input_source="flow_input",
                input_type="audio",
            ),
        ]

        draft = FlowEditDraft(
            flow_description="Helt ny beskrivning från AI.",
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(input_type=InputType.DOCUMENT),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_description="Gamla beskrivningen med ljudfiler.",
        )

        assert result.compiled_spec.flow_description == "Helt ny beskrivning från AI."

    def test_output_type_change_without_description_produces_advisory(self):
        """Terminal output type change → advisory when no description provided."""
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Skriv beslutsunderlag",
                output_type="text",
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(output_type=OutputType.DOCX),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=5,
            flow_name="Beslutsunderlag",
            flow_description="Skapar beslutsunderlag i textformat.",
        )

        # Description NOT mutated
        assert result.compiled_spec.flow_description == "Skapar beslutsunderlag i textformat."
        # Advisory present
        assert any(a.code == "flow_description_update_required" for a in result.advisories)
