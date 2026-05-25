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
    process_scoped_step_model_revision_if_requested,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    PlannerPlanEnvelope,
    PlanStatus,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    format_create_contextual_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_CASE_METADATA,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    ResolvedSlot,
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


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def _builder_plan(spec: FlowDraftSpecCore) -> BuilderPlan:
    return BuilderPlan(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED,
        spec=spec,
        spec_hash=spec.spec_hash(),
        envelope=PlannerPlanEnvelope(spec=spec),
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

    result = await process_outline_arguments(
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
                    "task": "Skriv rapporten för vald målgrupp.",
                    "uses_input_fields": ["malgrupp"],
                }
            ],
        },
        tool_call_id="call-runtime-hints",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.spec
    assert spec.form_fields is not None
    assert [field.name for field in spec.form_fields] == ["malgrupp"]
    assert spec.steps[0].input_bindings is not None
    assert "{{ flow_input.malgrupp }}" in spec.steps[0].input_bindings["question"]


@pytest.mark.asyncio
async def test_scoped_outline_revision_explains_model_change_on_transcription_step() -> (
    None
):
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-base", "gpt-5.4"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera mötesljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera mötet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriptionen.",
                    model_ref="model.gpt-4o-mini",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_model_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content="ändra modell till gpt 5.4 nano",
            )
        ],
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_a",
            target_step_name="Transkribera mötesljud",
            target_step_number=1,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result.compiled_proposal is None
    assert result.feedback is None
    assert result.user_message is not None
    assert "transkriberar ljud" in result.user_message
    assert "model.gpt-5-4-nano" not in result.user_message


@pytest.mark.asyncio
async def test_scoped_outline_revision_changes_model_on_selected_ai_step() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    old_model_ref = "model.gpt-4o-mini"
    new_model_ref = "model.gpt-5-4-nano"
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera mötesljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera mötet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriptionen.",
                    model_ref=old_model_ref,
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_model_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content="byt modell från gpt-4o mini till gpt 5.4 nano",
            )
        ],
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_b",
            target_step_name="Analysera mötet",
            target_step_number=2,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result.compiled_proposal is not None
    assert result.feedback is None
    assert (
        result.compiled_proposal.plan_rationale == "Bytte modell på det valda steget."
    )
    assert result.compiled_proposal.assumptions == tuple()
    revised_steps = result.compiled_proposal.spec.steps
    assert revised_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert revised_steps[1].assistant_spec.model_ref == new_model_ref
