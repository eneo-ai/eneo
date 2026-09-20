from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    patch,
)
from uuid import uuid4

import jsonschema
import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    FlowBuilderProposal,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_admission import lower_edit_tool_arguments
from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    _step_field_changes,
    compile_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_edit_proposal import process_edit_arguments
from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_flow_review import (
    ReviewEditScope,
    validate_review_edit_effect,
    validate_review_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    AIBuilderSavedFlowStepEditContext,
    ResolvedAIBuilderEditContext,
    ScopedRevisionRejection,
    resolve_plan_edit_context,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    _prior_spec_for_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_capture import (
    REJECTED_PROPOSAL_CAPTURE_DIR_ENV,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    FlowInputFieldIntent,
    OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import resolve_ui_language
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    ProposalReady,
    TerminalFailure,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import (
    admit_propose_flow_tool_arguments,
    build_native_strict_tool_schema,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    ConfirmedRuntimeMetadataField,
    FileRoleEvidence,
    InheritedTemplateBinding,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.input_binding_contract_rules import (
    derive_structured_projection_contract,
)
from eneo.main.exceptions import BadRequestException
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

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    assert result.compiled.content.assumptions == ["The existing input stays text."]
    assert result.compiled.content.plan_rationale == "Rename the analysis step."
    assert result.compiled.content.spec.steps[0].name == "Analyze case text"
    assert result.compiled.content.edit is not None
    assert result.compiled.content.edit.base_flow_revision == 7


@pytest.mark.asyncio
async def test_process_edit_arguments_persists_resolved_saved_step_scope() -> None:
    flow_step_id = uuid4()
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Analyze text",
        )
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow_step_id),
        scope="step",
        target_existing_step_ref="existing_step_1",
        target_step_name="Analyze text",
        target_step_number=1,
    )

    result = await _process(
        flow=flow,
        plan_edit_context=context,
        arguments={
            "plan_rationale": "Clarify the analysis instructions.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {
                        "instructions": "Analyze the text and explain the result clearly."
                    },
                }
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    assert (
        result.compiled.content.edit.scoped_target_existing_step_ref
        == "existing_step_1"
    )


@pytest.mark.asyncio
async def test_process_edit_arguments_classifies_whole_flow_input_change_as_modified() -> (
    None
):
    flow = _flow(
        _flow_step(step_order=1, user_description="Collect source"),
        _flow_step(
            step_order=2,
            user_description="Write result",
            input_source="all_previous_steps",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Use the direct predecessor as the input.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "input_source": "previous_step",
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    changes = result.compiled.content.edit.diff.step_changes
    assert [(change.step_ref, change.kind) for change in changes] == [
        ("existing_step_1", "unchanged"),
        ("existing_step_2", "modified"),
    ]


@pytest.mark.asyncio
async def test_process_edit_arguments_keeps_identity_entries_unchanged() -> None:
    flow = _flow(
        _flow_step(step_order=1, user_description="Collect source"),
        _flow_step(
            step_order=2,
            user_description="Write result",
            input_source="all_previous_steps",
        ),
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
        target_step_name="Collect source",
        target_step_number=1,
    )

    result = await _process(
        flow=flow,
        plan_edit_context=context,
        arguments={
            "plan_rationale": "Clarify the source and repair its consumer.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {
                        "instructions": "Collect the source and label it clearly."
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    changes = result.compiled.content.edit.diff.step_changes
    assert [(change.step_ref, change.kind) for change in changes] == [
        ("existing_step_1", "modified"),
        ("existing_step_2", "unchanged"),
    ]


@pytest.mark.asyncio
async def test_process_edit_arguments_refines_selected_added_plan_step() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Collect source"))
    initial = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Add a report step.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Write report",
                        "instructions": "Write a concise report.",
                    },
                },
            ],
        },
    )
    assert isinstance(initial, ProposalReady)
    prior_spec = initial.compiled.content.spec
    target = prior_spec.steps[1]
    context_request = AIBuilderPlanEditContext(
        scope="step",
        plan_id=uuid4(),
        target_plan_step_ref=target.plan_step_ref,
        target_step_name=target.name,
        target_step_number=2,
    )

    result = await _process(
        flow=flow,
        prior_spec_for_revision=prior_spec,
        plan_edit_context=ResolvedAIBuilderEditContext(
            request=context_request,
            scope="step",
            target_plan_step_ref=target.plan_step_ref,
            target_step_name=target.name,
            target_step_number=2,
            plan_id=context_request.plan_id,
        ),
        arguments={
            "plan_rationale": "Make the selected report more explicit.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Write report",
                        "instructions": "Write a concise report with clear conclusions.",
                    },
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    assert (
        result.compiled.content.edit.scoped_target_plan_step_ref == target.plan_step_ref
    )
    assert (
        result.compiled.content.spec.steps[1].assistant_spec.instructions
        == "Write a concise report with clear conclusions."
    )

    replacement_spec = result.compiled.content.spec
    replacement_target = replacement_spec.steps[1]
    replacement_context_request = AIBuilderPlanEditContext(
        scope="step",
        plan_id=uuid4(),
        target_plan_step_ref=replacement_target.plan_step_ref,
        target_step_name=replacement_target.name,
        target_step_number=2,
    )
    second_result = await _process(
        flow=flow,
        prior_spec_for_revision=replacement_spec,
        plan_edit_context=ResolvedAIBuilderEditContext(
            request=replacement_context_request,
            scope="step",
            target_plan_step_ref=replacement_target.plan_step_ref,
            target_step_name=replacement_target.name,
            target_step_number=2,
            plan_id=replacement_context_request.plan_id,
        ),
        arguments={
            "plan_rationale": "Add a limitations section to the selected report.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Write report",
                        "instructions": (
                            "Write a concise report with clear conclusions and limitations."
                        ),
                    },
                },
            ],
        },
    )

    assert isinstance(second_result, ProposalReady)
    assert isinstance(second_result, ProposalReady)
    assert (
        second_result.compiled.content.spec.steps[1].assistant_spec.instructions
        == "Write a concise report with clear conclusions and limitations."
    )


@pytest.mark.asyncio
async def test_process_edit_arguments_rejects_model_authored_downstream_wiring() -> (
    None
):
    flow = _flow(
        _flow_step(step_order=1, user_description="Collect source"),
        _flow_step(
            step_order=2,
            user_description="Write result",
            input_source="previous_step",
        ),
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
        target_step_name="Collect source",
        target_step_number=1,
    )

    result = await _process(
        flow=flow,
        plan_edit_context=context,
        arguments={
            "plan_rationale": "Clarify the selected step.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {
                        "instructions": "Collect the source and label it clearly."
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "input_source": "flow_input",
                },
            ],
        },
    )

    assert isinstance(result, CorrectableFailure)
    assert result.kind == "quality"
    assert "existing_step_2" in result.feedback
    assert "selected step" in result.feedback


@pytest.mark.asyncio
async def test_process_edit_arguments_attributes_and_captures_model_parse_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REJECTED_PROPOSAL_CAPTURE_DIR_ENV, str(tmp_path))
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))
    arguments = {
        "plan_rationale": " ",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
            }
        ],
    }

    result = await _process(flow=flow, arguments=arguments)

    assert result.kind == "parse"
    assert result.codes == frozenset({"proposal_parse_model"})
    captures = list(tmp_path.glob("rejected-proposal-*.json"))
    assert len(captures) == 1


@pytest.mark.asyncio
async def test_english_edit_compiles_input_reference_hint_in_english() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extract source facts",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Compare all source facts",
            input_source="all_previous_steps",
        ),
    )

    result = await _process(
        flow=flow,
        conversation=[
            ConversationMessage(
                role="user",
                content="Update the comparison step.",
                metadata={"ui_language": "en"},
            )
        ],
        arguments={
            "plan_rationale": "Focus the comparison on the source summary.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "uses_previous_fields": [{"from_step": 1, "field_path": "summary"}],
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    instructions = result.compiled.content.spec.steps[1].assistant_spec.instructions
    assert "Pay particular attention to these structured source fields:" in instructions
    assert (
        "Beakta särskilt följande strukturerade fält i underlaget:" not in instructions
    )


@pytest.mark.asyncio
async def test_edit_rejects_invalid_typed_source_ref_without_text_fallback() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extract source facts",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Use the source summary",
            input_source="previous_step",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Use the typed source summary.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "summary",
                            "label": "{{ invalid }}",
                        }
                    ],
                },
            ],
        },
    )

    assert isinstance(result, CorrectableFailure)
    assert result.kind == "validation"
    assert result.codes == frozenset({"invalid_source_refs"})
    assert "label must not contain templates" in result.feedback
    assert "{{ invalid }}" in result.feedback


@pytest.mark.asyncio
async def test_edit_inserting_non_writer_between_body_writer_and_renderer_is_advisory() -> (
    None
):
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Write final report",
            output_mode="compose_text",
        ),
        _flow_step(
            step_order=2,
            user_description="Create PDF",
            input_source="previous_step",
            output_mode="render_verbatim",
            output_type="pdf",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Record processing metrics before rendering.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "Record processing metrics",
                        "instructions": "Record the processing duration and item count.",
                    },
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    edit = result.compiled.content.edit
    assert edit is not None
    assert any(
        advisory.code == "document_renderer_must_immediately_follow_body_writer"
        and advisory.severity == "warning"
        for advisory in edit.advisories
    )


@pytest.mark.asyncio
async def test_edit_preserving_body_writer_renderer_adjacency_has_no_topology_advisory() -> (
    None
):
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Write final report",
            output_mode="compose_text",
        ),
        _flow_step(
            step_order=2,
            user_description="Create PDF",
            input_source="previous_step",
            output_mode="render_verbatim",
            output_type="pdf",
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Clarify the body writer name.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Write polished final report",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    edit = result.compiled.content.edit
    assert edit is not None
    assert result.compiled.content.spec.document_body_writer_step_refs == ("step_a",)
    assert not any(
        advisory.code == "document_renderer_must_immediately_follow_body_writer"
        for advisory in edit.advisories
    )


@pytest.mark.asyncio
async def test_edit_reports_step_local_citation_capability_advisory() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Fill the decision template",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "citation_mode": "inline_inref_sidecar",
                "template_asset_id": str(uuid4()),
            },
        )
    )

    result = await _process(
        flow=flow,
        conversation=[
            ConversationMessage(
                role="user",
                content="Keep the template step.",
                metadata={"ui_language": "en"},
            )
        ],
        arguments={
            "plan_rationale": "Keep the existing template step.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    edit = result.compiled.content.edit
    assert edit is not None
    assert [
        (advisory.code, advisory.severity, advisory.message, advisory.field)
        for advisory in edit.advisories
        if advisory.code == "citation_mode_unsupported"
    ] == [
        (
            "citation_mode_unsupported",
            "warning",
            "Source citations were disabled because the output cannot include "
            "inline citations.",
            "existing_step_1.output_config.citation_mode",
        )
    ]


@pytest.mark.asyncio
async def test_edit_enforces_template_preparation_stage_limit() -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extract template variables",
            input_type="document",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {
                    "source_facts": {"type": "array", "items": {"type": "string"}},
                    "uncertainties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Fill DOCX template",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={"bindings": {"summary": "{{ föregående_steg }}"}},
        ),
    )

    def arguments_with_stage_count(stage_count: int) -> dict[str, object]:
        return {
            "plan_rationale": "Prepare content before filling the template.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                *[
                    {
                        "kind": "add",
                        "step": {
                            "name": f"Prepare template content {index}",
                            "instructions": (
                                f"Prepare template content for stage {index}."
                            ),
                            "output_type": "text",
                        },
                    }
                    for index in range(1, stage_count + 1)
                ],
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        }

    accepted = await _process(flow=flow, arguments=arguments_with_stage_count(5))

    assert isinstance(accepted, ProposalReady)
    assert isinstance(accepted, ProposalReady)
    assert len(accepted.compiled.content.spec.steps) == 7

    rejected = await _process(flow=flow, arguments=arguments_with_stage_count(6))

    assert isinstance(rejected, CorrectableFailure)
    assert rejected.kind == "validation"
    assert rejected.codes == frozenset({"template_preparation_stage_limit_exceeded"})


@pytest.mark.asyncio
async def test_edit_removing_required_source_reader_field_is_rejected() -> None:
    flow = _source_reader_flow()

    result = await _process(
        flow=flow,
        planning_state=_planning_state_with_slots(
            primary_runtime_input="documents",
            post_processing_goal="summarize_or_overview",
        ),
        arguments={
            "plan_rationale": "Narrow the source extraction.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title",
                        }
                    ],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, CorrectableFailure)
    assert result.kind == "validation"
    assert "source_reader_required_fields_must_be_captured" in result.codes
    assert "summary" in result.feedback


@pytest.mark.asyncio
async def test_edit_preserving_required_source_reader_field_is_accepted() -> None:
    flow = _source_reader_flow()

    result = await _process(
        flow=flow,
        planning_state=_planning_state_with_slots(
            primary_runtime_input="documents",
            post_processing_goal="summarize_or_overview",
        ),
        arguments={
            "plan_rationale": "Clarify the source reader name.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Read and summarize source",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)


@pytest.mark.asyncio
async def test_edit_removing_terminal_schema_source_leaf_is_rejected() -> None:
    result = await _process(
        flow=_terminal_schema_source_reader_flow(),
        planning_state=_terminal_schema_planning_state(),
        arguments={
            "plan_rationale": "Narrow the source extraction.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title",
                        }
                    ],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, CorrectableFailure)
    assert result.kind == "validation"
    assert "source_reader_required_fields_must_be_captured" in result.codes
    assert "source_case_id" in result.feedback


@pytest.mark.asyncio
async def test_edit_preserving_terminal_schema_source_leaf_is_accepted() -> None:
    result = await _process(
        flow=_terminal_schema_source_reader_flow(),
        planning_state=_terminal_schema_planning_state(),
        arguments={
            "plan_rationale": "Clarify the source reader name.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Read source case identity",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)


@pytest.mark.asyncio
async def test_edit_removing_compare_aggregation_target_is_rejected() -> None:
    flow = _comparison_flow()

    result = await _process(
        flow=flow,
        planning_state=_comparison_planning_state(),
        arguments={
            "plan_rationale": "Use only the immediately preceding analysis.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_3",
                    "input_source": "previous_step",
                },
            ],
        },
    )

    assert isinstance(result, CorrectableFailure)
    assert result.kind == "validation"
    assert "multi_document_compare_requires_all_previous_steps" in result.codes


@pytest.mark.asyncio
async def test_edit_preserving_compare_aggregation_target_is_accepted() -> None:
    flow = _comparison_flow()

    result = await _process(
        flow=flow,
        planning_state=_comparison_planning_state(),
        arguments={
            "plan_rationale": "Clarify the comparison step name.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_3",
                    "name": "Compare all source analyses",
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    assert result.compiled.aggregation_intent == "compare"


@pytest.mark.asyncio
async def test_edit_preserving_targeted_compare_source_refs_is_accepted() -> None:
    result = await _process(
        flow=_comparison_flow(targeted=True),
        planning_state=_comparison_planning_state(),
        arguments={
            "plan_rationale": "Clarify the targeted comparison name.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_3",
                    "name": "Compare the targeted source analyses",
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)


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

    assert result.kind == "validation"
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

    assert result.kind == "validation"
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

    assert result.kind == "validation"
    assert "existing_step_99" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_reports_unknown_resource_refs() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Add a drafting step on a model.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                },
                {
                    "kind": "add",
                    "step": {
                        "name": "Write report",
                        "instructions": "Write a concise report.",
                        "model_ref": "model.missing",
                    },
                },
            ],
        },
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
        ),
    )

    assert result.kind == "validation"
    assert "model.missing" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_rejects_unknown_flow_input_key() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Use case input."))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Keep the current step.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {
                        "instructions": "Use {{ flow_input.case_identifier }}."
                    },
                }
            ],
        },
    )

    assert result.kind == "validation"
    assert "unknown flow_input key" in result.feedback


@pytest.mark.asyncio
async def test_ordered_submission_propagates_internal_compile_error() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))

    with patch(
        "eneo.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
        side_effect=RuntimeError("compiler exploded"),
    ):
        with pytest.raises(RuntimeError, match="compiler exploded"):
            await _process(
                flow=flow,
                arguments={
                    "plan_rationale": "Rename the analysis step.",
                    "steps": [
                        {
                            "kind": "modify",
                            "existing_step_ref": "existing_step_1",
                            "name": "Analyze case text",
                        }
                    ],
                },
            )


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

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.spec.form_fields == [
        FormFieldSpec(name="case_id", type="text", label="Case ID", required=True),
        FormFieldSpec(name="context", type="text", label="Context", required=False),
    ]
    assert result.compiled.content.edit is not None
    assert result.compiled.content.edit.diff.form_changes == []


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
                    "type": "select",
                    "label": "Review date",
                    "required": True,
                    "options": ["Today", "Later"],
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    assert [
        (change.kind, change.field_name)
        for change in result.compiled.content.edit.diff.form_changes
    ] == [
        ("modified", "case_id"),
        ("added", "review_date"),
        ("removed", "legacy_context"),
    ]
    assert result.compiled.content.spec.form_fields is not None
    assert result.compiled.content.spec.form_fields[1].options == [
        "Today",
        "Later",
    ]


@pytest.mark.asyncio
async def test_review_only_edit_is_modified_and_names_the_review_policy() -> None:
    flow = _diff_fixture_flow()

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Pause for a human after the review step.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "review_mode": "view",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    changes = result.compiled.content.edit.diff.step_changes
    assert [change.kind for change in changes] == ["unchanged", "modified", "unchanged"]
    assert [(c.field, c.previous, c.current) for c in changes[1].field_changes] == [
        ("review_policy", None, "view")
    ]


@pytest.mark.asyncio
async def test_output_contract_only_edit_names_the_fields() -> None:
    result = await _process(
        flow=_source_reader_flow(),
        planning_state=_planning_state_with_slots(
            primary_runtime_input="documents",
            post_processing_goal="summarize_or_overview",
        ),
        arguments={
            "plan_rationale": "Capture the author as well.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title",
                        },
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Summary",
                        },
                        {
                            "name": "author",
                            "field_type": "string",
                            "description": "Author",
                        },
                    ],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    changes = result.compiled.content.edit.diff.step_changes
    assert changes[0].kind == "modified"
    assert [(c.field, c.previous, c.current) for c in changes[0].field_changes] == [
        ("output_contract", "summary, title", "author, summary, title")
    ]


@pytest.mark.asyncio
async def test_binding_only_edit_names_the_input_sources() -> None:
    flow = _diff_fixture_flow()

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Feed the review only the summary.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "uses_previous_fields": [{"from_step": 1, "field_path": "summary"}],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    changes = result.compiled.content.edit.diff.step_changes
    assert changes[1].kind == "modified"
    fields = {c.field: (c.previous, c.current) for c in changes[1].field_changes}
    assert fields["input_bindings"] == (None, "Extract case.summary")
    # Every modified step explains itself: no change without a field behind it.
    assert all(change.field_changes for change in changes if change.kind == "modified")


def _diff_fixture_flow() -> SimpleNamespace:
    return _flow(
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


@pytest.mark.asyncio
async def test_same_leaf_schema_change_shows_two_different_values() -> None:
    # The short reading of a contract is its leaf names; when only a leaf's
    # type changes the row must still show a difference, not "summary → summary".
    result = await _process(
        flow=_source_reader_flow(),
        planning_state=_planning_state_with_slots(
            primary_runtime_input="documents",
            post_processing_goal="summarize_or_overview",
        ),
        arguments={
            "plan_rationale": "Make the summary a list of points.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title",
                        },
                        {
                            "name": "summary",
                            "field_type": "array",
                            "description": "Summary points",
                        },
                    ],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    (change,) = result.compiled.content.edit.diff.step_changes[0].field_changes
    assert change.field == "output_contract"
    # The short reading is the leaf names, unchanged here; the complete value
    # travels beside it and is what shows the type.
    assert change.previous == change.current == "summary, title"
    assert change.previous_detail is not None
    assert '"summary":{"type":"string"}' in change.previous_detail
    assert (
        change.current_detail is not None and '"type":"array"' in change.current_detail
    )


def test_json_typed_values_are_compared_as_json() -> None:
    # Python reads True and 1 as equal; a JSON Schema does not, and a schema is
    # exactly what a contract is. The diff owner compares canonical JSON.
    def step(flag_const: object) -> StepSpec:
        return StepSpec(
            plan_step_ref="step_1",
            existing_step_ref="existing_step_1",
            name="Extract",
            assistant_spec=AssistantSpec(instructions="Extract."),
            input_source=InputSource.FLOW_INPUT,
            input_type=InputType.TEXT,
            output_mode=OutputMode.PASS_THROUGH,
            output_type=OutputType.JSON,
            output_contract={
                "type": "object",
                "properties": {"flag": {"const": flag_const}},
            },
        )

    (change,) = _step_field_changes(step(True), step(1), step_label=lambda ref: ref)
    assert change.field == "output_contract"
    assert (
        change.previous_detail is not None and '"const":true' in change.previous_detail
    )
    assert change.current_detail is not None and '"const":1' in change.current_detail
    assert _step_field_changes(step(True), step(True), step_label=lambda ref: ref) == []


@pytest.mark.asyncio
async def test_adding_a_leaf_and_changing_a_type_at_once_keeps_both_on_record() -> None:
    result = await _process(
        flow=_source_reader_flow(),
        planning_state=_planning_state_with_slots(
            primary_runtime_input="documents",
            post_processing_goal="summarize_or_overview",
        ),
        arguments={
            "plan_rationale": "Add the author and make the summary a list.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title",
                        },
                        {
                            "name": "summary",
                            "field_type": "array",
                            "description": "Summary points",
                        },
                        {
                            "name": "author",
                            "field_type": "string",
                            "description": "Author",
                        },
                    ],
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    (change,) = result.compiled.content.edit.diff.step_changes[0].field_changes
    assert (change.previous, change.current) == (
        "summary, title",
        "author, summary, title",
    )
    assert change.current_detail is not None
    assert '"summary":{"description":"Summary points"' in change.current_detail
    assert '"type":"array"' in change.current_detail


@pytest.mark.asyncio
async def test_binding_change_between_question_and_sources_names_both() -> None:
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
            input_bindings={"question": "Bedöm ärendet: {{ step_1.output.text }}"},
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Feed the review only the summary.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "uses_previous_fields": [{"from_step": 1, "field_path": "summary"}],
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    fields = {
        c.field: (c.previous, c.current)
        for c in result.compiled.content.edit.diff.step_changes[1].field_changes
    }
    previous, current = fields["input_bindings"]
    assert previous is not None and previous.startswith("Bedöm ärendet:")
    assert current == "Extract case.summary"
    assert "source_refs" not in current and "question template" not in previous


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

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    edit = result.compiled.content.edit
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
    assert [
        (change.field, change.previous, change.current)
        for change in modified.field_changes
    ] == [
        ("name", "Review case", "Review updated"),
        ("instructions", None, "Review the extracted case."),
    ]
    assert edit.diff.step_changes[0].field_changes == []
    assert edit.diff.net_steps_added == 1
    assert edit.diff.net_steps_removed == 1
    assert edit.confidence == "ready"


@pytest.mark.asyncio
async def test_approval_diff_describes_the_prepared_spec_not_the_compiled_one() -> None:
    # Session preparation renames the second of two same-named steps after the
    # compiler has diffed; the approval must report the name the user gets.
    flow = _flow(_flow_step(step_order=1, user_description="Sammanfatta ärendet"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Add a second summary pass.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {
                        "name": "sammanfatta ärendet",
                        "instructions": "Summarize the case again, shorter.",
                        "output_type": "text",
                    },
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    added_step = result.compiled.content.spec.steps[-1]
    assert added_step.name == "sammanfatta ärendet (2)"
    added_change = result.compiled.content.edit.diff.step_changes[-1]
    assert (added_change.kind, added_change.step_name) == (
        "added",
        added_step.name,
    )


@pytest.mark.asyncio
async def test_approval_diff_reports_an_existing_step_renamed_by_preparation() -> None:
    # The added step comes first, so preparation suffixes the EXISTING step's
    # name; that rename is a field change the user must see before approving.
    flow = _flow(_flow_step(step_order=1, user_description="Sammanfatta ärendet"))

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Summarize first, then keep the existing pass.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "sammanfatta ärendet",
                        "instructions": "Summarize the case briefly.",
                        "output_type": "text",
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "input_source": "previous_step",
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    existing_step = result.compiled.content.spec.steps[-1]
    assert existing_step.name == "Sammanfatta ärendet (2)"
    existing_change = result.compiled.content.edit.diff.step_changes[-1]
    assert existing_change.kind == "modified"
    assert existing_change.step_name == existing_step.name
    assert ("name", "Sammanfatta ärendet", "Sammanfatta ärendet (2)") in [
        (change.field, change.previous, change.current)
        for change in existing_change.field_changes
    ]


async def test_strict_shaped_edit_compiles_like_the_sparse_one_and_passes_review_scope() -> (
    None
):
    # A strict provider sends every property, null where it changes nothing.
    # That payload must validate against the projected strict schema, lower to
    # the same proposal as the sparse one, compile to the same spec and diff,
    # and read as "changed nothing" to the review scope.
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
            user_description="Write report",
            input_source="previous_step",
            input_type="json",
        ),
    )
    schema = build_edit_flow_tool_schema(
        flow.steps,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
    )

    def strict_modify(ref: str, **changes: object) -> dict[str, object]:
        return {
            "kind": "modify",
            "existing_step_ref": ref,
            "name": None,
            "assistant_spec": {"instructions": None, "knowledge_refs": None},
            "input_source": None,
            "input_type": None,
            "output_type": None,
            "document_delivery_mode": None,
            "uses_form_fields": None,
            "uses_previous_fields": None,
            "output_fields": None,
            "review_mode": None,
            **changes,
        }

    strict_arguments: dict[str, object] = {
        "plan_rationale": "Sharpen the extraction instructions.",
        "assumptions": [],
        "flow_name": None,
        "flow_description": None,
        "steps": [
            strict_modify(
                "existing_step_1",
                assistant_spec={
                    "instructions": "Extract the case facts as JSON.",
                    "knowledge_refs": None,
                },
            ),
            strict_modify("existing_step_2"),
        ],
        "removed_existing_step_refs": [],
        "form_fields": None,
    }
    sparse_arguments: dict[str, object] = {
        "plan_rationale": "Sharpen the extraction instructions.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "assistant_spec": {"instructions": "Extract the case facts as JSON."},
            },
            {"kind": "modify", "existing_step_ref": "existing_step_2"},
        ],
    }
    strict_schema = build_native_strict_tool_schema(schema)  # type: ignore[arg-type]
    jsonschema.validate(strict_arguments, strict_schema["function"]["parameters"])

    strict_result = await _process(flow=flow, arguments=strict_arguments)
    sparse_result = await _process(flow=flow, arguments=sparse_arguments)

    assert isinstance(strict_result, ProposalReady)
    assert isinstance(sparse_result, ProposalReady)
    assert strict_result.compiled.content.spec == sparse_result.compiled.content.spec
    assert strict_result.compiled.content.edit is not None
    assert sparse_result.compiled.content.edit is not None
    assert (
        strict_result.compiled.content.edit.diff
        == sparse_result.compiled.content.edit.diff
    )
    assert [c.kind for c in strict_result.compiled.content.edit.diff.step_changes] == [
        "modified",
        "unchanged",
    ]

    # Held to a review scope that names only step 1, the strict payload
    # authored nothing on step 2 and nothing at flow level.
    scope = ReviewEditScope(
        step_refs=frozenset({"existing_step_1"}),
        removable_step_refs=frozenset(),
        may_add=False,
    )
    lowered = OrderedEditProposal.model_validate(
        lower_edit_tool_arguments(strict_arguments)
    )
    assert (
        validate_review_edit_proposal(
            scope=scope,
            proposal=lowered,
            flow_name=flow.name,
            flow_description=flow.description,
            current_step_refs=["existing_step_1", "existing_step_2"],
        )
        is None
    )
    assert (
        validate_review_edit_effect(
            scope=scope, diff=strict_result.compiled.content.edit.diff
        )
        is None
    )


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

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    edit = result.compiled.content.edit
    assert edit is not None
    assert [
        (change.kind, change.step_ref, change.step_name)
        for change in edit.diff.step_changes
    ] == [
        ("unchanged", "existing_step_1", "Extract source"),
        ("added", None, "Review source"),
        ("unchanged", "existing_step_2", "Use source"),
    ]
    reordered_consumer = result.compiled.content.spec.steps[2]
    assert reordered_consumer.input_bindings == {"question": "{{ step_a.output.text }}"}
    assert reordered_consumer.output_config == {"template": "{{ step_a.output.text }}"}


@pytest.mark.asyncio
async def test_ordered_step_diff_keeps_placeholder_named_step_ref_on_its_producer() -> (
    None
):
    # Gate 2026-09-05: alias translation must read the source_refs structure,
    # not every key spelled "step_ref": a document placeholder may carry that
    # name and its template must move with the producer like any other.
    flow = _flow(
        _flow_step(step_order=1, user_description="Extract source"),
        _flow_step(
            step_order=2,
            user_description="Write body",
            input_source="previous_step",
            input_bindings={"question": "{{ step_1.output.text }}"},
        ),
        _flow_step(
            step_order=3,
            user_description="Render",
            input_source="previous_step",
            output_config={
                "step_ref": "{{ step_2.output.text }}",
                "other": "{{ step_2.output.text }}",
            },
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Insert a review step before the body writer.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "add",
                    "step": {"name": "Review source", "instructions": "Review."},
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    renderer = result.compiled.content.spec.steps[3]
    assert renderer.output_config == {
        "step_ref": "{{ step_c.output.text }}",
        "other": "{{ step_c.output.text }}",
    }


@pytest.mark.asyncio
async def test_ordered_edit_rewrites_source_ref_runtime_aliases_to_plan_refs() -> None:
    # Live 2026-09-05: a builder-built flow (reader -> JSON summary -> text
    # composer bound through source_refs) could not be edited at all. The
    # compiled spec renamed steps to plan refs but left source_refs pointing
    # at runtime aliases, so the composer critic saw no consumed structured
    # priors and rejected an untouched topology.
    documents_contract = {
        "type": "object",
        "properties": {"documents": {"type": "array", "items": {"type": "object"}}},
    }
    summary_contract = {
        "type": "object",
        "properties": {"points": {"type": "array", "items": {"type": "string"}}},
    }
    summarize_bindings = {
        "source_refs": [
            {
                "label": "documents",
                "output": "structured",
                "step_ref": "step_1",
                "field_path": "documents",
            }
        ]
    }
    # The persisted contract is the exact projection of the bound field.
    summarize_contract = derive_structured_projection_contract(
        input_bindings=summarize_bindings,
        source_contracts_by_step_ref={"step_1": documents_contract},
    )
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Read sources",
            input_type="document",
            output_type="json",
            output_contract=documents_contract,
        ),
        _flow_step(
            step_order=2,
            user_description="Summarize",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            input_bindings=summarize_bindings,
            input_contract=summarize_contract,
            output_contract=summary_contract,
        ),
        _flow_step(
            step_order=3,
            user_description="Write news",
            input_source="previous_step",
            input_bindings={
                "source_refs": [
                    {
                        "label": "documents",
                        "output": "structured",
                        "step_ref": "step_1",
                        "field_path": "documents",
                    },
                    {
                        "label": "points",
                        "output": "structured",
                        "step_ref": "step_2",
                        "field_path": "points",
                    },
                ]
            },
        ),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Shorten the news item.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_3",
                    "name": "Write short news",
                    "assistant_spec": {"instructions": "At most 80 words."},
                },
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    steps = result.compiled.content.spec.steps
    assert steps[1].input_contract == summarize_contract
    assert [ref["step_ref"] for ref in steps[1].input_bindings["source_refs"]] == [
        "step_a"
    ]
    assert [ref["step_ref"] for ref in steps[2].input_bindings["source_refs"]] == [
        "step_a",
        "step_b",
    ]


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

    assert isinstance(first_result, ProposalReady)
    assert isinstance(first_result, ProposalReady)
    assert (
        first_result.compiled.content.spec.steps[0].input_source
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

    assert isinstance(later_result, ProposalReady)
    assert isinstance(later_result, ProposalReady)
    assert (
        later_result.compiled.content.spec.steps[1].input_source
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

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    step = result.compiled.content.spec.steps[0]
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

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    step = result.compiled.content.spec.steps[1]
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

    assert isinstance(result, ProposalReady)
    assert isinstance(result, ProposalReady)
    edit = result.compiled.content.edit
    assert edit is not None
    assert [(change.kind, change.step_ref) for change in edit.diff.step_changes] == [
        ("unchanged", "existing_step_1")
    ]
    assert edit.diff.net_steps_added == 0
    assert edit.diff.net_steps_removed == 0
    assert edit.diff.form_changes == []
    assert edit.diff.metadata_changes == []
    assert edit.diff.flow_property_changes == {}

    spec_step = result.compiled.content.spec.steps[0]
    assert spec_step.assistant_spec.instructions == "Extract case data."
    assert spec_step.assistant_spec.model_ref == "model.gpt"
    assert spec_step.assistant_spec.knowledge_refs == ["knowledge.policy"]
    assert spec_step.input_config == flow.steps[0].input_config
    assert result.compiled.content.spec.form_fields == [
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

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.edit is not None
    assert result.compiled.content.edit.confidence == "needs_review"


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
                    "provenance": "user_confirmed",
                }
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.spec.form_fields is None
    assert result.compiled.content.edit is not None
    assert result.compiled.content.edit.diff.form_changes == []
    assert any(
        advisory.code == "form_field_shadows_primary_input"
        and advisory.field == "form_fields"
        and advisory.field_provenance == "model_proposed"
        for advisory in result.compiled.content.edit.advisories
    )


@pytest.mark.asyncio
async def test_confirmed_edit_field_options_survive_server_owned_projection() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="priority",
                label="Priority",
                field_type="select",
                required=True,
                options=["Low", "High"],
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-1",
        )
    ]

    result = await _process(
        flow=flow,
        planning_state=state,
        arguments={
            "plan_rationale": "Use the confirmed priority field.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
            "form_fields": [
                {
                    "name": "priority",
                    "type": "select",
                    "label": "Changed by model",
                    "options": ["Other"],
                }
            ],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.spec.form_fields == [
        FormFieldSpec(
            name="priority",
            type="select",
            label="Priority",
            required=True,
            options=["Low", "High"],
        )
    ]


@pytest.mark.asyncio
async def test_confirmed_edit_field_survives_when_model_omits_form_fields() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="priority",
                label="Priority",
                field_type="select",
                required=True,
                options=["Low", "High"],
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-1",
        )
    ]

    result = await _process(
        flow=flow,
        planning_state=state,
        arguments={
            "plan_rationale": "Keep the confirmed priority field.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
        },
    )

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.spec.form_fields == [
        FormFieldSpec(
            name="priority",
            type="select",
            label="Priority",
            required=True,
            options=["Low", "High"],
        )
    ]


@pytest.mark.asyncio
async def test_confirmed_edit_shadow_field_is_rejected_explicitly() -> None:
    flow = _flow(_flow_step(step_order=1, user_description="Analyze text"))
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="text",
                label="Text",
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-1",
        )
    ]

    result = await _process(
        flow=flow,
        planning_state=state,
        arguments={
            "plan_rationale": "Use the confirmed text field.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_1"}],
            "form_fields": [{"name": "text", "type": "text", "label": "Text"}],
        },
    )

    assert isinstance(result, TerminalFailure)
    assert result.kind == "architecture"
    assert result.codes == frozenset({"confirmed_form_field_incompatible"})


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

    assert isinstance(result, ProposalReady)
    assert result.compiled.content.spec.steps[1].input_bindings == {
        "question": "case_id: {{ flow_input.case_id }}",
        "source_refs": [{"step_ref": "step_a", "output": "structured"}],
    }
    assert result.compiled.content.edit is not None
    assert any(
        advisory.code == "form_field_shadows_primary_input"
        and advisory.field == "form_fields"
        for advisory in result.compiled.content.edit.advisories
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

    assert isinstance(result, ProposalReady)
    steps = result.compiled.content.spec.steps
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
    assert result.compiled.content.edit is not None
    assert any(
        change.kind == "added" and change.step_name == "Transkribera ljud"
        for change in result.compiled.content.edit.diff.step_changes
    )
    assert result.compiled.content.edit.warnings
    assert result.compiled.content.edit.confidence == "needs_review"


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

    assert isinstance(result, ProposalReady)
    steps = result.compiled.content.spec.steps
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

    assert isinstance(result, ProposalReady)
    transcript_steps = [
        step
        for step in result.compiled.content.spec.steps
        if step.name == "Transkribera ljud"
    ]
    assert len(transcript_steps) == 1
    assert result.compiled.content.spec.steps[1].existing_step_ref == "existing_step_1"


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

    assert isinstance(result, ProposalReady)
    steps = result.compiled.content.spec.steps
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
    conversation: list[ConversationMessage] | None = None,
    assistant_snapshots=None,
    resource_catalog=None,
    planning_state: PlanningState | None = None,
    plan_edit_context: ResolvedAIBuilderEditContext | None = None,
    prior_spec_for_revision=None,
):
    return await process_edit_arguments(
        turn=_make_turn(),
        conversation=conversation or [],
        arguments=arguments,
        available_model_refs=None,
        available_kb_refs=None,
        flow=flow,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
        plan_edit_context=plan_edit_context,
        prior_spec_for_revision=prior_spec_for_revision,
        compile_context=create_compile_context_from_planning_state(
            planning_state,
            ui_language=resolve_ui_language(conversation or []),
        ),
    )


def _flow(*steps: FlowStep, metadata_json: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        steps=list(steps),
        draft_revision=7,
        name="Existing flow",
        description="Existing description",
        metadata_json=metadata_json or {},
    )


def _saved_step_large_flow_fixture(step_count: int):
    flow = _flow(
        *(
            _flow_step(
                step_order=order,
                user_description=f"Step {order}",
                input_source="flow_input" if order == 1 else "previous_step",
            )
            for order in range(1, step_count + 1)
        )
    )
    snapshots = {
        step.assistant_id: AssistantAuthoringSnapshot(
            instructions=f"Saved instructions for step {step.step_order}."
        )
        for step in flow.steps
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[3].id),
        scope="step",
        target_existing_step_ref="existing_step_4",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None
    return flow, snapshots, catalog, context, prior


@pytest.mark.parametrize("step_count", [10, 40])
async def test_saved_step_fragment_expands_without_changing_untouched_steps(step_count):
    flow, snapshots, catalog, context, prior = _saved_step_large_flow_fixture(
        step_count
    )
    before = [
        canonical_json_bytes(step.model_dump(mode="json")) for step in prior.steps
    ]
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Clarify the selected instructions.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_4",
                    "assistant_spec": {"instructions": "Explain the evidence clearly."},
                }
            ],
        },
    )
    assert isinstance(result, ProposalReady), result
    compiled = result.compiled.content.spec
    assert len(compiled.steps) == step_count
    assert [step.existing_step_ref for step in compiled.steps] == [
        step.existing_step_ref for step in prior.steps
    ]
    assert (
        compiled.steps[3].assistant_spec.instructions == "Explain the evidence clearly."
    )
    for index, step in enumerate(compiled.steps):
        if index != 3:
            assert canonical_json_bytes(step.model_dump(mode="json")) == before[index]
    assert [
        canonical_json_bytes(step.model_dump(mode="json")) for step in prior.steps
    ] == before


@pytest.mark.parametrize(
    ("submitted_refs", "feedback"),
    [
        (["existing_step_99"], "unknown"),
        (["existing_step_5"], "selected"),
        (["existing_step_4", "existing_step_4"], "once"),
    ],
)
async def test_saved_step_fragment_rejects_invalid_refs_even_without_changes(
    submitted_refs, feedback
):
    flow, snapshots, catalog, context, prior = _saved_step_large_flow_fixture(10)
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Clarify the selected instructions.",
            "steps": [
                {"kind": "modify", "existing_step_ref": ref} for ref in submitted_refs
            ],
        },
    )
    assert isinstance(result, CorrectableFailure), result
    assert feedback in result.feedback.lower()
    assert submitted_refs[0] in result.feedback


def test_saved_step_revision_sequence_is_checked_before_fragment_expansion():
    flow, snapshots, catalog, _, prior = _saved_step_large_flow_fixture(10)
    stale_sequence = prior.model_copy(update={"steps": list(reversed(prior.steps))})
    proposal = OrderedEditProposal.model_validate(
        {
            "plan_rationale": "Clarify the selected instructions.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_99"}],
        }
    )
    with pytest.raises(
        BadRequestException, match="revision must preserve the saved step sequence"
    ):
        compile_edit_proposal(
            proposal,
            current_steps=flow.steps,
            base_flow_revision=flow.draft_revision,
            assistant_snapshots=snapshots,
            resource_catalog=catalog,
            revision_spec=stale_sequence,
        )


async def test_saved_step_repair_replays_fragment_and_names_target():
    import json

    from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
        ProposalCompleted,
        flatten_proposal_message_groups,
    )
    from tests.unittests.flows.ai_builder.test_ai_builder_proposal_retry import (
        _collect,
        _make_self_correction_request,
        _original_tool_call,
        _tool_response,
    )

    flow, snapshots, catalog, context, prior = _saved_step_large_flow_fixture(40)
    arguments = {
        "plan_rationale": "Clarify the selected instructions.",
        "steps": [{"kind": "modify", "existing_step_ref": "existing_step_4"}],
    }

    async def process(arguments):
        return await _process(
            flow=flow,
            assistant_snapshots=snapshots,
            resource_catalog=catalog,
            plan_edit_context=context,
            prior_spec_for_revision=prior,
            arguments=arguments,
        )

    failure = await process(arguments)
    assert isinstance(failure, CorrectableFailure), failure
    assert "existing_step_4" in failure.feedback
    corrected = {
        **arguments,
        "steps": [
            {
                **arguments["steps"][0],
                "assistant_spec": {"instructions": "Explain the evidence clearly."},
            }
        ],
    }
    repair = AsyncMock(return_value=_tool_response(arguments=corrected))
    compiled = []

    async def process_invocation(invocation):
        outcome = await process(invocation.arguments)
        assert isinstance(outcome, ProposalReady), outcome
        compiled.append(outcome.compiled.content.spec)
        return ProposalCompleted(events=())

    await _collect(
        _make_self_correction_request(
            failure=failure,
            tool_call=_original_tool_call(json.dumps(arguments)),
            repair_completion=repair,
            process_tool_invocation=process_invocation,
        )
    )
    repair.assert_awaited_once()
    messages = flatten_proposal_message_groups(repair.call_args.args[0].message_groups)
    replay = json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"])
    assert replay == arguments
    assert len(replay["steps"]) == 1
    assert "existing_step_4" in messages[-1]["content"]
    assert len(compiled) == 1 and len(compiled[0].steps) == 40


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
    )


def _planning_state_with_primary_input(value: str) -> PlanningState:
    state = _planning_state_with_slots(primary_runtime_input=value)
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type=InputType(value),
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                )
            ],
            chosen_patterns=["audio_transcription"],
        )
    )
    return state


def _planning_state_with_slots(**values: str) -> PlanningState:
    state = PlanningState.empty()
    for name, value in values.items():
        state.resolved_slots[name] = ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            evidence=[],
            confidence="high",
        )
    return state


def _form_metadata(*fields: dict[str, object]) -> dict[str, object]:
    return {"form_schema": {"fields": list(fields)}}


def _comparison_flow(*, targeted: bool = False) -> SimpleNamespace:
    reader_contract = {
        "type": "object",
        "properties": {"analysis": {"type": "string"}},
    }
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Read first source",
            input_type="document",
            output_type="json",
            output_contract=reader_contract,
        ),
        _flow_step(
            step_order=2,
            user_description="Analyze source evidence",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_contract=reader_contract,
        ),
        _flow_step(
            step_order=3,
            user_description="Compare source analyses",
            input_source="previous_step" if targeted else "all_previous_steps",
            input_type="text",
            input_bindings=(
                {
                    "source_refs": [
                        {"step_ref": "step_a", "output": "structured"},
                        {"step_ref": "step_b", "output": "structured"},
                    ]
                }
                if targeted
                else None
            ),
        ),
    )


def _comparison_planning_state() -> PlanningState:
    state = _planning_state_with_slots(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="multiple_documents_case",
        comparison_scope="same_run_compare",
    )
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                )
            ],
            chosen_patterns=["document_to_structured_report", "comparison"],
            aggregation_intent="compare",
        )
    )
    return state


def _source_reader_flow() -> SimpleNamespace:
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Read source",
            input_type="document",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Write report",
            input_source="previous_step",
            input_type="json",
        ),
    )


def _terminal_schema_source_reader_flow() -> SimpleNamespace:
    contract = {
        "type": "object",
        "properties": {"source_case_id": {"type": "string"}},
    }
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Read source case identity",
            input_type="document",
            output_type="json",
            output_contract=contract,
        ),
        _flow_step(
            step_order=2,
            user_description="Build structured result",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_contract=contract,
        ),
    )


def _terminal_schema_planning_state() -> PlanningState:
    state = _planning_state_with_slots(
        primary_runtime_input="documents",
        terminal_output="structured_json",
    )
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"source_case_id": {"type": "string"}},
        },
        source="declared_schema",
        confidence="high",
        evidence=["message:source_case_id"],
    )
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                    output_mode=OutputMode.PASS_THROUGH,
                )
            ],
            chosen_patterns=["document_to_structured_report"],
        )
    )
    return state


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
            output_mode="render_verbatim",
            output_type="pdf",
        ),
    )


def test_the_turn_scope_is_read_from_the_handoff_and_not_after_the_user_typed() -> None:
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        review_edit_scope_for_turn,
    )

    scope = review_edit_scope_for_turn(_review_command_conversation())
    assert scope is not None and scope.step_refs == frozenset({"existing_step_1"})
    assert (
        review_edit_scope_for_turn(
            _review_command_conversation(then_the_user_typed="Byt namn på flödet")
        )
        is None
    )


def _review_command_conversation(
    *, then_the_user_typed: str | None = None, step_orders: list[int] | None = None
):
    """A suggestion handoff, optionally followed by the user's own message."""
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        metadata_for_user_message,
    )
    from eneo.flows.ai_builder.ai_builder_flow_review import (
        AIBuilderSuggestionContext,
        FlowReviewSuggestionFocus,
        investigation_message,
    )

    context = AIBuilderSuggestionContext(
        flow_version=2,
        definition_checksum="sum",
        sample_run_ids=[uuid4()],
        suggestions=[
            FlowReviewSuggestionFocus(
                suggestion_kind="instruction_outcome_drift",
                step_orders=step_orders or [1],
            )
        ],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content=investigation_message(context.suggestions),
            metadata=metadata_for_user_message(
                review_context=context, review_evidence_level=1
            ),
        )
    ]
    if then_the_user_typed is not None:
        conversation.append(
            ConversationMessage(role="user", content=then_the_user_typed)
        )
    return conversation


@pytest.mark.asyncio
async def test_a_review_turn_may_not_change_a_step_the_findings_do_not_name():
    """The turn answers the findings the user picked, and nothing else.

    The same proposal is accepted when the user typed the request
    themselves: it is the handoff that bounds the edit, not the session.
    """

    flow = _flow(
        _flow_step(step_order=1, user_description="Sammanfatta"),
        _flow_step(step_order=2, user_description="Föreslå beslut"),
    )
    arguments = {
        "plan_rationale": "Steg 2 skrivs om.",
        "steps": [
            {"kind": "modify", "existing_step_ref": "existing_step_2", "name": "Nytt"},
        ],
    }

    refused = await _process(
        flow=flow,
        arguments=arguments,
        conversation=_review_command_conversation(),
    )
    assert isinstance(refused, CorrectableFailure)
    assert "existing_step_2" in refused.feedback

    # The user's own words are their own edit: the bound is gone.
    theirs = await _process(
        flow=flow,
        arguments=arguments,
        conversation=_review_command_conversation(
            then_the_user_typed="skriv om steg 2 också"
        ),
    )
    assert not isinstance(theirs, CorrectableFailure) or (
        "existing_step_2" not in theirs.feedback
    )


@pytest.mark.asyncio
async def test_a_review_turn_is_not_blamed_for_the_compilers_housekeeping():
    """The compiler repairs a persisted shape on every whole-flow edit.

    A transcription step ahead of a bare audio input is the compiler's doing,
    not the model reaching past the findings; held against it the bounded
    turn could never be admitted and the model could not undo it. The scope
    is held to the model's own changes, the kept steps stay as saved, and the
    plan the user approves still shows all of it.
    """
    flow = _audio_document_flow()
    conversation = _review_command_conversation()

    result = await _process(
        flow=flow,
        arguments=_admitted_by_the_review_schema(
            flow,
            conversation,
            steps=[
                _strict_review_modify(
                    "existing_step_1",
                    assistant_spec={
                        "instructions": "Fånga mötets syfte, deltagare och beslut.",
                        "knowledge_refs": None,
                    },
                ),
                {"kind": "keep", "existing_step_ref": "existing_step_2"},
                {"kind": "keep", "existing_step_ref": "existing_step_3"},
                {"kind": "keep", "existing_step_ref": "existing_step_4"},
            ],
        ),
        conversation=conversation,
    )

    assert isinstance(result, ProposalReady), getattr(result, "feedback", result)
    steps = result.compiled.content.spec.steps
    assert steps[0].existing_step_ref is None  # the compiler's transcription step
    assert steps[1].existing_step_ref == "existing_step_1"
    assert steps[1].assistant_spec.instructions == (
        "Fånga mötets syfte, deltagare och beslut."
    )
    edit = result.compiled.content.edit
    assert edit is not None
    by_kind = {
        kind: [
            c.step_ref or c.step_name for c in edit.diff.step_changes if c.kind == kind
        ]
        for kind in ("added", "modified", "unchanged")
    }
    assert by_kind["added"] == ["Transkribera ljud"]
    assert by_kind["modified"] == ["existing_step_1"]
    assert by_kind["unchanged"] == [
        "existing_step_2",
        "existing_step_3",
        "existing_step_4",
    ]


@pytest.mark.asyncio
async def test_a_review_turn_is_not_blamed_for_the_input_field_the_server_carries():
    """A confirmed runtime field from the session is projected onto every
    proposal before compilation. The bounded turn never wrote it, and the
    unchanged flow gets the same projection, so it is not the model's."""
    flow = _flow(
        _flow_step(step_order=1, user_description="Sammanfatta"),
        _flow_step(
            step_order=2,
            user_description="Föreslå beslut",
            input_source="previous_step",
        ),
    )
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="priority",
                label="Priority",
                field_type="select",
                required=True,
                options=["Low", "High"],
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-1",
        )
    ]
    conversation = _review_command_conversation()

    result = await _process(
        flow=flow,
        planning_state=state,
        arguments=_admitted_by_the_review_schema(
            flow,
            conversation,
            steps=[
                _strict_review_modify(
                    "existing_step_1",
                    assistant_spec={"instructions": "Kortare.", "knowledge_refs": None},
                ),
                {"kind": "keep", "existing_step_ref": "existing_step_2"},
            ],
        ),
        conversation=conversation,
    )

    assert isinstance(result, ProposalReady), getattr(result, "feedback", result)
    assert [f.name for f in result.compiled.content.spec.form_fields or []] == [
        "priority"
    ]


@pytest.mark.asyncio
async def test_a_review_turn_is_not_blamed_for_a_duplicate_name_preparation_suffixes():
    """Preparation gives duplicate step names their suffix after compilation.

    Two unselected steps share a name; the unchanged flow gets the same
    suffix, so the rename is the server's. The plan still shows it.
    """
    flow = _flow(
        _flow_step(step_order=1, user_description="Sammanfatta"),
        _flow_step(
            step_order=2, user_description="Sammanfatta", input_source="previous_step"
        ),
        _flow_step(
            step_order=3,
            user_description="Föreslå beslut",
            input_source="previous_step",
        ),
    )
    conversation = _review_command_conversation(step_orders=[3])

    result = await _process(
        flow=flow,
        arguments=_admitted_by_the_review_schema(
            flow,
            conversation,
            steps=[
                {"kind": "keep", "existing_step_ref": "existing_step_1"},
                {"kind": "keep", "existing_step_ref": "existing_step_2"},
                _strict_review_modify(
                    "existing_step_3",
                    assistant_spec={
                        "instructions": "Föreslå högst tre beslut.",
                        "knowledge_refs": None,
                    },
                ),
            ],
        ),
        conversation=conversation,
    )

    assert isinstance(result, ProposalReady), getattr(result, "feedback", result)
    names = [step.name for step in result.compiled.content.spec.steps]
    assert len(set(names)) == 3
    renamed = [
        c.step_ref
        for c in result.compiled.content.edit.diff.step_changes
        if any(f.field == "name" for f in c.field_changes)
    ]
    assert renamed and renamed != ["existing_step_3"]


@pytest.mark.asyncio
async def test_a_spilled_edit_payload_is_re_homed_and_then_told_what_it_still_lacks():
    """The captured non-strict shape, through admission and the real edit
    processor: the field objects that spilled out of step 3 are re-homed and
    the root null tail dropped, so the model is told the one thing it can act
    on (the steps it never emitted) instead of a schema error."""
    from eneo.flows.ai_builder.ai_builder_tools import admit_propose_flow_tool_arguments

    flow = _flow(
        _flow_step(step_order=1, user_description="Transkribera"),
        _flow_step(
            step_order=2, user_description="Fakta", input_source="previous_step"
        ),
        _flow_step(
            step_order=3, user_description="Analys", input_source="previous_step"
        ),
        _flow_step(
            step_order=4, user_description="Rapport", input_source="previous_step"
        ),
        _flow_step(step_order=5, user_description="PDF", input_source="previous_step"),
    )
    schema = build_edit_flow_tool_schema(
        list(flow.steps),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
    )
    captured_shape = {
        "plan_rationale": "Steg 3 fångar fler fält.",
        "steps": [
            {"kind": "keep", "existing_step_ref": "existing_step_1"},
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_2",
                "assistant_spec": {"instructions": "Sammanfatta fakta."},
            },
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_3",
                "output_type": "json",
                "output_fields": [
                    {"name": "motestyp", "field_type": "string", "description": "Typ."}
                ],
            },
            {"name": "risker", "field_type": "array", "description": "Risker."},
            {"name": "oppna_fragor", "field_type": "array", "description": "Öppna."},
        ],
        "review_mode": None,
        "document_delivery_mode": None,
    }

    admitted = admit_propose_flow_tool_arguments(
        arguments=captured_shape,
        tool_schema=schema,  # type: ignore[arg-type]
    )
    assert [f["name"] for f in admitted["steps"][2]["output_fields"]] == [
        "motestyp",
        "risker",
        "oppna_fragor",
    ]
    result = await _process(flow=flow, arguments=admitted)

    assert isinstance(result, CorrectableFailure)
    assert "existing_step_4" in result.feedback and "existing_step_5" in result.feedback


def _strict_review_modify(ref: str, **changes: object) -> dict[str, object]:
    """A modify item as a strict provider writes it: every property present."""
    return {
        "kind": "modify",
        "existing_step_ref": ref,
        "name": None,
        "assistant_spec": {"instructions": None, "knowledge_refs": None},
        "input_source": None,
        "input_type": None,
        "output_type": None,
        "document_delivery_mode": None,
        "uses_form_fields": None,
        "uses_previous_fields": None,
        "output_fields": None,
        "review_mode": None,
        **changes,
    }


def _admitted_by_the_review_schema(
    flow, conversation, *, steps: list[dict[str, object]]
) -> dict[str, object]:
    """The payload a strict provider may send for this handoff, admitted
    against the review-scoped schema before it is processed."""
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        review_edit_scope_for_turn,
    )

    schema = build_edit_flow_tool_schema(
        list(flow.steps),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        review_scope=review_edit_scope_for_turn(conversation),
    )
    strict = build_native_strict_tool_schema(schema)  # type: ignore[arg-type]
    parameters = strict["function"]["parameters"]
    arguments: dict[str, object] = {
        "plan_rationale": "Svar på granskningens fynd.",
        "assumptions": [],
        "steps": steps,
    }
    if "removed_existing_step_refs" in parameters["properties"]:
        arguments["removed_existing_step_refs"] = []
    jsonschema.validate(arguments, parameters)
    # What production admits is what is processed: the strict check above is
    # the provider's, this is the server's.
    return admit_propose_flow_tool_arguments(
        arguments=arguments,
        tool_schema=schema,  # type: ignore[arg-type]
    )


def test_the_models_own_changes_are_the_diff_net_of_the_housekeeping() -> None:
    from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
        FlowEditDiff,
        StepChange,
        StepFieldChange,
    )
    from eneo.flows.ai_builder.ai_builder_flow_review import (
        review_edit_changes_of_the_model,
    )

    housekeeping = FlowEditDiff(
        step_changes=[
            StepChange(kind="added", step_name="Transkribera ljud"),
            StepChange(
                kind="modified",
                step_name="Skapa PDF",
                step_ref="existing_step_4",
                field_changes=[
                    StepFieldChange(
                        field="output_mode",
                        previous="pass_through",
                        current="render_verbatim",
                    )
                ],
            ),
        ]
    )
    diff = FlowEditDiff(
        step_changes=[
            StepChange(kind="added", step_name="Transkribera ljud"),
            StepChange(
                kind="modified",
                step_name="Etablera",
                step_ref="existing_step_1",
                field_changes=[
                    StepFieldChange(field="instructions", previous=None, current="Ny.")
                ],
            ),
            StepChange(
                kind="modified",
                step_name="Skapa PDF",
                step_ref="existing_step_4",
                field_changes=[
                    StepFieldChange(
                        field="output_mode",
                        previous="pass_through",
                        current="render_verbatim",
                    ),
                    StepFieldChange(field="name", previous="Skapa PDF", current="PDF"),
                ],
            ),
        ]
    )

    own = review_edit_changes_of_the_model(diff, housekeeping=housekeeping)

    assert [(c.kind, c.step_ref) for c in own.step_changes] == [
        ("modified", "existing_step_1"),
        ("modified", "existing_step_4"),
    ]
    assert (own.net_steps_added, own.net_steps_removed) == (0, 0)
    # Only the rename is the model's; the output mode was the compiler's.
    assert [f.field for f in own.step_changes[1].field_changes] == ["name"]
    # A structured value reads the same in short but differs in full: the
    # model's, not the compiler's.
    contract_change = StepChange(
        kind="modified",
        step_name="Etablera",
        step_ref="existing_step_1",
        field_changes=[
            StepFieldChange(
                field="output_contract",
                current="2 fält",
                current_detail='{"properties":{"a":{},"b":{}}}',
            )
        ],
    )
    housekept_contract = contract_change.model_copy(
        update={
            "field_changes": [
                StepFieldChange(
                    field="output_contract",
                    current="2 fält",
                    current_detail='{"properties":{"a":{},"c":{}}}',
                )
            ]
        }
    )
    still_the_models = review_edit_changes_of_the_model(
        FlowEditDiff(step_changes=[contract_change]),
        housekeeping=FlowEditDiff(step_changes=[housekept_contract]),
    )
    assert still_the_models.step_changes[0].kind == "modified"
    # No baseline: nothing is exempt.
    assert review_edit_changes_of_the_model(diff, housekeeping=None) == diff
    # A step the compiler alone touched counts as unchanged.
    only_housekeeping = review_edit_changes_of_the_model(
        FlowEditDiff(step_changes=housekeeping.step_changes), housekeeping=housekeeping
    )
    assert [(c.kind, c.step_ref) for c in only_housekeeping.step_changes] == [
        ("unchanged", "existing_step_4")
    ]


@pytest.mark.asyncio
async def test_an_investigation_that_finds_nothing_to_change_ends_the_turn():
    """Finding nothing is a real answer, and the only honest one sometimes.

    Sending the model back to try again would loop: the repair call withdraws
    the decline tool and demands a plan, so a model that correctly concludes
    the runs do not support the suggestion could never finish.
    """
    from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import ProposalAnswer

    flow = _flow(
        _flow_step(step_order=1, user_description="Sammanfatta"),
        _flow_step(step_order=2, user_description="Föreslå beslut"),
    )

    result = await _process(
        flow=flow,
        arguments={
            "plan_rationale": "Stegen gör olika saker; ingen ändring behövs.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
        conversation=_review_command_conversation(),
    )

    assert isinstance(result, ProposalAnswer)
    assert "hittar inget" in result.answer


@pytest.mark.asyncio
async def test_edit_compiles_against_the_flows_own_template_binding() -> None:
    template_asset_id = uuid4()
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Sammanfatta mötet",
            input_type="document",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Fyll i mötesrapportmallen",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(template_asset_id),
                "template_name": "motesrapport.docx",
                "placeholders": ["föregående_steg", "datum"],
                "bindings": {
                    "föregående_steg": "{{ föregående_steg }}",
                    "datum": "{{ datum }}",
                },
            },
        ),
    )
    planning_state = PlanningState.empty()
    planning_state.inherited_template = InheritedTemplateBinding(
        template_asset_id=template_asset_id,
        placeholders=["föregående_steg", "datum"],
    )

    result = await _process(
        flow=flow,
        planning_state=planning_state,
        arguments={
            "plan_rationale": "Förtydliga sammanfattningssteget, mallen är oförändrad.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Skriv mötesanteckningar",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady), result
    terminal = result.compiled.content.spec.steps[-1]
    assert terminal.output_mode is OutputMode.TEMPLATE_FILL
    assert terminal.output_config == {
        "template_asset_id": str(template_asset_id),
        "bindings": {
            "föregående_steg": "{{ föregående_steg }}",
            "datum": "{{ datum }}",
        },
    }


def _bound_template_flow(
    *,
    template_asset_id,
    bindings: dict[str, str],
) -> SimpleNamespace:
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Läs underlaget",
            input_type="document",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Skriv rapporten",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=3,
            user_description="Fyll i mallen",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(template_asset_id),
                "bindings": bindings,
            },
        ),
    )


def _inherited_planning_state(
    template_asset_id, placeholders: list[str]
) -> PlanningState:
    state = PlanningState.empty()
    state.inherited_template = InheritedTemplateBinding(
        template_asset_id=template_asset_id,
        placeholders=placeholders,
    )
    return state


@pytest.mark.asyncio
async def test_edit_keeps_the_flows_template_mappings_when_an_earlier_step_changes() -> (
    None
):
    # "rapport" is not a derivable name: re-deriving it would bind a new Flow
    # input field instead of the previous step's text the flow already maps.
    template_asset_id = uuid4()
    bindings = {
        "rapport": "{{ föregående_steg }}",
        "underlag": "{{ step_1.output.text }}",
        "datum": "{{ datum }}",
        "kommentar": "",
    }
    result = await _process(
        flow=_bound_template_flow(
            template_asset_id=template_asset_id, bindings=bindings
        ),
        planning_state=_inherited_planning_state(
            template_asset_id, ["rapport", "underlag", "datum", "kommentar"]
        ),
        arguments={
            "plan_rationale": "Byter bara namn på första steget.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Läs ärendet",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
        },
    )

    assert isinstance(result, ProposalReady), result
    spec = result.compiled.content.spec
    terminal = spec.steps[-1]
    assert terminal.output_config == {
        "template_asset_id": str(template_asset_id),
        "bindings": {
            "rapport": "{{ föregående_steg }}",
            # A step alias moves with the step it names.
            "underlag": "{{ " + spec.steps[0].plan_step_ref + ".output.text }}",
            "datum": "{{ datum }}",
            "kommentar": "",
        },
    }
    assert not spec.form_fields


@pytest.mark.asyncio
async def test_edit_reports_a_template_mapping_whose_step_was_removed() -> None:
    template_asset_id = uuid4()
    result = await _process(
        flow=_bound_template_flow(
            template_asset_id=template_asset_id,
            bindings={"rapport": "{{ step_2.output.text }}"},
        ),
        planning_state=_inherited_planning_state(template_asset_id, ["rapport"]),
        arguments={
            "plan_rationale": "Tar bort rapportsteget.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
            "removed_existing_step_refs": ["existing_step_2"],
        },
    )

    assert isinstance(result, CorrectableFailure), result
    assert "template_binding_dependency_broken" in result.codes
    assert "rapport" in result.feedback


@pytest.mark.asyncio
async def test_edit_binds_the_flows_template_to_a_moved_terminal_step() -> None:
    # The original terminal goes; its predecessor becomes the template-fill
    # step. The flow's asset must land on that step or publication fails.
    template_asset_id = uuid4()
    result = await _process(
        flow=_bound_template_flow(
            template_asset_id=template_asset_id,
            bindings={"rapport": "{{ föregående_steg }}"},
        ),
        planning_state=_inherited_planning_state(template_asset_id, ["rapport"]),
        arguments={
            "plan_rationale": "Fyller i mallen direkt från rapportsteget.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "output_type": "docx",
                    "document_delivery_mode": "template_fill",
                },
            ],
            "removed_existing_step_refs": ["existing_step_3"],
        },
    )

    assert isinstance(result, ProposalReady), result
    spec = result.compiled.content.spec
    terminal = spec.steps[-1]
    assert terminal.output_mode is OutputMode.TEMPLATE_FILL
    assert terminal.output_config is not None
    assert terminal.output_config["template_asset_id"] == str(template_asset_id)
    assert terminal.output_config["bindings"] == {"rapport": "{{ föregående_steg }}"}


@pytest.mark.asyncio
async def test_edit_reports_a_removed_producer_instead_of_rebinding_by_position() -> (
    None
):
    # Removing step 2 leaves a text-producing step 3 at position 2 in the new
    # plan; the persisted "step_2" alias names the removed producer, never
    # whatever now sits at that position.
    template_asset_id = uuid4()
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Läs underlaget",
            input_type="document",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Skriv rapporten",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=3,
            user_description="Skriv sammanfattningen",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=4,
            user_description="Fyll i mallen",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(template_asset_id),
                "bindings": {"rapport": "{{ step_2.output.text }}"},
            },
        ),
    )

    result = await _process(
        flow=flow,
        planning_state=_inherited_planning_state(template_asset_id, ["rapport"]),
        arguments={
            "plan_rationale": "Tar bort rapportsteget.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
                {"kind": "modify", "existing_step_ref": "existing_step_4"},
            ],
            "removed_existing_step_refs": ["existing_step_2"],
        },
    )

    assert isinstance(result, CorrectableFailure), result
    assert "template_binding_dependency_broken" in result.codes
    assert "rapport" in result.feedback


@pytest.mark.asyncio
async def test_edit_keeps_every_mapping_publication_accepts() -> None:
    # A bare Flow input field, a step's status and its error message are all
    # valid published mappings the Builder would never derive itself.
    template_asset_id = uuid4()
    bindings = {
        "diarienummer": "{{ diarienummer }}",
        "status": "{{ step_1.status }}",
        "fel": "{{ step_1.error_message }}",
    }
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Läs underlaget",
            input_type="document",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Fyll i mallen",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(template_asset_id),
                "bindings": bindings,
            },
        ),
        metadata_json=_form_metadata(
            {
                "name": "diarienummer",
                "type": "text",
                "label": "Diarienummer",
                "required": True,
            }
        ),
    )

    result = await _process(
        flow=flow,
        planning_state=_inherited_planning_state(
            template_asset_id, ["diarienummer", "status", "fel"]
        ),
        arguments={
            "plan_rationale": "Byter bara namn på första steget.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "name": "Läs ärendet",
                },
                {"kind": "modify", "existing_step_ref": "existing_step_2"},
            ],
        },
    )

    assert isinstance(result, ProposalReady), result
    spec = result.compiled.content.spec
    reader_ref = spec.steps[0].plan_step_ref
    assert spec.steps[-1].output_config == {
        "template_asset_id": str(template_asset_id),
        "bindings": {
            "diarienummer": "{{ diarienummer }}",
            "status": "{{ " + reader_ref + ".status }}",
            "fel": "{{ " + reader_ref + ".error_message }}",
        },
    }
    assert [field.name for field in spec.form_fields or ()] == ["diarienummer"]


def _four_step_bound_flow(template_asset_id) -> SimpleNamespace:
    return _flow(
        _flow_step(
            step_order=1,
            user_description="Läs underlaget",
            input_type="document",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Skriv rapporten",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=3,
            user_description="Skriv sammanfattningen",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        _flow_step(
            step_order=4,
            user_description="Fyll i mallen",
            input_source="previous_step",
            input_type="text",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(template_asset_id),
                "bindings": {
                    "rapport": "{{ step_2.output.text }}",
                    "datum": "{{ datum }}",
                },
            },
        ),
    )


@pytest.mark.asyncio
async def test_edit_removing_the_template_step_ignores_its_old_mappings() -> None:
    # No template step remains, so no mapping is retained: the removed
    # producer of "rapport" is not a dependency of anything.
    template_asset_id = uuid4()
    result = await _process(
        flow=_four_step_bound_flow(template_asset_id),
        planning_state=_inherited_planning_state(
            template_asset_id, ["rapport", "datum"]
        ),
        arguments={
            "plan_rationale": "Tar bort rapportsteget och mallsteget.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
            ],
            "removed_existing_step_refs": ["existing_step_2", "existing_step_4"],
        },
    )

    assert isinstance(result, ProposalReady), result
    assert (
        result.compiled.content.spec.steps[-1].output_mode
        is not OutputMode.TEMPLATE_FILL
    )


@pytest.mark.asyncio
async def test_edit_ignores_an_old_mapping_the_replacement_template_no_longer_has() -> (
    None
):
    # The replacement template only has "datum"; the old "rapport" mapping
    # is not retained, so its removed producer is no dependency.
    template_asset_id = uuid4()
    planning_state = _inherited_planning_state(template_asset_id, ["rapport", "datum"])
    planning_state.file_roles = [
        FileRoleEvidence(
            file_id=uuid4(),
            filename="ny-mall.docx",
            file_type="document",
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="high",
            template_placeholders=["datum"],
        )
    ]
    result = await _process(
        flow=_four_step_bound_flow(template_asset_id),
        planning_state=planning_state,
        arguments={
            "plan_rationale": "Byter mall och tar bort rapportsteget.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_1"},
                {"kind": "modify", "existing_step_ref": "existing_step_3"},
                {"kind": "modify", "existing_step_ref": "existing_step_4"},
            ],
            "removed_existing_step_refs": ["existing_step_2"],
        },
    )

    assert isinstance(result, ProposalReady), result
    terminal = result.compiled.content.spec.steps[-1]
    assert terminal.output_mode is OutputMode.TEMPLATE_FILL
    assert terminal.output_config == {"bindings": {"datum": "{{ datum }}"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_null", [False, True])
@pytest.mark.parametrize("concurrent_save", [None, "content", "reorder"])
@pytest.mark.parametrize("ui_language", ["sv", "en"])
async def test_saved_step_partial_revision_requires_current_saved_revision(
    keep_null,
    concurrent_save,
    ui_language,
    monkeypatch,
    send_lock_release,
) -> None:
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Analyze source",
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2, user_description="Review result", input_source="previous_step"
        ),
        _flow_step(
            step_order=3,
            user_description="Deliver result",
            input_source="previous_step",
        ),
    )
    flow.id = uuid4()
    session = BuilderSession(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        target_kind=TargetKind.EDIT,
        flow_id=flow.id,
    )
    snapshots = {
        flow.steps[0].assistant_id: AssistantAuthoringSnapshot(
            instructions="Saved instructions"
        )
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context, _ = await resolve_plan_edit_context(
        repo=SimpleNamespace(),
        tenant_id=session.tenant_id,
        session=session,
        flow=flow,
        context=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    first = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Improve the selected step.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {"instructions": "Improved instructions"},
                },
            ],
        },
    )
    assert isinstance(first, ProposalReady), first
    plan = BuilderPlan(
        id=uuid4(),
        session_id=session.id,
        tenant_id=session.tenant_id,
        proposal=FlowBuilderProposal(content=first.compiled.content),
    )
    assert plan.proposal.content.edit is not None
    assert plan.proposal.content.edit.base_flow_revision == 7
    session.latest_plan_id = plan.id
    if concurrent_save:
        from eneo.flows.ai_builder.ai_builder_domain_models import SessionStatus
        from tests.unittests.flows.ai_builder.test_ai_builder_planner import (
            _budget_policy,
            _make_planner,
            _route,
        )

        flow.draft_revision = 8
        if concurrent_save == "reorder":
            flow.steps[0].step_order, flow.steps[1].step_order = 2, 1
            flow.steps.sort(key=lambda step: step.step_order)
            assert flow.steps[0].user_description == "Review result"
        else:
            flow.steps[1].user_description = "New saved review"
        saved_steps = [step.model_dump(mode="json") for step in flow.steps]
        retained_proposal = plan.model_dump(mode="json")
        planner = _make_planner()
        planner.user.tenant_id = session.tenant_id
        planner.repo.get_session.return_value = session
        planner.repo.get_plan.return_value = plan
        planner.repo.load_planning_state.return_value = PlanningState.empty()
        session.status = SessionStatus.AWAITING_APPROVAL
        prepare = AsyncMock(
            side_effect=AssertionError("Stale revision reached request preparation")
        )
        monkeypatch.setattr(
            "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request", prepare
        )
        expected = (
            "Flödet har ändrats sedan det här förslaget skapades. Välj steget igen i det aktuella flödet för att fortsätta."
            if ui_language == "sv"
            else "The flow has changed since this proposal was created. Select the step again in the current flow to continue."
        )
        for _ in range(2):
            client_turn_id = uuid4()
            events = [
                event
                async for event in planner.send_message(
                    session_id=session.id,
                    client_turn_id=client_turn_id,
                    request_fingerprint="a" * 64,
                    request_snapshot={
                        "client_turn_id": str(client_turn_id),
                        "message": "Improve the output fields",
                    },
                    message="Improve the output fields",
                    edit_context=AIBuilderPlanEditContext(
                        scope="step", plan_id=plan.id, target_plan_step_ref="step_a"
                    ),
                    ui_language=ui_language,
                    completion_model_route=_route(),
                    flow=flow,
                    assistant_snapshots=snapshots,
                    capacity=ModelCapacity(100_000, 4096),
                    budget_policy=_budget_policy(),
                )
            ]
            assert [event.data.text for event in events if event.event == "text"] == [
                expected
            ]
            assert events[-1].event == "done"
        prepare.assert_not_awaited()
        assert planner.litellm_client.mock_calls == []
        assert (
            planner.repo.restore_awaiting_approval_after_answered_turn.await_count == 2
        )
        assert planner.repo.complete_session_turn.await_count == 2
        assert len(send_lock_release.released_leases) == 2
        committed = planner.repo.commit_turn.await_args.kwargs["new_messages"]
        assert committed[-1].content == expected
        assert committed[-1].tool_calls is None
        assert session.latest_plan_id == plan.id
        assert plan.model_dump(mode="json") == retained_proposal
        assert [step.model_dump(mode="json") for step in flow.steps] == saved_steps
        return
    context, prior_plan = await resolve_plan_edit_context(
        repo=SimpleNamespace(get_plan=AsyncMock(return_value=plan)),
        tenant_id=session.tenant_id,
        session=session,
        flow=flow,
        context=AIBuilderPlanEditContext(
            scope="step", plan_id=plan.id, target_plan_step_ref="step_a"
        ),
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=prior_plan,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    patch_fields = {"assistant_spec": None} if keep_null else {}
    second = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Improve the selected step.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Grounded summary",
                        }
                    ],
                    **patch_fields,
                },
            ],
        },
    )
    assert isinstance(second, ProposalReady), second
    assert (
        second.compiled.content.spec.steps[1:] == first.compiled.content.spec.steps[1:]
    )
    assert (
        second.compiled.content.spec.steps[0].assistant_spec.instructions
        == "Improved instructions"
    )
    assert second.compiled.content.spec.steps[0].output_contract is not None
    assert second.compiled.content.edit is not None
    assert second.compiled.content.edit.base_flow_revision == 7
    changes = second.compiled.content.edit.diff.step_changes[0].model_dump(mode="json")
    assert "instructions" in str(changes)
    assert "output_contract" in str(changes)


@pytest.mark.asyncio
async def test_saved_step_preserves_consumer_with_numeric_runtime_aliases() -> None:
    contract = {"type": "object", "properties": {"summary": {"type": "string"}}}
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Analyze",
            output_type="json",
            output_contract=contract,
        ),
        _flow_step(
            step_order=2,
            user_description="Write",
            input_source="previous_step",
            input_bindings={
                "source_refs": [
                    {
                        "step_ref": "step_1",
                        "output": "structured",
                        "field_path": "summary",
                    }
                ]
            },
        ),
    )
    snapshots = {
        flow.steps[0].assistant_id: AssistantAuthoringSnapshot(
            instructions="Saved analysis"
        ),
        flow.steps[1].assistant_id: AssistantAuthoringSnapshot(
            instructions="Write {{ step_1.output.structured.summary }}"
        ),
    }
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Clarify analysis.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {"instructions": "Improved analysis"},
                },
            ],
        },
    )
    assert isinstance(result, ProposalReady), result
    consumer = result.compiled.content.spec.steps[1]
    assert (
        consumer.assistant_spec.instructions
        == "Write {{ step_a.output.structured.summary }}"
    )
    assert consumer.input_bindings == {
        "source_refs": [
            {"step_ref": "step_a", "output": "structured", "field_path": "summary"}
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authored",
    [
        {"flow_name": "Changed flow"},
        {"flow_description": "Changed description"},
        {"form_fields": []},
    ],
)
async def test_saved_step_authored_effect_policy_rejects_flow_fields(authored):
    flow = _flow(_flow_step(step_order=1, user_description="Analyze"))
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=None,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=None, available_kbs=None
        ),
    )
    result = await _process(
        flow=flow,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Improve instructions.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {"instructions": "Improved instructions"},
                }
            ],
            **authored,
        },
    )
    assert isinstance(result, CorrectableFailure), result
    assert "flow" in result.feedback.lower()


def _saved_step_consumer_fixture(consumer_kind):
    contract = {
        "type": "object",
        "properties": {
            "report": {"type": "object", "properties": {"summary": {"type": "string"}}},
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        },
    }
    consumer = _flow_step(
        step_order=2,
        user_description="Use result",
        input_source="previous_step",
        input_bindings={"question": "Independent input"},
    )
    consumer_instructions = "Keep these consumer instructions"
    if consumer_kind == "implicit":
        contract = {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        }
        consumer.input_type = "json"
        consumer.input_bindings = None
        consumer.input_contract = contract
    elif consumer_kind == "projection":
        consumer.input_type = "json"
        consumer.input_bindings = {
            "source_refs": [
                {
                    "step_ref": "step_1",
                    "output": "structured",
                    "field_path": "report.summary",
                }
            ]
        }
        consumer.input_contract = derive_structured_projection_contract(
            input_bindings=consumer.input_bindings,
            source_contracts_by_step_ref={"step_1": contract},
        )
    elif consumer_kind == "array":
        consumer.output_mode = FlowOutputMode.COMPOSE_TEXT
        consumer.input_bindings = {
            "source_refs": [
                {
                    "step_ref": "step_1",
                    "output": "structured",
                    "field_path": "items",
                    "item_template": "{name}",
                }
            ]
        }
    elif consumer_kind == "whole":
        consumer.input_bindings = {"question": "Use {{ step_1.output.structured }}"}
    elif consumer_kind == "instructions":
        consumer_instructions += " {{ step_1.output.structured.report.summary }}"
    elif consumer_kind == "template":
        consumer = _flow_step(
            step_order=2,
            user_description="Fill template",
            input_source="previous_step",
            output_mode="template_fill",
            output_type="docx",
            input_bindings={"question": "Independent input"},
            output_config={
                "template_asset_id": str(uuid4()),
                "bindings": {
                    "SUMMARY": "{{ step_1.output.structured.report.summary }}"
                },
            },
        )
    else:
        consumer.output_config = {
            "nested": {"text": "{{ step_1.output.structured.report.summary }}"}
        }
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Analyze",
            output_type="json",
            output_contract=contract,
        ),
        consumer,
    )
    snapshots = {
        flow.steps[0].assistant_id: AssistantAuthoringSnapshot(
            instructions="Analyze the source"
        ),
        consumer.assistant_id: AssistantAuthoringSnapshot(
            instructions=consumer_instructions
        ),
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    return flow, snapshots, catalog, context, prior


@pytest.mark.asyncio
async def test_saved_terminal_step_can_replace_nested_contract_without_consumers():
    flow, snapshots, catalog, context, prior = _saved_step_consumer_fixture(
        "projection"
    )
    assert prior is not None
    flow.steps = flow.steps[:1]
    prior = prior.model_copy(update={"steps": prior.steps[:1]})
    before = prior.model_dump(mode="json")
    assert context.preserve_output_contract is False

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Return the summary directly.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Result summary",
                            "required": True,
                        }
                    ],
                }
            ],
        },
    )

    assert isinstance(result, ProposalReady), result
    contract = result.compiled.content.spec.steps[0].output_contract
    assert contract is not None
    assert contract["properties"] == {
        "summary": {
            "type": "string",
            "title": "Summary",
            "description": "Result summary",
        }
    }
    assert contract["required"] == ["summary"]
    assert prior.model_dump(mode="json") == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("consumer_kind", "target_patch", "feedback_fragment"),
    [
        (
            "projection",
            {
                "output_fields": [
                    {
                        "name": "unrelated",
                        "field_type": "string",
                        "description": "Result field",
                    }
                ]
            },
            "report.summary",
        ),
        (
            "projection",
            {
                "output_fields": [
                    {
                        "name": "report",
                        "field_type": "object",
                        "description": "Result field",
                        "children": [
                            {
                                "name": "summary",
                                "field_type": "number",
                                "description": "Result field",
                            }
                        ],
                    }
                ]
            },
            "contract",
        ),
        (
            "array",
            {
                "output_fields": [
                    {
                        "name": "items",
                        "field_type": "array",
                        "description": "Result field",
                    }
                ]
            },
            "object",
        ),
        (
            "array",
            {
                "output_fields": [
                    {
                        "name": "items",
                        "field_type": "array",
                        "description": "Result field",
                        "children": [
                            {
                                "name": "other",
                                "field_type": "string",
                                "description": "Result field",
                            }
                        ],
                    }
                ]
            },
            "name",
        ),
        ("whole", {"output_type": "text", "output_fields": []}, "structured"),
        ("whole", {"output_fields": []}, "contract"),
        ("instructions", {"output_fields": []}, "contract"),
        (
            "instructions",
            {
                "output_fields": [
                    {
                        "name": "unrelated",
                        "field_type": "string",
                        "description": "Result field",
                    }
                ]
            },
            "report",
        ),
        (
            "output_config",
            {
                "output_fields": [
                    {
                        "name": "unrelated",
                        "field_type": "string",
                        "description": "Result field",
                    }
                ]
            },
            "report",
        ),
    ],
)
async def test_saved_step_incompatible_consumer_returns_repair(
    consumer_kind, target_patch, feedback_fragment
):
    from eneo.flows.ai_builder.ai_builder_proposal_retry import repair_feedback
    from eneo.flows.ai_builder.ai_builder_validator import validate_spec

    flow, snapshots, catalog, context, prior = _saved_step_consumer_fixture(
        consumer_kind
    )
    assert prior is not None
    baseline_validation = validate_spec(prior)
    assert baseline_validation.valid, baseline_validation.errors
    before = prior.steps[1].model_dump(mode="json")
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Revise the result schema.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    **target_patch,
                },
            ],
        },
    )
    assert isinstance(result, CorrectableFailure), result
    assert result.kind != "parse", result
    assert feedback_fragment in repair_feedback(result).lower(), result
    assert prior.steps[1].model_dump(mode="json") == before


@pytest.mark.parametrize("consumer_kind", ["instructions", "output_config"])
def test_reference_validator_skips_missing_contract_for_prose_only_consumer(
    consumer_kind,
):
    from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
    from eneo.flows.ai_builder.ai_builder_validation_references import (
        validate_variable_references,
    )

    _, _, _, _, prior = _saved_step_consumer_fixture(consumer_kind)
    assert prior is not None
    missing = prior.model_copy(
        update={
            "steps": [
                prior.steps[0].model_copy(update={"output_contract": None}),
                prior.steps[1],
            ]
        }
    )
    result = SpecValidationResult()
    validate_variable_references(missing, result)
    assert result.valid, result.errors


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_contract", [False, True])
async def test_saved_step_preserves_contract_used_by_template_bindings(remove_contract):
    from eneo.flows.ai_builder.ai_builder_validator import validate_spec

    flow, snapshots, catalog, context, prior = _saved_step_consumer_fixture("template")
    assert prior is not None
    baseline_validation = validate_spec(prior)
    assert baseline_validation.valid, baseline_validation.errors
    target_patch = (
        {"output_fields": []}
        if remove_contract
        else {
            "assistant_spec": {"instructions": "Improved analysis"},
        }
    )
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Remove the schema.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    **target_patch,
                },
            ],
        },
    )
    if remove_contract:
        assert isinstance(result, CorrectableFailure), result
        assert "consumer_requires_output_contract" in result.codes
        assert "step_b" in result.feedback
    else:
        assert isinstance(result, ProposalReady), result
        assert (
            result.compiled.content.spec.steps[1].output_mode
            == OutputMode.TEMPLATE_FILL
        )
        assert (
            result.compiled.content.spec.steps[1].output_config
            == prior.steps[1].output_config
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [False, True])
async def test_untouched_composer_step_keeps_its_mode(scoped):
    """A step the model did not touch keeps its saved output_mode.

    compose_text is never derivable from the step's types, so rederiving it
    for an identity-only entry retyped the step to pass_through: a scoped
    edit was then refused for changing an unrelated step (eneo-qmo) and a
    whole-flow edit showed a mode change the user never asked for (eneo-380).
    """

    flow, snapshots, catalog, context, _ = _saved_step_consumer_fixture("array")
    flow.steps[1].input_bindings = {
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "report.summary",
            }
        ]
    }
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None
    assert prior.steps[1].output_mode == OutputMode.COMPOSE_TEXT
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context if scoped else None,
        prior_spec_for_revision=prior if scoped else None,
        arguments={
            "plan_rationale": "Clarify analysis.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {"instructions": "Improved analysis"},
                },
                *(
                    []
                    if scoped
                    else [{"kind": "keep", "existing_step_ref": "existing_step_2"}]
                ),
            ],
        },
    )
    assert isinstance(result, ProposalReady), result
    compiled = result.compiled.content.spec
    assert compiled.steps[1].output_mode == OutputMode.COMPOSE_TEXT
    assert compiled.steps[0].assistant_spec.instructions == "Improved analysis"
    assert result.compiled.content.edit is not None
    assert not [
        field
        for change in result.compiled.content.edit.diff.step_changes
        for field in change.field_changes
        if field.field == "output_mode"
    ]


def _pdf_body_saved_flow():
    """The live eneo-qmo flow shape: step 3 writes the document step 4 renders."""

    contract = {
        "type": "object",
        "required": ["documents"],
        "properties": {"documents": {"type": "array", "items": {"type": "string"}}},
    }
    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Extrahera källfält",
            input_source="flow_input",
            input_type="document",
            output_type="json",
            output_contract=contract,
        ),
        _flow_step(
            step_order=2,
            user_description="Bedöm ansökan mot reglerna",
            input_source="previous_step",
            input_type="json",
            input_contract=contract,
            output_type="json",
            output_contract=contract,
        ),
        _flow_step(
            step_order=3,
            user_description="Skriv beslutsdokument",
            input_source="previous_step",
            input_bindings={
                "source_refs": [
                    {
                        "label": "documents",
                        "output": "structured",
                        "step_ref": "step_1",
                        "field_path": "documents",
                    }
                ]
            },
        ),
        _flow_step(
            step_order=4,
            user_description="Rendera PDF",
            input_source="previous_step",
            output_mode="render_verbatim",
            output_type="pdf",
        ),
    )
    snapshots = {
        step.assistant_id: AssistantAuthoringSnapshot(
            instructions=(
                "Skriv det kompletta beslutsdokumentet som ska renderas till PDF."
                if step.step_order == 3
                else f"Saved instructions {step.step_order}."
            )
        )
        for step in flow.steps
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    return flow, snapshots, catalog


@pytest.mark.asyncio
async def test_saved_step_edit_leaves_the_untouched_pdf_body_step_byte_identical():
    """The live eneo-qmo shape: editing step 1 of a flow whose step 3 writes the
    document a PDF step renders.

    Spec normalisation renames such a step ("Förbered PDF-innehåll") and prefixes
    its instructions; on a saved flow that carries the undecorated step, the
    scoped guard then saw an unrelated step change on every repair round. A step
    the model did not touch must come out exactly as saved.
    """

    flow, snapshots, catalog = _pdf_body_saved_flow()
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None
    saved_untouched = [
        canonical_json_bytes(step.model_dump(mode="json", exclude={"plan_step_ref"}))
        for step in prior.steps[1:]
    ]

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Lista saknade uppgifter.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "assistant_spec": {
                        "instructions": "Lista alltid vilka uppgifter som saknas."
                    },
                }
            ],
        },
    )

    assert isinstance(result, ProposalReady), result
    compiled = result.compiled.content.spec
    assert compiled.steps[2].name == "Skriv beslutsdokument"
    assert [
        canonical_json_bytes(step.model_dump(mode="json", exclude={"plan_step_ref"}))
        for step in compiled.steps[1:]
    ] == saved_untouched


def _two_step_saved_flow_with_context():
    flow = _flow(
        _flow_step(step_order=1, user_description="Sammanfatta"),
        _flow_step(
            step_order=2,
            user_description="Granska",
            input_source="previous_step",
        ),
    )
    snapshots = {
        step.assistant_id: AssistantAuthoringSnapshot(
            instructions=f"Saved instructions {step.step_order}."
        )
        for step in flow.steps
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None
    return flow, snapshots, catalog, context, prior


_TARGET_ONLY_FRAGMENT = {
    "plan_rationale": "Förtydliga.",
    "steps": [
        {
            "kind": "modify",
            "existing_step_ref": "existing_step_1",
            "assistant_spec": {"instructions": "Sammanfatta i tre punkter."},
        }
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("unrelated_compiled_step_changed", TerminalFailure),
        ("step_sequence_changed", TerminalFailure),
        ("runtime_form_fields_changed", TerminalFailure),
        ("flow_metadata_changed", TerminalFailure),
        ("target_step_unchanged", CorrectableFailure),
        ("target_step_model_changed", CorrectableFailure),
    ],
)
async def test_saved_step_drift_outside_the_selected_step_is_a_server_defect(
    monkeypatch: pytest.MonkeyPatch, reason: str, outcome: type
):
    """Admission refuses every model-authored change outside the selected
    step, so a preserved-step, sequence, form-field or metadata rejection of
    a saved-step revision can only be the server's own drift: it ends the
    turn as a typed server defect instead of asking the model to repair what
    it never wrote. Target-step rejections stay repair feedback.
    """

    flow, snapshots, catalog, context, prior = _two_step_saved_flow_with_context()
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_edit_proposal.validate_scoped_plan_revision",
        lambda **_kwargs: ScopedRevisionRejection(reason, f"rejected: {reason}"),
    )

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments=_TARGET_ONLY_FRAGMENT,
    )

    assert isinstance(result, outcome), result
    if isinstance(result, TerminalFailure):
        assert result.code == AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED
        assert result.details["failure_code"] == "scoped_edit_preservation_failed"
        assert result.details["reason"] == reason
        assert result.details["architecture_repair_disposition"] == "server_defect"
    else:
        assert result.feedback == f"rejected: {reason}"


@pytest.mark.asyncio
async def test_saved_step_revision_leaves_a_bad_leading_audio_step_as_saved():
    """The whole-flow audio repair inserts a transcription step ahead of a
    saved audio step that emits structured output. A saved-step revision keeps
    the saved sequence, so the repair does not run and the saved flow's chain
    error reaches the model as ordinary validation feedback."""

    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Analysera samtalet",
            input_source="flow_input",
            input_type="audio",
            output_type="json",
            output_contract={
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _flow_step(
            step_order=2,
            user_description="Skriv rapport",
            input_source="previous_step",
            input_type="json",
        ),
        _flow_step(
            step_order=3,
            user_description="Rendera PDF",
            input_source="previous_step",
            output_mode="render_verbatim",
            output_type="pdf",
        ),
    )
    snapshots = {
        step.assistant_id: AssistantAuthoringSnapshot(
            instructions=f"Saved instructions {step.step_order}."
        )
        for step in flow.steps
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[1].id),
        scope="step",
        target_existing_step_ref="existing_step_2",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Kortare rapport.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_2",
                    "assistant_spec": {"instructions": "Skriv en kort rapport."},
                }
            ],
        },
    )

    # The saved flow's own chain error is repair feedback through the bounded
    # loop, not a transcription step the fragment never asked for.
    assert isinstance(result, CorrectableFailure), result
    assert result.kind == "validation"
    assert "audio_document_transcript_chain_invalid" in result.codes
    assert "Transkribera" not in result.feedback


@pytest.mark.asyncio
async def test_saved_step_identity_only_target_is_refused_before_normalization():
    """Selecting the undecorated PDF-body step and submitting only its identity
    must not compile: the artifact normalizer would rename and prefix it and
    the plan would present the server's decoration as the model's edit."""

    flow, snapshots, catalog = _pdf_body_saved_flow()
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[2].id),
        scope="step",
        target_existing_step_ref="existing_step_3",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Inget att ändra.",
            "steps": [{"kind": "modify", "existing_step_ref": "existing_step_3"}],
        },
    )

    assert isinstance(result, CorrectableFailure), result
    assert "submitted without changes" in result.feedback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "echo",
    [
        {"name": "Skriv beslutsdokument"},
        {
            "assistant_spec": {
                "instructions": (
                    "Skriv det kompletta beslutsdokumentet som ska renderas till PDF."
                )
            }
        },
    ],
    ids=["same_name", "same_instructions"],
)
async def test_saved_step_target_echoing_its_saved_value_is_not_a_change(echo):
    """A field the model sends with the saved value is presence, not
    authorship. The compiler protects the target when its compiled form equals
    the saved one, so the artifact normalizer cannot rename and prefix it into
    an approvable edit; the guard then reports the target unchanged."""

    flow, snapshots, catalog = _pdf_body_saved_flow()
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[2].id),
        scope="step",
        target_existing_step_ref="existing_step_3",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None

    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Samma som förut.",
            "steps": [
                {"kind": "modify", "existing_step_ref": "existing_step_3", **echo}
            ],
        },
    )

    assert isinstance(result, CorrectableFailure), result
    assert "was unchanged" in result.feedback
    assert "Förbered" not in result.feedback


@pytest.mark.asyncio
async def test_saved_step_fragment_keeps_an_untouched_speaker_mapping_step():
    """speaker_mapping is the other persisted mode no derivation produces.

    The Builder never proposes it, but edits must carry it through: the
    fragment expansion fills the untouched transcription and speaker-mapping
    steps in with their saved modes.
    """

    flow = _flow(
        _flow_step(
            step_order=1,
            user_description="Transkribera",
            input_source="flow_input",
            input_type="audio",
            output_mode="transcribe_only",
            output_type="text",
        ),
        _flow_step(
            step_order=2,
            user_description="Namnge talare",
            input_source="previous_step",
            output_mode="speaker_mapping",
            output_type="json",
            output_config={
                "speaker_mapping": {
                    "participants_field": "deltagare",
                    "infer_names": True,
                }
            },
        ).model_copy(
            update={"review_policy": FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)}
        ),
        _flow_step(
            step_order=3,
            user_description="Sammanfatta",
            input_source="previous_step",
            input_type="json",
        ),
    )
    snapshots = {
        step.assistant_id: AssistantAuthoringSnapshot(
            instructions=f"Saved instructions {step.step_order}."
        )
        for step in flow.steps
    }
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None
    )
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[2].id),
        scope="step",
        target_existing_step_ref="existing_step_3",
    )
    prior = _prior_spec_for_revision(
        context=context,
        prior_plan=None,
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
    )
    assert prior is not None
    assert [step.output_mode for step in prior.steps] == [
        OutputMode.TRANSCRIBE_ONLY,
        OutputMode.SPEAKER_MAPPING,
        OutputMode.PASS_THROUGH,
    ]
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Förtydliga sammanfattningen.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_3",
                    "assistant_spec": {"instructions": "Sammanfatta per talare."},
                }
            ],
        },
    )
    assert isinstance(result, ProposalReady), result
    assert [step.output_mode for step in result.compiled.content.spec.steps] == [
        OutputMode.TRANSCRIBE_ONLY,
        OutputMode.SPEAKER_MAPPING,
        OutputMode.PASS_THROUGH,
    ]


@pytest.mark.parametrize("field_name", ["summary", "different"])
@pytest.mark.asyncio
async def test_saved_step_implicit_json_consumer_contract_is_preserved(field_name):
    from eneo.flows.ai_builder.ai_builder_validator import validate_spec

    flow, snapshots, catalog, context, prior = _saved_step_consumer_fixture("implicit")
    assert prior is not None
    assert validate_spec(prior).valid
    proposed = prior.model_copy(deep=True)
    proposed.steps[0].output_contract = {
        "type": "object",
        "properties": {field_name: {"type": "string"}},
        "required": [field_name],
    }
    validation = validate_spec(proposed)
    assert validation.valid is (field_name == "summary"), validation.errors
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={
            "plan_rationale": "Revise the result schema.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_fields": [
                        {
                            "name": field_name,
                            "field_type": "string",
                            "description": "Result summary",
                        }
                    ],
                },
            ],
        },
    )
    if field_name == "summary":
        assert isinstance(result, ProposalReady), result
    else:
        assert isinstance(result, CorrectableFailure), result
        assert "input_contract_type_mismatch" in result.codes


@pytest.mark.parametrize("change_contract", [False, True])
async def test_failure_repair_compilation_accepts_instructions_but_refuses_contract_change(
    change_contract,
):
    from dataclasses import replace

    flow, snapshots, catalog, context, prior = _saved_step_large_flow_fixture(4)
    context = replace(context, preserve_output_contract=True)
    change = {
        "kind": "modify",
        "existing_step_ref": "existing_step_4",
        "assistant_spec": {"instructions": "Explain the evidence clearly."},
    }
    if change_contract:
        change["output_type"] = "json"
        change["output_fields"] = [
            {"name": "summary", "field_type": "string", "description": "Summary"}
        ]
    result = await _process(
        flow=flow,
        assistant_snapshots=snapshots,
        resource_catalog=catalog,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        arguments={"plan_rationale": "Repair the instruction", "steps": [change]},
    )
    if change_contract:
        assert isinstance(result, CorrectableFailure), result
        assert "failed output contract" in result.feedback
    else:
        assert isinstance(result, ProposalReady), result
        assert (
            result.compiled.content.spec.steps[3].assistant_spec.instructions
            == "Explain the evidence clearly."
        )
        assert (
            result.compiled.content.spec.steps[3].output_type
            == prior.steps[3].output_type
        )
