from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_proposal import (
    format_create_contextual_quality_feedback,
    outline_flow_retry_config,
    process_outline_arguments,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    BuilderPlan,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    PlannerPlanEnvelope,
    PlanStatus,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    StepTriple,
)


def _make_processor(**overrides) -> AIBuilderProposalProcessor:
    defaults = {
        "user": MagicMock(tenant_id=uuid4()),
        "repo": AsyncMock(),
        "litellm_client": AsyncMock(),
        "self_correction_temperature": 0.2,
        "self_correction_bumped_temperature": 0.5,
        "forced_proposal_temperature": 0.3,
        "quality_retry_warning_codes": set(),
    }
    defaults.update(overrides)
    return AIBuilderProposalProcessor(**defaults)


def _make_turn(
    *,
    session_id=None,
    tenant_id=None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


def _structured_fan_in_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Structured report",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract A",
                assistant_spec=AssistantSpec(instructions="Extract A."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract B",
                assistant_spec=AssistantSpec(instructions="Extract B."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Write report",
                assistant_spec=AssistantSpec(instructions="Write report."),
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _json_all_previous_architecture_spec() -> FlowDraftSpecCore:
    spec = _structured_fan_in_spec()
    return spec.model_copy(
        update={
            "steps": [
                *spec.steps[:2],
                spec.steps[2].model_copy(update={"input_type": InputType.JSON}),
            ]
        }
    )


def _make_plan(spec: FlowDraftSpecCore) -> BuilderPlan:
    return BuilderPlan(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED,
        spec=spec,
        spec_hash=spec.spec_hash(),
        envelope=PlannerPlanEnvelope(spec=spec),
    )


def _stored_plan_result(*, plan=None, envelope=None):
    return SimpleNamespace(
        plan=plan or MagicMock(id=uuid4()),
        envelope=envelope or MagicMock(),
        new_planning_state_version=1,
    )


def test_create_contextual_quality_feedback_uses_semantic_remediation() -> None:
    feedback = format_create_contextual_quality_feedback(
        conversation=[],
        spec=_structured_fan_in_spec(),
        aggregation_intent="linear",
        resource_catalog=None,
    )

    assert feedback is not None
    assert "Quality issues" in feedback
    assert "strukturerade" in feedback.casefold()
    for token in (
        "input_source",
        "uses_previous_fields",
        "input_bindings",
        "{{ step_",
    ):
        assert token not in feedback


def test_create_contextual_quality_feedback_still_enforces_architecture() -> None:
    with pytest.raises(AIBuilderArchitectureError):
        format_create_contextual_quality_feedback(
            conversation=[],
            spec=_json_all_previous_architecture_spec(),
            aggregation_intent="linear",
            resource_catalog=None,
        )


@pytest.mark.asyncio
async def test_outline_flow_retry_config_carries_revision_context() -> None:
    processor = _make_processor()
    planning_state = PlanningState.empty()
    plan = _make_plan(_structured_fan_in_spec())
    plan_edit_context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=plan.id,
        target_plan_step_ref="step_a",
    )

    config = outline_flow_retry_config(
        processor=processor,
        planning_state=planning_state,
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=plan,
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_create_proposal.process_outline_arguments",
        new=AsyncMock(
            return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
        ),
    ) as process_outline:
        await config.process_tool_invocation(
            ToolRetryInvocation(
                turn=_make_turn(),
                conversation=[],
                new_messages_start=0,
                arguments={"flow_name": "Test", "plan_rationale": "R", "steps": []},
                assistant_content="Här är mitt korrigerade förslag:",
                tool_call_id="call_retry",
                available_model_refs=None,
                available_kb_refs=None,
            )
        )

    process_outline.assert_awaited_once()
    assert process_outline.await_args.kwargs["planning_state"] is planning_state
    assert process_outline.await_args.kwargs["plan_edit_context"] is plan_edit_context
    assert process_outline.await_args.kwargs["prior_plan_for_revision"] is plan


@pytest.mark.asyncio
async def test_outline_processing_enforces_without_mcp_selection() -> None:
    processor = _make_processor()
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Använd Time MCP för att hämta aktuell tid.",
        ),
        ConversationMessage(
            role="user",
            content="Fortsätt utan MCP",
            metadata={
                "question_answer": {
                    "question_id": MCP_RESOURCE_SELECTION_QUESTION_ID,
                    "selected_values": ["without_mcp"],
                }
            },
        ),
    ]

    result = await process_outline_arguments(
        processor=processor,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=0,
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use MCP despite the user's decline.",
            "steps": [
                {
                    "name": "Hämta tid",
                    "task": "Hämta aktuell tid via Time MCP.",
                    "mcp_tool_refs": ["mcp_tool.time-mcp-get-current-time"],
                }
            ],
        },
        assistant_content="",
        tool_call_id="call-time",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.failure_kind == "quality"
    assert result.feedback is not None
    assert "continue without MCP" in result.feedback
    processor.repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_outline_validation_failure_preserves_duplicate_step_name_code() -> None:
    processor = _make_processor()

    result = await process_outline_arguments(
        processor=processor,
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        new_messages_start=0,
        arguments={
            "flow_name": "Duplicate names",
            "plan_rationale": "Two semantic steps accidentally share a name.",
            "steps": [
                {"name": "Förbered PDF-innehåll", "task": "Sammanfatta texten."},
                {"name": "Förbered PDF-innehåll", "task": "Skriv slutrapport."},
            ],
        },
        assistant_content="",
        tool_call_id="call-duplicate-name",
        available_model_refs=None,
        available_kb_refs=None,
    )

    assert result.failure_kind == "validation"
    assert "duplicate_step_name" in result.failure_codes
    assert result.feedback is not None
    assert "Duplicate step name" in result.feedback
    processor.repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_outline_audio_to_docx_returns_plan_event() -> None:
    processor = _make_processor()
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    async def _store_plan(**kwargs):
        spec = kwargs["spec"]
        return _stored_plan_result(
            plan=_make_plan(spec),
            envelope=PlannerPlanEnvelope(spec=spec),
        )

    with patch(
        "intric.flows.ai_builder.ai_builder_create_proposal.store_plan_and_update_conversation",
        new=AsyncMock(side_effect=_store_plan),
    ):
        result = await process_outline_arguments(
            processor=processor,
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Bygg ett flöde som transkriberar ljud och skapar DOCX.",
                )
            ],
            new_messages_start=0,
            arguments={
                "flow_name": "Ljudrapport",
                "plan_rationale": "Skapa en DOCX-rapport från uppladdat ljud.",
                "steps": [
                    {
                        "name": "Sammanfatta inspelningen",
                        "task": "Sammanfatta den transkriberade inspelningen.",
                    }
                ],
            },
            assistant_content="",
            tool_call_id="call-audio-docx",
            available_model_refs=None,
            available_kb_refs=None,
            planning_state=state,
        )

    assert result.event is not None
    payload = json.loads(result.event["data"])
    assert payload["envelope"]["spec"]["steps"][0]["input_type"] == "audio"
    assert payload["envelope"]["spec"]["steps"][-1]["output_type"] == "docx"
