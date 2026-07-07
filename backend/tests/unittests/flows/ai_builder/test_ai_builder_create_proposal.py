from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    process_create_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    build_create_contextual_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_CASE_METADATA,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_prepares_through_authoring_command_async,
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
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def test_create_contextual_quality_feedback_uses_semantic_remediation() -> None:
    feedback = build_create_contextual_quality_feedback(
        conversation=[],
        spec=_structured_fan_in_spec(),
        aggregation_intent="linear",
        resource_catalog=None,
    ).feedback

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

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=conversation,
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use MCP despite the user's decline.",
            "steps": [
                {
                    "name": "Hämta tid",
                    "instructions": "Hämta aktuell tid via Time MCP.",
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
    assert result.events == ()


@pytest.mark.asyncio
async def test_outline_processing_propagates_internal_compile_error() -> None:
    with patch(
        "eneo.flows.ai_builder.ai_builder_create_proposal.compile_create_intent_to_spec",
        side_effect=RuntimeError("compiler exploded"),
    ):
        with pytest.raises(RuntimeError, match="compiler exploded"):
            await process_create_intent_arguments(
                turn=_make_turn(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett textflöde.")
                ],
                arguments={
                    "flow_name": "Internal bug",
                    "plan_rationale": "Trigger compiler bug.",
                    "steps": [
                        {"name": "Analysera", "instructions": "Analysera texten."}
                    ],
                },
                tool_call_id="call-internal-bug",
                available_model_refs=None,
                available_kb_refs=None,
            )


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

    result = await process_create_intent_arguments(
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
                    "instructions": "Hämta aktuell tid via Time MCP.",
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
    assert result.events == ()


@pytest.mark.asyncio
async def test_outline_processing_expands_mcp_server_name_through_compiled_spec() -> (
    None
):
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Använd Time MCP för att hämta och konvertera tid.",
            )
        ],
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use the selected time MCP server.",
            "steps": [
                {
                    "name": "Hämta tid",
                    "instructions": "Använd Time MCP för tidshämtning.",
                    "mcp_server_refs": ["Time MCP"],
                }
            ],
        },
        tool_call_id="call-time-server",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is not None
    assistant_spec = result.compiled_proposal.content.spec.steps[0].assistant_spec
    assert assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-get-current-time",
        "mcp_tool.time-mcp-convert-time",
    ]


@pytest.mark.asyncio
async def test_outline_processing_keeps_named_mcp_tool_to_one_tool() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Använd bara get_current_time från Time MCP.",
            )
        ],
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use one selected MCP tool.",
            "steps": [
                {
                    "name": "Hämta aktuell tid",
                    "instructions": "Använd get_current_time för angiven tidszon.",
                    "mcp_tool_refs": ["get_current_time"],
                }
            ],
        },
        tool_call_id="call-time-tool",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is not None
    assistant_spec = result.compiled_proposal.content.spec.steps[0].assistant_spec
    assert assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert assistant_spec.mcp_tool_refs == ["mcp_tool.time-mcp-get-current-time"]


@pytest.mark.asyncio
async def test_outline_processing_reports_unknown_resource_from_compiled_spec() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[_model_resource("model-1", "gpt-5.4-nano")],
        available_kbs=[],
        available_mcps=[],
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Unknown model flow",
            "plan_rationale": "Use a missing model ref.",
            "steps": [
                {
                    "name": "Analysera",
                    "instructions": "Analysera texten.",
                    "model_ref": "missing-fast-model",
                }
            ],
        },
        tool_call_id="call-unknown-resource",
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "Unknown model reference 'missing-fast-model'" in result.feedback
    assert "step 'step_a'.assistant_spec.model_ref" in result.feedback
    assert "model.gpt-5-4-nano" in result.feedback


@pytest.mark.asyncio
async def test_outline_validation_failure_preserves_duplicate_step_name_code() -> None:
    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Duplicate names",
            "plan_rationale": "Two semantic steps accidentally share a name.",
            "steps": [
                {
                    "name": "Förbered PDF-innehåll",
                    "instructions": "Sammanfatta texten.",
                },
                {"name": "Förbered PDF-innehåll", "instructions": "Skriv slutrapport."},
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
async def test_outline_assembly_rejection_returns_validation_failure_code() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="documents",
        source="structured_answer",
        confidence="high",
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(role="user", content="Bygg ett dokumentflöde.")
        ],
        arguments={
            "flow_name": "Invalid document reader",
            "plan_rationale": "The first step tried to write text from documents.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write a summary directly from uploaded documents.",
                    "output_type": "text",
                }
            ],
        },
        tool_call_id="call-assembly-rejection",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset(
        {"assembly_source_file_first_step_requires_json"}
    )
    assert result.feedback is not None
    assert "first semantic step" in result.feedback


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

    result = await process_create_intent_arguments(
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
                    "instructions": "Sammanfatta den transkriberade inspelningen.",
                }
            ],
        },
        tool_call_id="call-audio-docx",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert spec.steps[0].input_type == InputType.AUDIO
    assert spec.steps[-1].output_type == OutputType.DOCX
    await assert_create_spec_prepares_through_authoring_command_async(spec)


@pytest.mark.asyncio
async def test_outline_processing_uses_runtime_hint_source_from_conversation() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som använder inmatningsfält för målgrupp "
                    "vid körning och skriver en rapport."
                ),
            )
        ],
        arguments={
            "flow_name": "Målgruppsrapport",
            "plan_rationale": "Anpassa rapporten efter målgrupp.",
            "steps": [
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten för vald målgrupp.",
                    "uses_form_fields": ["malgrupp"],
                }
            ],
        },
        tool_call_id="call-runtime-hints",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert spec.form_fields is not None
    assert [field.name for field in spec.form_fields] == ["malgrupp"]
    assert spec.steps[0].input_bindings is not None
    assert "{{ flow_input.malgrupp }}" in spec.steps[0].input_bindings["question"]
    await assert_create_spec_prepares_through_authoring_command_async(spec)
