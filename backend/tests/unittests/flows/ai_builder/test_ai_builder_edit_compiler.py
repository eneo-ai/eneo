"""Tests for AI Builder edit compiler."""

from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    FormFieldOperation,
    StepEditOperation,
    StepPatch,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    FormFieldSpec as EditFormFieldSpec,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_authoring_variable_rewriting import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy


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
    input_contract: dict | None = None,
    output_contract: dict | None = None,
    output_config: dict | None = None,
    review_policy: FlowStepReviewPolicy | None = None,
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
        input_contract=input_contract,
        output_contract=output_contract,
        output_config=output_config,
        review_policy=review_policy,
        mcp_policy=mcp_policy,
    )


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def _kb_resource(local_id: str, name: str) -> AIBuilderAvailableKnowledgeBaseResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "description": "",
    }


def _make_assistant_snapshot_context(
    *steps: FlowStep,
) -> tuple[AssistantAuthoringSnapshots, AIBuilderResourceCatalog]:
    snapshots: AssistantAuthoringSnapshots = {}
    available_models: list[AIBuilderAvailableModelResource] = []
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] = []
    for index, step in enumerate(steps, start=1):
        model_ref = str(uuid4())
        kb_ref = str(uuid4())
        snapshots[step.assistant_id] = AssistantAuthoringSnapshot(
            instructions=f"Original prompt {index}",
            model=AssistantAuthoringResourceRef(
                local_ref=model_ref,
                label=f"Model {index}",
            ),
            knowledge_refs=(
                AssistantAuthoringResourceRef(
                    local_ref=kb_ref,
                    label=f"KB {index}",
                ),
            ),
        )
        available_models.append(_model_resource(model_ref, f"Model {index}"))
        available_kbs.append(_kb_resource(kb_ref, f"KB {index}"))
    return snapshots, build_ai_builder_resource_catalog(
        available_models=available_models,
        available_kbs=available_kbs,
    )


def _make_mcp_assistant_snapshot_context(
    step: FlowStep,
) -> tuple[AssistantAuthoringSnapshots, AIBuilderResourceCatalog, AssistantSpec]:
    snapshot = AssistantAuthoringSnapshot(
        instructions="Original prompt",
        mcp_server_refs=(
            AssistantAuthoringResourceRef(local_ref="server-1", label="server-1"),
        ),
        mcp_tool_refs=(
            AssistantAuthoringResourceRef(local_ref="tool-1", label="tool-1"),
        ),
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-1",
                "ref": "server-1",
                "name": "server-1",
                "tools": [{"id": "tool-1", "ref": "tool-1", "name": "tool-1"}],
            }
        ],
    )
    return (
        {step.assistant_id: snapshot},
        catalog,
        catalog.assistant_spec_from_snapshot(snapshot),
    )


def _make_knowledge_assistant_snapshot_context(
    step: FlowStep,
) -> tuple[AssistantAuthoringSnapshots, AIBuilderResourceCatalog, AssistantSpec]:
    snapshot = AssistantAuthoringSnapshot(
        instructions="Original prompt",
        knowledge_refs=(AssistantAuthoringResourceRef(local_ref="kb-1", label="kb-1"),),
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[_kb_resource("kb-1", "kb-1")],
    )
    return (
        {step.assistant_id: snapshot},
        catalog,
        catalog.assistant_spec_from_snapshot(snapshot),
    )


def _make_add_payload(
    *,
    name: str,
    instructions: str,
    input_source: InputSource = InputSource.PREVIOUS_STEP,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    runtime_upload: bool = False,
    runtime_required: bool = False,
) -> AddStepPayload:
    return AddStepPayload(
        name=name,
        instructions=instructions,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        runtime_upload=runtime_upload,
        runtime_required=runtime_required,
    )


def test_compile_edit_draft_rejects_uncanonicalized_duplicate_modifies() -> None:
    existing = [_make_flow_step(step_order=1)]
    draft = FlowEditDraft(
        plan_rationale="Duplicate modify operations should not reach compiler.",
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Skapa rapport"),
            ),
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(output_type=OutputType.DOCX),
            ),
        ],
    )

    with pytest.raises(ValueError, match="canonicalized before compilation"):
        compile_edit_draft(draft, existing, base_flow_revision=1)


def test_compile_edit_draft_rejects_empty_step_name_patch() -> None:
    existing = [_make_flow_step(step_order=1, user_description="Original")]
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name=""),
            )
        ]
    )

    with pytest.raises(ValueError, match="Step name cannot be cleared"):
        compile_edit_draft(draft, existing, base_flow_revision=1)


def test_compile_edit_draft_clears_all_previous_input_contract() -> None:
    stale_contract = {
        "type": "object",
        "properties": {"meeting_context": {"type": "string"}},
    }
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Extrahera",
            output_type="json",
            output_contract=stale_contract,
        ),
        _make_flow_step(
            step_order=2,
            user_description="Sammanställ",
            input_source="all_previous_steps",
            input_type="text",
            output_type="json",
            input_contract=stale_contract,
            output_contract=stale_contract,
        ),
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert result.compiled_spec.steps[1].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert result.compiled_spec.steps[1].input_contract is None
    assert any(
        advisory.code == "all_previous_input_contract_cleared"
        for advisory in result.advisories
    )


def test_compile_edit_draft_preserves_existing_review_policy() -> None:
    review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Transkribera",
            review_policy=review_policy,
        )
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert result.compiled_spec.steps[0].review_policy == review_policy


def test_compile_edit_draft_updates_review_policy_from_patch() -> None:
    existing = [
        _make_flow_step(step_order=1, user_description="Transkribera"),
    ]
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(review_mode="edit"),
            )
        ],
        plan_rationale="Låt användaren korrigera transkriberingen före nästa steg.",
    )

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    review_policy = result.compiled_spec.steps[0].review_policy
    assert review_policy is not None
    assert review_policy.mode is FlowStepReviewMode.EDIT


def test_compile_edit_draft_clears_review_policy_with_explicit_null_patch() -> None:
    existing_review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Transkribera",
            review_policy=existing_review_policy,
        ),
    ]
    patch = StepPatch.model_validate({"review_mode": None})
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=patch,
            )
        ],
        plan_rationale="Ta bort manuell granskning.",
    )

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert "review_mode" in patch.model_fields_set
    assert result.compiled_spec.steps[0].review_policy is None


def test_compile_edit_draft_preserves_review_policy_when_patch_omits_review_mode() -> (
    None
):
    existing_review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Transkribera",
            review_policy=existing_review_policy,
        ),
    ]
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Transkribera och granska"),
            )
        ],
        plan_rationale="Byt namn utan att ändra granskningspunkten.",
    )

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert result.compiled_spec.steps[0].name == "Transkribera och granska"
    assert result.compiled_spec.steps[0].review_policy == existing_review_policy


def test_compile_edit_draft_repairs_audio_document_flow_missing_transcript_step() -> (
    None
):
    meeting_contract = {
        "type": "object",
        "properties": {"meeting_context": {"type": "string"}},
    }
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Etablera gemensam möteskontext",
            input_source="flow_input",
            input_type="audio",
            output_type="json",
            input_bindings={"question": "{{ step_input.text }}"},
            input_contract=None,
            output_contract=meeting_contract,
        ),
        _make_flow_step(
            step_order=2,
            user_description="Analysera bakgrund",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            input_contract=meeting_contract,
            output_contract={
                "type": "object",
                "properties": {"background_points": {"type": "array"}},
            },
        ),
        _make_flow_step(
            step_order=3,
            user_description="Skriv strukturerad mötesrapport",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
        _make_flow_step(
            step_order=4,
            user_description="Skapa PDF",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert [
        (step.input_source, step.input_type, step.output_type, step.output_mode)
        for step in result.compiled_spec.steps
    ] == [
        (
            InputSource.FLOW_INPUT,
            InputType.AUDIO,
            OutputType.TEXT,
            OutputMode.TRANSCRIBE_ONLY,
        ),
        (
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.JSON,
            OutputMode.PASS_THROUGH,
        ),
        (
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.JSON,
            OutputMode.PASS_THROUGH,
        ),
        (
            InputSource.ALL_PREVIOUS_STEPS,
            InputType.TEXT,
            OutputType.TEXT,
            OutputMode.PASS_THROUGH,
        ),
        (
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.PDF,
            OutputMode.PASS_THROUGH,
        ),
    ]
    assert result.compiled_spec.steps[1].input_bindings is None
    assert result.compiled_spec.steps[1].input_contract is None
    assert [step.plan_step_ref for step in result.compiled_spec.steps[:3]] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert result.compiled_spec.steps[1].existing_step_ref == "existing_step_1"
    assert result.compiled_spec.steps[2].input_bindings == {
        "question": "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    }
    assert any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.diff.step_changes
    )


def test_compile_edit_draft_does_not_repair_existing_audio_transcript_flow() -> None:
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Transkribera ljud",
            input_source="flow_input",
            input_type="audio",
            output_type="text",
            output_mode="transcribe_only",
        ),
        _make_flow_step(
            step_order=2,
            user_description="Skapa PDF",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert [
        (step.name, step.input_source, step.input_type, step.output_type)
        for step in result.compiled_spec.steps
    ] == [
        (
            "Transkribera ljud",
            InputSource.FLOW_INPUT,
            InputType.AUDIO,
            OutputType.TEXT,
        ),
        (
            "Skapa PDF",
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.PDF,
        ),
    ]
    assert not any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.diff.step_changes
    )


def test_compile_edit_draft_does_not_repair_audio_flow_without_document_terminal() -> (
    None
):
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Analysera ljud",
            input_source="flow_input",
            input_type="audio",
            output_type="json",
        ),
        _make_flow_step(
            step_order=2,
            user_description="Skriv svar",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert [
        (step.name, step.input_source, step.input_type, step.output_type)
        for step in result.compiled_spec.steps
    ] == [
        (
            "Analysera ljud",
            InputSource.FLOW_INPUT,
            InputType.AUDIO,
            OutputType.JSON,
        ),
        (
            "Skriv svar",
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.TEXT,
        ),
    ]
    assert not any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.diff.step_changes
    )


def test_compile_edit_draft_does_not_repair_non_audio_document_flow() -> None:
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Analysera dokument",
            input_source="flow_input",
            input_type="document",
            output_type="json",
        ),
        _make_flow_step(
            step_order=2,
            user_description="Skapa PDF",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    ]
    draft = FlowEditDraft(operations=[], plan_rationale="Behåll flödet.")

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert [
        (step.name, step.input_source, step.input_type, step.output_type)
        for step in result.compiled_spec.steps
    ] == [
        (
            "Analysera dokument",
            InputSource.FLOW_INPUT,
            InputType.DOCUMENT,
            OutputType.JSON,
        ),
        (
            "Skapa PDF",
            InputSource.PREVIOUS_STEP,
            InputType.TEXT,
            OutputType.PDF,
        ),
    ]
    assert not any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.diff.step_changes
    )


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
                    placement=StepPlacement(
                        position="before", anchor_ref="existing_step_1"
                    ),
                    add_payload=_make_add_payload(
                        name="Transkribera ljud",
                        instructions="Transkribera ljudfilen.",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                    ),
                ),
            ],
            plan_rationale="Add transcription before analysis.",
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_name="Test Flow",
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

    def test_add_step_uses_shared_new_step_draft_compilation_rules(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Analysera transkript",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
        ]

        draft = FlowEditDraft.model_validate(
            {
                "operations": [
                    {
                        "op": "add",
                        "placement": {
                            "position": "before",
                            "anchor_ref": "existing_step_1",
                        },
                        "add_payload": {
                            "name": "Transkribera ljud",
                            "instructions": "Transkribera ljudfilen ordagrant.",
                            "input_source": "flow_input",
                            "input_type": "audio",
                            "output_type": "text",
                            "runtime_upload": True,
                            "runtime_required": True,
                        },
                    }
                ],
                "plan_rationale": "Lägg till transkribering före analys.",
            }
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=1,
            flow_name="Ljudanalys",
        )

        step = result.compiled_spec.steps[0]
        assert step.name == "Transkribera ljud"
        assert step.output_mode == OutputMode.TRANSCRIBE_ONLY
        assert step.input_config == {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": "audio",
            }
        }
        assert step.assistant_spec.instructions == "Transkribera ljudfilen ordagrant."


def test_edit_compiler_ignores_form_field_that_shadows_primary_text_input():
    existing = [
        _make_flow_step(
            step_order=1,
            user_description="Analyze text",
            input_source="flow_input",
            input_type="text",
        )
    ]
    draft = FlowEditDraft(
        operations=[],
        form_operations=[
            FormFieldOperation(
                op="add",
                field_name="text",
                field_payload=EditFormFieldSpec(
                    label="Text",
                    field_type="text",
                    required=True,
                ),
            )
        ],
    )

    result = compile_edit_draft(draft, existing, base_flow_revision=1)

    assert result.compiled_spec.form_fields is None
    assert result.diff.form_changes == []
    assert any(
        advisory.code == "form_field_shadows_primary_input"
        and advisory.field == "form_fields"
        for advisory in result.advisories
    )


def test_edit_compiler_preserves_mcp_refs_when_patch_omits_resource_fields() -> None:
    existing_step = _make_flow_step(step_order=1, user_description="Fetch case")
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(instructions="Use the case data."),
                ),
            )
        ],
        plan_rationale="Update wording only.",
    )
    assistant_snapshots, resource_catalog, expected_snapshot_spec = (
        _make_mcp_assistant_snapshot_context(existing_step)
    )

    result = compile_edit_draft(
        draft,
        [existing_step],
        base_flow_revision=1,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    assistant_spec = result.compiled_spec.steps[0].assistant_spec
    assert assistant_spec.instructions == "Use the case data."
    assert assistant_spec.mcp_server_refs == expected_snapshot_spec.mcp_server_refs
    assert assistant_spec.mcp_tool_refs == expected_snapshot_spec.mcp_tool_refs


def test_edit_compiler_clears_mcp_refs_when_patch_sets_empty_lists() -> None:
    existing_step = _make_flow_step(step_order=1, user_description="Fetch case")
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(
                        instructions="No external case lookup is needed.",
                        mcp_server_refs=[],
                        mcp_tool_refs=[],
                    ),
                ),
            )
        ],
        plan_rationale="Remove external lookup.",
    )
    assistant_snapshots, resource_catalog, _ = _make_mcp_assistant_snapshot_context(
        existing_step
    )

    result = compile_edit_draft(
        draft,
        [existing_step],
        base_flow_revision=1,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    assistant_spec = result.compiled_spec.steps[0].assistant_spec
    assert assistant_spec.instructions == "No external case lookup is needed."
    assert assistant_spec.mcp_server_refs == []
    assert assistant_spec.mcp_tool_refs == []


def test_edit_compiler_switches_mcp_step_to_knowledge_without_stale_mcp_refs() -> None:
    existing_step = _make_flow_step(step_order=1, user_description="Fetch case")
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(
                        instructions="Use approved policy knowledge.",
                        knowledge_refs=["kb-1"],
                    ),
                ),
            )
        ],
        plan_rationale="Replace live lookup with static knowledge.",
    )
    assistant_snapshots, resource_catalog, _ = _make_mcp_assistant_snapshot_context(
        existing_step
    )

    result = compile_edit_draft(
        draft,
        [existing_step],
        base_flow_revision=1,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    assistant_spec = result.compiled_spec.steps[0].assistant_spec
    assert assistant_spec.knowledge_refs == ["kb-1"]
    assert assistant_spec.mcp_server_refs == []
    assert assistant_spec.mcp_tool_refs == []


def test_edit_compiler_switches_knowledge_step_to_mcp_without_stale_kb_refs() -> None:
    existing_step = _make_flow_step(step_order=1, user_description="Search policies")
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(
                    assistant_spec=AssistantSpec(
                        instructions="Fetch the live case record.",
                        mcp_server_refs=["server-1"],
                        mcp_tool_refs=["tool-1"],
                    ),
                ),
            )
        ],
        plan_rationale="Replace static policy lookup with live case lookup.",
    )
    assistant_snapshots, resource_catalog, _ = (
        _make_knowledge_assistant_snapshot_context(existing_step)
    )

    result = compile_edit_draft(
        draft,
        [existing_step],
        base_flow_revision=1,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    assistant_spec = result.compiled_spec.steps[0].assistant_spec
    assert assistant_spec.knowledge_refs == []
    assert assistant_spec.mcp_server_refs == ["server-1"]
    assert assistant_spec.mcp_tool_refs == ["tool-1"]


def test_edit_compiler_rejects_snapshot_resource_missing_from_catalog() -> None:
    existing_step = _make_flow_step(step_order=1, user_description="Search policies")
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Search policies carefully"),
            )
        ],
        plan_rationale="Update wording only.",
    )
    snapshots: AssistantAuthoringSnapshots = {
        existing_step.assistant_id: AssistantAuthoringSnapshot(
            instructions="Original prompt",
            knowledge_refs=(
                AssistantAuthoringResourceRef(
                    local_ref="missing-kb",
                    label="Sensitive policy name",
                ),
            ),
        )
    }
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
    )

    with pytest.raises(AssistantSnapshotResourceUnavailableError) as exc_info:
        compile_edit_draft(
            draft,
            [existing_step],
            base_flow_revision=1,
            assistant_snapshots=snapshots,
            resource_catalog=resource_catalog,
        )

    assert exc_info.value.kind == "knowledge_base"
    assert "Sensitive policy name" not in str(exc_info.value)


def test_edit_compiler_derives_transcribe_mode_when_modify_changes_audio_text_step() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Transkribera",
        input_type="audio",
        output_mode="pass_through",
        output_type="text",
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Transkribera ljud"),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.name == "Transkribera ljud"
    assert step.output_mode == OutputMode.TRANSCRIBE_ONLY


def test_edit_compiler_derives_transcribe_mode_when_patch_changes_input_to_audio() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Bearbeta indata",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(input_type=InputType.AUDIO),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.input_type == InputType.AUDIO
    assert step.output_mode == OutputMode.TRANSCRIBE_ONLY


def test_edit_compiler_preserves_template_fill_docx_when_patch_omits_output_mechanics() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Fyll mall",
        output_mode="template_fill",
        output_type="docx",
        output_config={"template_file_id": "template-1"},
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Fyll beslutsmall"),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.name == "Fyll beslutsmall"
    assert step.output_mode == OutputMode.TEMPLATE_FILL
    assert step.output_type == OutputType.DOCX
    assert step.output_config == {"template_file_id": "template-1"}


def test_edit_compiler_preserves_audio_transcription_mode_when_patch_only_renames() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Transkribera",
        input_type="audio",
        output_mode="transcribe_only",
        output_type="text",
    )
    assistant_snapshots, resource_catalog = _make_assistant_snapshot_context(
        existing_step
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Transkribera ljud"),
            )
        ]
    )

    result = compile_edit_draft(
        draft,
        [existing_step],
        base_flow_revision=1,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    step = result.compiled_spec.steps[0]
    assert step.name == "Transkribera ljud"
    assert step.output_mode == OutputMode.TRANSCRIBE_ONLY
    assert step.output_type == OutputType.TEXT
    assert step.assistant_spec.model_ref is None


def test_edit_compiler_preserves_generated_docx_mode_when_patch_only_renames() -> None:
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Skapa dokument",
        output_mode="pass_through",
        output_type="docx",
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(name="Skapa DOCX"),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.name == "Skapa DOCX"
    assert step.output_mode == OutputMode.PASS_THROUGH
    assert step.output_type == OutputType.DOCX


def test_edit_compiler_uses_document_delivery_mode_to_switch_template_docx_to_generated() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Fyll mall",
        output_mode="template_fill",
        output_type="docx",
        output_config={"template_file_id": "template-1"},
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(document_delivery_mode="generated"),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.output_mode == OutputMode.PASS_THROUGH
    assert step.output_type == OutputType.DOCX
    assert step.output_config is None


def test_edit_compiler_uses_document_delivery_mode_to_switch_generated_docx_to_template() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Skapa dokument",
        output_mode="pass_through",
        output_type="docx",
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(document_delivery_mode="template_fill"),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.output_mode == OutputMode.TEMPLATE_FILL
    assert step.output_type == OutputType.DOCX


def test_edit_compiler_derives_generated_pdf_when_template_fill_step_changes_to_pdf() -> (
    None
):
    existing_step = _make_flow_step(
        step_order=1,
        user_description="Fyll mall",
        output_mode="template_fill",
        output_type="docx",
        output_config={"template_file_id": "template-1"},
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="modify",
                target_ref="existing_step_1",
                patch=StepPatch(output_type=OutputType.PDF),
            )
        ]
    )

    result = compile_edit_draft(draft, [existing_step], base_flow_revision=1)

    step = result.compiled_spec.steps[0]
    assert step.output_mode == OutputMode.PASS_THROUGH
    assert step.output_type == OutputType.PDF
    assert step.output_config is None


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

    def test_modify_with_no_effect_is_collapsed_to_unchanged(self):
        existing = [
            _make_flow_step(step_order=1, user_description="First"),
            _make_flow_step(step_order=2, user_description="Second"),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(name="Second"),
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=2)

        assert [change.kind for change in result.diff.step_changes] == [
            "unchanged",
            "unchanged",
        ]
        assert all(change.details is None for change in result.diff.step_changes)

    def test_modify_step_can_rebuild_input_bindings_from_typed_previous_fields(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Extrahera JSON",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "sammanfattning": {"type": "string"},
                    },
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skriv slutrapport",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                input_bindings={"question": "{{ föregående_steg }}"},
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[
                            {
                                "from_step": 1,
                                "field_path": "sammanfattning",
                                "label": "Sammanfattning",
                            }
                        ]
                    ),
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=2)

        assert (
            result.compiled_spec.steps[1].input_bindings["question"]
            == "Sammanfattning: {{ step_a.output.structured.sammanfattning }}"
        )

    def test_modify_step_translates_original_previous_field_ref_after_removal(self):
        existing = [
            _make_flow_step(step_order=1, user_description="Remove me"),
            _make_flow_step(
                step_order=2,
                user_description="Extract",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            ),
            _make_flow_step(
                step_order=3,
                user_description="Write",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                input_bindings={"question": "{{ old }}"},
            ),
        ]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(op="remove", target_ref="existing_step_1"),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_3",
                    patch=StepPatch(
                        uses_previous_fields=[
                            {
                                "from_step": 2,
                                "field_path": "answer",
                            }
                        ]
                    ),
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=3)

        assert result.compiled_spec.steps[1].input_bindings == {
            "question": "answer: {{ step_a.output.structured.answer }}"
        }

    def test_modify_step_drops_previous_field_ref_to_removed_step(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Remove me",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"removed": {"type": "string"}},
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Extract",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            ),
            _make_flow_step(
                step_order=3,
                user_description="Write",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                input_bindings={"question": "{{ old }}"},
            ),
        ]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(op="remove", target_ref="existing_step_1"),
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_3",
                    patch=StepPatch(
                        uses_previous_fields=[
                            {
                                "from_step": 1,
                                "field_path": "removed",
                            }
                        ]
                    ),
                ),
            ],
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=3)

        assert result.compiled_spec.steps[1].input_bindings == {
            "question": "{{ step_a.output.structured }}"
        }

    def test_modify_step_form_fields_preserve_previous_source_in_underlag(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Extrahera JSON",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "sammanfattning": {"type": "string"},
                    },
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
        ]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(uses_form_fields=["case_id"]),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=2,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "case_id",
                            "type": "text",
                            "label": "Case ID",
                        }
                    ]
                }
            },
        )

        assert result.compiled_spec.steps[1].input_bindings == {
            "question": "{{ step_a.output.structured }}\n\ncase_id: {{ flow_input.case_id }}"
        }
        validation = validate_spec(result.compiled_spec)
        assert validation.valid

    def test_modify_step_ignores_form_field_that_shadows_primary_text_input(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Analyze text",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                    },
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Write report",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
        ]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(uses_form_fields=["text", "case_id"]),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=2,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "case_id",
                            "type": "text",
                            "label": "Case ID",
                        }
                    ]
                }
            },
        )

        assert result.compiled_spec.steps[1].input_bindings == {
            "question": "{{ step_a.output.structured }}\n\ncase_id: {{ flow_input.case_id }}"
        }
        assert any(
            advisory.code == "form_field_shadows_primary_input"
            and advisory.field == "form_fields"
            for advisory in result.advisories
        )

    def test_modify_all_previous_step_keeps_fan_in_implicit_and_adds_hints(self):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Extrahera JSON",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "sammanfattning": {"type": "string"},
                    },
                },
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skriv rapport",
                input_source="all_previous_steps",
                input_type="text",
                output_type="text",
            ),
        ]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_2",
                    patch=StepPatch(
                        uses_previous_fields=[
                            {
                                "from_step": 1,
                                "field_path": "sammanfattning",
                                "label": "Sammanfattning",
                            }
                        ],
                        uses_form_fields=["case_id"],
                    ),
                ),
            ],
        )

        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=2,
            current_metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "case_id",
                            "type": "text",
                            "label": "Case ID",
                        }
                    ]
                }
            },
        )

        step = result.compiled_spec.steps[1]
        assert step.input_bindings is None
        assert "Beakta särskilt följande strukturerade fält" in (
            step.assistant_spec.instructions
        )
        assert "case_id: {{ flow_input.case_id }}" in step.assistant_spec.instructions
        validation = validate_spec(result.compiled_spec)
        assert validation.valid


class TestTransitionNormalization:
    def test_text_to_pdf_edit_clears_incompatible_citation_mode_and_emits_advisory(
        self,
    ):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Grounded report",
                output_type="text",
                output_config={"citation_mode": "inline_inref_sidecar"},
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_1",
                    patch=StepPatch(output_type=OutputType.PDF),
                ),
            ],
            plan_rationale="Convert the final step to PDF.",
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=5)

        step = result.compiled_spec.steps[0]
        assert step.output_type == OutputType.PDF
        assert step.output_config is None
        assert [change.kind for change in result.diff.step_changes] == ["modified"]
        assert any(
            advisory.code == "output_config_citation_mode_cleared"
            and advisory.field == "existing_step_1.output_config.citation_mode"
            for advisory in result.advisories
        )

    def test_output_only_edit_does_not_flag_downstream_steps_modified_for_alias_rewrites(
        self,
    ):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Extrahera text",
                input_source="flow_input",
                input_type="document",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Riskanalys (JSON)",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {
                        "riskposter": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    },
                },
            ),
            _make_flow_step(
                step_order=3,
                user_description="Teorikoppling",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                input_bindings={
                    "question": "{{ step_2.output.structured }}\n\nreferensnummer: {{ flow_input.referensnummer }}"
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "teori_kopplingar": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    },
                },
            ),
            _make_flow_step(
                step_order=4,
                user_description="Grounded sammanfattning",
                input_source="all_previous_steps",
                input_type="any",
                output_type="text",
                input_bindings={
                    "question": (
                        "{{ step_1.output.text }}\n\n"
                        "{{ step_2.output.text }}\n\n"
                        "{{ step_3.output.text }}"
                    )
                },
            ),
            _make_flow_step(
                step_order=5,
                user_description="Generera DOCX",
                input_source="previous_step",
                input_type="text",
                output_type="docx",
                input_bindings={"question": "{{ föregående_steg }}"},
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_5",
                    patch=StepPatch(output_type=OutputType.PDF),
                ),
            ],
            plan_rationale="Byt bara slutformatet till PDF.",
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=3)

        assert [
            (change.step_ref, change.kind) for change in result.diff.step_changes
        ] == [
            ("existing_step_1", "unchanged"),
            ("existing_step_2", "unchanged"),
            ("existing_step_3", "unchanged"),
            ("existing_step_4", "unchanged"),
            ("existing_step_5", "modified"),
        ]
        assert result.diff.step_changes[-1].details == "output_type → pdf"

    def test_output_only_edit_does_not_flag_source_material_completion_as_modified(
        self,
    ):
        existing = [
            _make_flow_step(
                step_order=1,
                user_description="Extrahera text",
                input_source="flow_input",
                input_type="document",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Sammanfatta underlag",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"sammanfattning": {"type": "string"}},
                },
            ),
            _make_flow_step(
                step_order=3,
                user_description="Extrahera risker",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                input_bindings={"question": "{{ step_2.output.structured }}"},
                output_contract={
                    "type": "object",
                    "properties": {"risker": {"type": "array"}},
                },
            ),
            _make_flow_step(
                step_order=4,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                input_bindings={"question": "{{ step_3.output.structured }}"},
            ),
            _make_flow_step(
                step_order=5,
                user_description="Skapa DOCX",
                input_source="previous_step",
                input_type="text",
                output_type="docx",
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="modify",
                    target_ref="existing_step_5",
                    patch=StepPatch(output_type=OutputType.PDF),
                ),
            ],
            plan_rationale="Byt bara slutformatet till PDF.",
        )

        result = compile_edit_draft(draft, existing, base_flow_revision=3)

        assert [
            (change.step_ref, change.kind) for change in result.diff.step_changes
        ] == [
            ("existing_step_1", "unchanged"),
            ("existing_step_2", "unchanged"),
            ("existing_step_3", "unchanged"),
            ("existing_step_4", "unchanged"),
            ("existing_step_5", "modified"),
        ]
        step_3_question = result.compiled_spec.steps[2].input_bindings["question"]
        assert "Source material: {{ step_a.output.text }}" in step_3_question
        assert result.diff.step_changes[-1].details == "output_type → pdf"


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
                    add_payload=_make_add_payload(
                        name="Summary",
                        instructions="Summarize.",
                    ),
                ),
            ],
        )

        result1 = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=5,
            flow_name="Old Name",
        )
        result2 = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=5,
            flow_name="Old Name",
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
                user_description="Skriv slutrapport",
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
            "Tar emot uppladdade dokument vid körning och skapar en kort "
            "svensk slutrapport i textformat."
        )
        result = compile_edit_draft(
            draft,
            existing,
            base_flow_revision=5,
            flow_name="Slutrapport",
            flow_description=original_desc,
        )

        # Description is NOT mutated — advisory instead
        assert result.compiled_spec.flow_description == original_desc
        assert "flow_description" not in result.diff.flow_property_changes
        assert any(
            a.code == "flow_description_update_required" for a in result.advisories
        )

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
                    field_payload=EditFormFieldSpec(
                        required=False, label="Brukarens fullständiga namn"
                    ),
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
        assert [
            (change.kind, change.field_name) for change in result.diff.form_changes
        ] == [
            ("modified", "Brukarens namn"),
            ("added", "Uppföljningsperiod"),
        ]

    def test_canonicalizes_existing_runtime_aliases_when_inserting_before_first_step(
        self,
    ):
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
                        "Brukare: {{ flow_input.Brukarens namn }}\n"
                        "Kontext: {{ flow_input.Handläggningskontext }}\n"
                        "Behov: {{ step_1.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
                    )
                },
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="before", anchor_ref="existing_step_1"
                    ),
                    add_payload=_make_add_payload(
                        name="Transkribera ljud",
                        instructions="Transkribera ljud.",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
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
            == "Brukare: {{ flow_input.Brukarens namn }}\n"
            "Kontext: {{ flow_input.Handläggningskontext }}\n"
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
            == "Brukare: {{ flow_input.Brukarens namn }}\n"
            "Kontext: {{ flow_input.Handläggningskontext }}\n"
            "Behov: {{ step_2.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
        )

    def test_plan_step_ref_head_rewritten_for_every_template_reference_shape(
        self,
    ) -> None:
        step = StepSpec(
            plan_step_ref="step_b",
            name="Use source",
            assistant_spec=AssistantSpec(
                instructions="Use {{ step_a.output }} and {{ step_a.text }}."
            ),
            input_source=InputSource.PREVIOUS_STEP,
            input_bindings={
                "question": "Use {{ step_a.output }} and {{ step_a.text }}."
            },
        )

        rewritten = rewrite_step_spec_variables(step, {"step_a": 1, "step_b": 2})

        assert rewritten.assistant_spec.instructions == (
            "Use {{ step_1.output }} and {{ step_1.text }}."
        )
        assert rewritten.input_bindings == {
            "question": "Use {{ step_1.output }} and {{ step_1.text }}."
        }


class TestConfidence:
    def test_simple_add_is_ready(self):
        existing = [_make_flow_step(step_order=1, user_description="Step")]
        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(position="append"),
                    add_payload=_make_add_payload(
                        name="New",
                        instructions="Do.",
                    ),
                ),
            ],
        )
        result = compile_edit_draft(draft, existing, base_flow_revision=1)
        assert result.confidence == "ready"

    def test_many_operations_needs_review(self):
        existing = [
            _make_flow_step(step_order=i, user_description=f"Step {i}")
            for i in range(1, 8)
        ]
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
            _make_flow_step(
                step_order=1,
                user_description="Transcribe",
                input_source="flow_input",
                input_type="audio",
            ),
            _make_flow_step(
                step_order=2, user_description="Analyze", input_source="previous_step"
            ),
            _make_flow_step(
                step_order=3, user_description="Format", input_source="previous_step"
            ),
        ]

        draft = FlowEditDraft(
            operations=[
                StepEditOperation(
                    op="add",
                    placement=StepPlacement(
                        position="after", anchor_ref="existing_step_2"
                    ),
                    add_payload=_make_add_payload(
                        name="Classify",
                        instructions="Classify the analysis.",
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
            _make_flow_step(step_order=1, user_description="Skriv slutrapport"),
        ]
        assistant_snapshots, resource_catalog = _make_assistant_snapshot_context(
            *existing
        )

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
            resource_catalog=resource_catalog,
        )

        assistant_spec = result.compiled_spec.steps[0].assistant_spec
        expected_spec = resource_catalog.assistant_spec_from_snapshot(
            assistant_snapshots[existing[0].assistant_id]
        )
        assert assistant_spec.instructions == "Original prompt 1"
        assert assistant_spec.model_ref == expected_spec.model_ref
        assert assistant_spec.knowledge_refs == expected_spec.knowledge_refs

    def test_partial_assistant_patch_merges_with_existing_snapshot(self):
        existing = [
            _make_flow_step(step_order=1, user_description="IBIC-extraktion"),
        ]
        assistant_snapshots, resource_catalog = _make_assistant_snapshot_context(
            *existing
        )

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
            resource_catalog=resource_catalog,
        )

        assistant_spec = result.compiled_spec.steps[0].assistant_spec
        expected_spec = resource_catalog.assistant_spec_from_snapshot(
            assistant_snapshots[existing[0].assistant_id]
        )
        assert assistant_spec.instructions == "Uppdaterad prompt för IBIC-analys."
        assert assistant_spec.model_ref == expected_spec.model_ref
        assert assistant_spec.knowledge_refs == expected_spec.knowledge_refs


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
        assert (
            result.compiled_spec.flow_description
            == "Tar emot ljudfiler och transkriberar dem till text."
        )
        # Advisory tells the user the description may be stale
        assert any(
            a.code == "flow_description_update_required" for a in result.advisories
        )

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

        assert (
            result.compiled_spec.flow_description
            == "Tar emot dokument och analyserar dem."
        )
        assert not any(
            a.code == "flow_description_update_required" for a in result.advisories
        )

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
        assert not any(
            a.code == "flow_description_update_required" for a in result.advisories
        )

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
                user_description="Skriv slutrapport",
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
            flow_name="Slutrapport",
            flow_description="Skapar slutrapport i textformat.",
        )

        # Description NOT mutated
        assert (
            result.compiled_spec.flow_description == "Skapar slutrapport i textformat."
        )
        # Advisory present
        assert any(
            a.code == "flow_description_update_required" for a in result.advisories
        )

    def test_unsupported_current_flow_input_source_still_raises(self):
        existing = [
            _make_flow_step(
                step_order=1,
                input_source="http_get",
            ),
        ]

        with pytest.raises(ValueError):
            compile_edit_draft(
                FlowEditDraft(),
                existing,
                base_flow_revision=1,
                flow_description="Calls an HTTP source.",
            )
