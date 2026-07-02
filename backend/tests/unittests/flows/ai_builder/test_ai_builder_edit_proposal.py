from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_edit_proposal import process_edit_arguments
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from tests.unittests.flows.ai_builder.proposal_turn_builders import _make_turn


@pytest.mark.asyncio
async def test_process_edit_arguments_accepts_ordered_submission() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Rename the analysis step.",
            "assumptions": ["The existing input stays text."],
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Analyze case text",
                }
            ],
        },
    )

    assert result.failure_kind is None
    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.assumptions == [
        "The existing input stays text."
    ]
    assert (
        result.compiled_proposal.content.plan_rationale == "Rename the analysis step."
    )
    assert result.compiled_proposal.content.spec.steps[0].name == "Analyze case text"
    assert result.compiled_proposal.content.edit is not None
    assert result.compiled_proposal.content.edit.base_flow_revision == 7


@pytest.mark.asyncio
async def test_ordered_submission_rejects_omitted_existing_step() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Extract data"),
        _flow_step(
            step_order=2,
            user_description="Write report",
            input_source="previous_step",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Only mention one step.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
        },
    )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "existing_step_2" in result.feedback
    assert "removed_existing_step_refs" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_rejects_step_preserved_and_removed() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Extract data"),
        _flow_step(
            step_order=2,
            user_description="Write report",
            input_source="previous_step",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Contradict the requested removal.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
            "removed_existing_step_refs": ["existing_step_2"],
        },
    )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "existing_step_2" in result.feedback
    assert "both steps and removed_existing_step_refs" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_rejects_unknown_ref_before_omitted_add() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Remove"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Replace the current step.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_99"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Replacement",
                        "instructions": "Start from the flow input.",
                    },
                },
            ],
            "removed_existing_step_refs": ["existing_step_1"],
        },
    )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "existing_step_99" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_reports_unknown_resource_refs() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Change model.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {"model_ref": "model.missing"},
                }
            ],
        },
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            available_mcps=[],
        ),
    )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "model.missing" in result.feedback


@pytest.mark.asyncio
async def test_ordered_form_fields_preserve_on_omission() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Analyze text"),
        metadata_json=_form_metadata(
            {
                "name": "case_id",
                "type": "text",
                "label": "Case ID",
                "required": True,
            },
            {
                "name": "context",
                "type": "text",
                "label": "Context",
                "required": False,
            },
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep form fields.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.form_fields == [
        FormFieldSpec(name="case_id", type="text", label="Case ID", required=True),
        FormFieldSpec(name="context", type="text", label="Context", required=False),
    ]
    assert result.compiled_proposal.content.edit is not None
    assert result.compiled_proposal.content.edit.diff.form_changes == []


@pytest.mark.asyncio
async def test_ordered_form_fields_diff_complete_state() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Analyze text"),
        metadata_json=_form_metadata(
            {
                "name": "case_id",
                "type": "text",
                "label": "Case ID",
                "required": True,
            },
            {
                "name": "legacy_context",
                "type": "text",
                "label": "Legacy context",
            },
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Update form fields.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
            "form_fields": [
                {
                    "name": "case_id",
                    "type": "text",
                    "label": "Case reference",
                    "required": False,
                },
                {
                    "name": "review_date",
                    "type": "date",
                    "label": "Review date",
                    "required": True,
                },
            ],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.edit is not None
    assert [
        (change.kind, change.field_name)
        for change in result.compiled_proposal.content.edit.diff.form_changes
    ] == [
        ("modified", "case_id"),
        ("added", "review_date"),
        ("removed", "legacy_context"),
    ]


@pytest.mark.asyncio
async def test_ordered_step_diff_covers_unchanged_modified_added_removed() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extract case",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Review case",
            input_source="previous_step",
            input_type="json",
        ),
        _flow_step(
            step_order=3,
            user_description="Archive result",
            input_source="previous_step",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep extraction, improve review, replace archive.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "name": "Review updated",
                    "assistant_spec": {"instructions": "Review the extracted case."},
                },
                {
                    "kind": "add",
                    "step": {
                        "name": "Summarize outcome",
                        "instructions": "Summarize the reviewed case.",
                        "output_type": "text",
                    },
                },
            ],
            "removed_existing_step_refs": ["existing_step_3"],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.edit is not None
    edit = result.compiled_proposal.content.edit
    assert [
        (change.kind, change.step_ref, change.step_name)
        for change in edit.diff.step_changes
    ] == [
        ("unchanged", "existing_step_1", "Extract case"),
        ("modified", "existing_step_2", "Review updated"),
        ("added", None, "Summarize outcome"),
        ("removed", "existing_step_3", "Archive result"),
    ]
    modified = edit.diff.step_changes[1]
    assert modified.details is not None
    assert "name" in modified.details
    assert "instructions updated" in modified.details
    assert edit.diff.net_steps_added == 1
    assert edit.diff.net_steps_removed == 1
    assert edit.confidence == "ready"


@pytest.mark.asyncio
async def test_ordered_step_diff_preserves_literal_aliases_after_insertion() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Extract source"),
        _flow_step(
            step_order=2,
            user_description="Use source",
            input_source="previous_step",
            input_bindings={"question": "{{ step_1.output.text }}"},
            output_config={"template": "{{ step_1.output.text }}"},
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Insert a follow-up step before the consumer.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Review source",
                        "instructions": "Review source.",
                    },
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert result.failure_kind is None
    assert result.compiled_proposal is not None
    edit = result.compiled_proposal.content.edit
    assert edit is not None
    assert [
        (change.kind, change.step_ref, change.step_name)
        for change in edit.diff.step_changes
    ] == [
        ("unchanged", "existing_step_1", "Extract source"),
        ("added", None, "Review source"),
        ("unchanged", "existing_step_2", "Use source"),
    ]
    reordered_consumer = result.compiled_proposal.content.spec.steps[2]
    assert reordered_consumer.input_bindings == {"question": "{{ step_a.output.text }}"}
    assert reordered_consumer.output_config == {"template": "{{ step_a.output.text }}"}


@pytest.mark.asyncio
async def test_ordered_add_step_derives_omitted_input_source_through_pipeline() -> None:
    first_result = await _process(
        flow=_flow(
            _flow_step(
                step_order=1,
                user_description="Remove",
                input_type="document",
            )
        ),
        arguments={
            "plan_rationale": "Replace the first step.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "New first",
                        "instructions": "Start from the flow input.",
                    },
                }
            ],
            "removed_existing_step_refs": ["existing_step_1"],
        },
    )

    assert first_result.failure_kind is None
    assert first_result.compiled_proposal is not None
    assert (
        first_result.compiled_proposal.content.spec.steps[0].input_source
        == InputSource.FLOW_INPUT
    )

    later_result = await _process(
        flow=_flow(_flow_step(step_order=1, user_description="Keep")),
        arguments={
            "plan_rationale": "Append a follow-up step.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "New second",
                        "instructions": "Continue from the previous step.",
                    },
                },
            ],
        },
    )

    assert later_result.failure_kind is None
    assert later_result.compiled_proposal is not None
    assert (
        later_result.compiled_proposal.content.spec.steps[1].input_source
        == InputSource.PREVIOUS_STEP
    )


@pytest.mark.asyncio
async def test_ordered_add_first_document_step_derives_runtime_input_config() -> None:
    result = await _process(
        flow=_flow(
            _flow_step(
                step_order=1,
                user_description="Remove",
                input_type="document",
            )
        ),
        arguments={
            "plan_rationale": "Replace the first step with document analysis.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "Analyze document",
                        "instructions": "Analyze the uploaded document.",
                    },
                }
            ],
            "removed_existing_step_refs": ["existing_step_1"],
        },
    )

    assert result.failure_kind is None
    assert result.compiled_proposal is not None
    step = result.compiled_proposal.content.spec.steps[0]
    assert step.input_source == InputSource.FLOW_INPUT
    assert step.input_type == InputType.DOCUMENT
    assert step.input_config is not None
    runtime_input = step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == "document"
    assert runtime_input["required"] is False


@pytest.mark.asyncio
async def test_ordered_add_later_document_step_compiles_to_text_input() -> None:
    result = await _process(
        flow=_flow(_flow_step(step_order=1, user_description="Keep")),
        arguments={
            "plan_rationale": "Append a document-derived follow-up.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Use previous output",
                        "instructions": "Continue from the previous step.",
                    },
                },
            ],
        },
    )

    assert result.failure_kind is None
    assert result.compiled_proposal is not None
    step = result.compiled_proposal.content.spec.steps[1]
    assert step.input_source == InputSource.PREVIOUS_STEP
    assert step.input_type == InputType.TEXT
    assert step.input_config is None


@pytest.mark.asyncio
async def test_ordered_edit_noop_round_trip_from_snapshot_reports_unchanged_only() -> (
    None
):
    assistant_id = uuid4()
    model_id = "11111111-1111-4111-8111-111111111111"
    kb_id = "22222222-2222-4222-8222-222222222222"
    flow = _flow(
        _flow_step(
            step_order=1,
            assistant_id=assistant_id,
            user_description="Extract case",
            input_source="flow_input",
            input_type="json",
            output_type="json",
            input_config={"runtime_input": {"enabled": True, "required": True}},
            output_contract={
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
            },
        ),
        metadata_json=_form_metadata(
            {
                "name": "case_id",
                "type": "text",
                "label": "Case ID",
                "required": True,
            }
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep the existing flow unchanged.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
        },
        assistant_snapshots={
            assistant_id: AssistantAuthoringSnapshot(
                instructions="Extract case data.",
                model=AssistantAuthoringResourceRef(local_ref=model_id, label="GPT"),
                knowledge_refs=(
                    AssistantAuthoringResourceRef(local_ref=kb_id, label="Policy"),
                ),
            )
        },
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[
                {
                    "id": model_id,
                    "ref": model_id,
                    "name": "GPT",
                    "display_name": "GPT",
                    "provider": "test",
                }
            ],
            available_kbs=[
                {
                    "id": kb_id,
                    "ref": kb_id,
                    "name": "Policy",
                    "display_name": "Policy",
                    "description": "Case policy",
                }
            ],
        ),
    )

    assert result.failure_kind is None
    assert result.compiled_proposal is not None
    edit = result.compiled_proposal.content.edit
    assert edit is not None
    assert [(change.kind, change.step_ref) for change in edit.diff.step_changes] == [
        ("unchanged", "existing_step_1")
    ]
    assert edit.diff.net_steps_added == 0
    assert edit.diff.net_steps_removed == 0
    assert edit.diff.form_changes == []
    assert edit.diff.metadata_changes == []
    assert edit.diff.flow_property_changes == {}

    spec_step = result.compiled_proposal.content.spec.steps[0]
    assert spec_step.assistant_spec.instructions == "Extract case data."
    assert spec_step.assistant_spec.model_ref == "model.gpt"
    assert spec_step.assistant_spec.knowledge_refs == ["knowledge.policy"]
    assert spec_step.input_config == flow.steps[0].input_config
    assert result.compiled_proposal.content.spec.form_fields == [
        FormFieldSpec(
            name="case_id",
            type="text",
            label="Case ID",
            required=True,
        )
    ]


@pytest.mark.asyncio
async def test_ordered_edit_confidence_needs_review_for_many_changes() -> None:
    flow = _flow(
        *[
            _flow_step(
                step_order=index,
                user_description=f"Step {index}",
                input_source="flow_input" if index == 1 else "previous_step",
            )
            for index in range(1, 7)
        ]
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Rename all steps.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": f"existing_step_{index}",
                    "name": f"Step {index} updated",
                }
                for index in range(1, 7)
            ],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.edit is not None
    assert result.compiled_proposal.content.edit.confidence == "needs_review"


@pytest.mark.asyncio
async def test_ordered_form_field_shadow_declaration_is_dropped_with_advisory() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Do not duplicate primary input.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
            "form_fields": [
                {
                    "name": "text",
                    "type": "text",
                    "label": "Text",
                    "required": True,
                }
            ],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.form_fields is None
    assert result.compiled_proposal.content.edit is not None
    assert result.compiled_proposal.content.edit.diff.form_changes == []
    assert any(
        advisory.code == "form_field_shadows_primary_input"
        and advisory.field == "form_fields"
        for advisory in result.compiled_proposal.content.edit.advisories
    )


@pytest.mark.asyncio
async def test_ordered_step_shadow_reference_is_filtered_with_advisory() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extract JSON",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Write report",
            input_source="previous_step",
        ),
        metadata_json=_form_metadata(
            {
                "name": "case_id",
                "type": "text",
                "label": "Case ID",
            }
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Use only the extra form field.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "uses_form_fields": ["text", "case_id"],
                },
            ],
        },
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\ncase_id: {{ flow_input.case_id }}"
    }
    assert result.compiled_proposal.content.edit is not None
    assert any(
        advisory.code == "form_field_shadows_primary_input"
        and advisory.field == "form_fields"
        for advisory in result.compiled_proposal.content.edit.advisories
    )


@pytest.mark.asyncio
async def test_ordered_audio_repair_inserts_transcript_and_rewires_consumer() -> None:
    flow = _audio_document_flow()

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep the flow shape.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
                {"kind": "modify", "existing_step_ref": "existing_step_4"},
            ],
        },
    )

    assert result.compiled_proposal is not None
    steps = result.compiled_proposal.content.spec.steps
    assert [
        (step.input_source, step.input_type, step.output_type, step.output_mode)
        for step in steps
    ][:2] == [
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
    ]
    assert steps[1].existing_step_ref == "existing_step_1"
    assert steps[1].input_bindings is None
    assert steps[1].input_contract is None
    assert steps[1].input_config is None
    assert steps[0].input_config is not None
    runtime_input = steps[0].input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == "audio"
    assert runtime_input["required"] is True
    assert result.compiled_proposal.content.edit is not None
    assert any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.compiled_proposal.content.edit.diff.step_changes
    )
    assert result.compiled_proposal.content.edit.warnings
    assert result.compiled_proposal.content.edit.confidence == "needs_review"


@pytest.mark.asyncio
async def test_ordered_audio_repair_clears_stale_runtime_input_config() -> None:
    flow = _audio_document_flow(
        first_step_input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "required": True,
                "max_files": 3,
            }
        }
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep the flow shape.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
                {"kind": "modify", "existing_step_ref": "existing_step_4"},
            ],
        },
    )

    assert result.compiled_proposal is not None
    steps = result.compiled_proposal.content.spec.steps
    assert steps[1].existing_step_ref == "existing_step_1"
    assert steps[1].input_source == InputSource.PREVIOUS_STEP
    assert steps[1].input_type == InputType.TEXT
    assert steps[1].input_config is None
    assert steps[0].input_config is not None
    transcript_runtime_input = steps[0].input_config["runtime_input"]
    assert transcript_runtime_input["input_format"] == "audio"
    assert transcript_runtime_input["required"] is True
    assert transcript_runtime_input["max_files"] == 3


@pytest.mark.asyncio
async def test_ordered_audio_repair_does_not_duplicate_existing_transcript() -> None:
    flow = _audio_document_flow()

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "The model already inserted transcription.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "Transkribera ljud",
                        "instructions": "Transkribera uppladdat ljud till text.",
                        "output_type": "text",
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "input_source": "previous_step",
                    "input_type": "text",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
                {"kind": "modify", "existing_step_ref": "existing_step_4"},
            ],
        },
    )

    assert result.compiled_proposal is not None
    transcript_steps = [
        step
        for step in result.compiled_proposal.content.spec.steps
        if step.name == "Transkribera ljud"
    ]
    assert len(transcript_steps) == 1
    assert (
        result.compiled_proposal.content.spec.steps[1].existing_step_ref
        == "existing_step_1"
    )


@pytest.mark.asyncio
async def test_added_edit_step_uses_server_requested_primary_runtime_input() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="IBIC-extraktion",
            input_source="flow_input",
            input_type="document",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "input_format": "document",
                }
            },
        )
    )

    result = await _process(
        flow=flow,
        planning_state=_planning_state_with_primary_input("audio"),
        arguments={
            "plan_rationale": "Add transcription before document analysis.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "Transkribera ljudfil",
                        "instructions": "Transkribera ljudfilen ordagrant till svensk text.",
                        "output_type": "text",
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "input_source": "previous_step",
                    "input_type": "text",
                },
            ],
        },
    )

    assert result.compiled_proposal is not None
    steps = result.compiled_proposal.content.spec.steps
    assert steps[0].input_source == InputSource.FLOW_INPUT
    assert steps[0].input_type == InputType.AUDIO
    assert steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY
    assert steps[0].input_config is not None
    assert steps[0].input_config["runtime_input"]["required"] is True
    assert steps[1].existing_step_ref == "existing_step_1"
    assert steps[1].input_source == InputSource.PREVIOUS_STEP
    assert steps[1].input_type == InputType.TEXT


async def _process(
    *,
    flow: SimpleNamespace,
    arguments: dict[str, object],
    assistant_snapshots=None,
    resource_catalog=None,
    planning_state: PlanningState | None = None,
):
    return await process_edit_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments=arguments,
        available_model_refs=None,
        available_kb_refs=None,
        flow=flow,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
    )


def _flow(*steps: FlowStep, metadata_json: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        steps=list(steps),
        draft_revision=7,
        name="Existing flow",
        description="Existing description",
        metadata_json=metadata_json or {},
    )


def _flow_step(
    *,
    step_order: int,
    assistant_id=None,
    user_description: str,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    input_bindings: dict | None = None,
    input_contract: dict | None = None,
    output_contract: dict | None = None,
    input_config: dict | None = None,
    output_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id or uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        input_config=input_config,
        output_config=output_config,
        mcp_policy="inherit",
    )


def _planning_state_with_primary_input(value: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value=value,
        source="structured_answer",
        evidence=[],
        confidence="high",
    )
    return state


def _form_metadata(*fields: dict[str, object]) -> dict[str, object]:
    return {"form_schema": {"fields": list(fields)}}


def _audio_document_flow(
    *,
    first_step_input_config: dict | None = None,
) -> SimpleNamespace:
    meeting_contract = {
        "type": "object",
        "properties": {"meeting_context": {"type": "string"}},
    }
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Etablera gemensam möteskontext",
            input_source="flow_input",
            input_type="audio",
            output_type="json",
            input_bindings={"question": "{{ step_input.text }}"},
            input_contract=None,
            output_contract=meeting_contract,
            input_config=first_step_input_config,
        ),
        _flow_step(
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
        _flow_step(
            step_order=3,
            user_description="Skriv strukturerad mötesrapport",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=4,
            user_description="Skapa PDF",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    )
