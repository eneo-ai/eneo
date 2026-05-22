from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_proposal import (
    process_outline_arguments,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    format_create_contextual_quality_feedback,
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
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


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
async def test_outline_processing_returns_compiled_proposal_for_processor_finalization() -> (
    None
):
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
        turn=_make_turn(),
        conversation=conversation,
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
        tool_call_id="call-time",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is not None
    assert result.feedback is None
    assert result.has_events is False


@pytest.mark.asyncio
async def test_outline_processing_leaves_mcp_question_persistence_to_processor() -> (
    None
):
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

    result = await process_outline_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Använd Time MCP för att hämta aktuell tid.",
                metadata={"ui_language": "sv"},
            )
        ],
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use selected MCP tooling.",
            "steps": [
                {
                    "name": "Hämta tid",
                    "task": "Hämta aktuell tid via Time MCP.",
                    "mcp_tool_refs": ["mcp_tool.time-mcp-get-current-time"],
                }
            ],
        },
        tool_call_id="call-time",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is not None
    assert result.has_events is False


@pytest.mark.asyncio
async def test_outline_validation_failure_preserves_duplicate_step_name_code() -> None:
    result = await process_outline_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Duplicate names",
            "plan_rationale": "Two semantic steps accidentally share a name.",
            "steps": [
                {"name": "Förbered PDF-innehåll", "task": "Sammanfatta texten."},
                {"name": "Förbered PDF-innehåll", "task": "Skriv slutrapport."},
            ],
        },
        tool_call_id="call-duplicate-name",
        available_model_refs=None,
        available_kb_refs=None,
    )

    assert result.compiled_proposal is not None
    validation = result.compiled_proposal.validation
    assert not validation.valid
    assert any(error.code == "duplicate_step_name" for error in validation.errors)
    assert any("Duplicate step name" in error.message for error in validation.errors)


@pytest.mark.asyncio
async def test_outline_audio_to_docx_returns_compiled_proposal() -> None:
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

    result = await process_outline_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Bygg ett flöde som transkriberar ljud och skapar DOCX.",
            )
        ],
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
        tool_call_id="call-audio-docx",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.spec
    assert spec.steps[0].input_type == InputType.AUDIO
    assert spec.steps[-1].output_type == OutputType.DOCX
