from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder import (
    ai_builder_proposal_processor as proposal_processor_module,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_proposal import (
    process_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
    MCP_SELECTION_USE_SERVER_PREFIX,
    MCP_SELECTION_WITHOUT,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    build_self_correction_error_event,
)
from intric.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalTurnContext,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_question_recovery import (
    RecoveredToolDispatchRequest,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    AssistantSnapshotResourceUnavailableError,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _builder_plan,
    _compiled_outline_proposal,
    _make_context,
    _make_edit_compilation,
    _make_flow_spec,
    _make_turn,
)


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import (
    _make_processor,
    _make_response_with_tool_calls,
    _make_tool_call,
    _make_usage,
    _store_compiled_plan,
)


def test_proposal_processor_has_no_generic_submission_tool_config() -> None:
    deleted_module_names = ("".join(("SubmissionTool", "HandlerConfig")),)
    deleted_processor_methods = (
        "".join(("_handle_submission_", "tool_call")),
        "".join(("_build_submission_", "processing_kwargs")),
        "".join(("request_self_", "correction")),
        "".join(("_submission_retry_", "config")),
    )

    assert not [
        name
        for name in deleted_module_names
        if hasattr(proposal_processor_module, name)
    ]
    assert not [
        name
        for name in deleted_processor_methods
        if hasattr(AIBuilderProposalProcessor, name)
    ]


def test_self_correction_error_event_keeps_internal_feedback_out_of_user_message() -> (
    None
):
    event = build_self_correction_error_event(
        feedback=(
            "Compiled edit spec validation failed: Flow must have at least one step."
        ),
        failure_kind="validation",
    )

    payload = json.loads(event["data"])
    assert payload["code"] == "self_correction_invalid_plan"
    assert "did not contain any flow steps" in payload["message"]
    assert "Compiled edit spec" not in payload["message"]
    assert "Flow must have at least one step" not in payload["message"]


def test_self_correction_parse_error_uses_actionable_user_message() -> None:
    event = build_self_correction_error_event(
        feedback="Invalid propose_flow arguments: operations.0.add_payload.knowledge_refs",
        failure_kind="parse",
    )

    payload = json.loads(event["data"])
    assert payload["code"] == "self_correction_invalid_payload"
    assert "incomplete plan configuration" in payload["message"]
    assert "operations.0" not in payload["message"]


async def _single_plan_event(**_kwargs):
    yield {"event": "plan", "data": "{}"}


def test_proposal_turn_telemetry_counts_only_explicit_repair_calls() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-tracker",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    tracker.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    )
    tracker.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=4, completion_tokens=1, total_tokens=5),
    )
    tracker.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        counts_as_repair=True,
    )

    telemetry = tracker.build_planner_telemetry(tool_call_count=1)

    assert telemetry["llm_calls_made"] == 3
    assert telemetry["repair_attempts"] == 1
    assert telemetry["total_tokens"] == 22


@pytest.mark.asyncio
async def test_dispatch_known_tool_call_routes_question_recovery_dispatch_result() -> (
    None
):
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.name = ASK_STRUCTURED_QUESTION_TOOL_NAME
    usage_tracker = ProposalTurnTelemetry(
        request_id="req-question",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    ctx = _make_context(
        available_model_refs={"model-a"},
        available_kb_refs={"kb-a"},
        resource_catalog=MagicMock(),
        assistant_snapshots=MagicMock(),
        usage_tracker=usage_tracker,
    )
    recovered_call = _make_tool_call(
        CONFIRM_REQUIREMENTS_TOOL_NAME,
        {"summary": "Ready", "key_decisions": []},
    )
    recovered_dispatch = RecoveredToolDispatchRequest(
        tool_calls=[recovered_call],
        text_content=None,
        llm_messages=[{"role": "system", "content": "Recovered"}],
        tool_schemas=[{"function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}}],
        request_id="question-recovery",
    )

    async def _question_items(**_kwargs):
        yield {"event": "status", "data": '{"status":"repairing"}'}
        yield recovered_dispatch

    async def _handled_events(**_kwargs):
        yield {"event": "requirements_summary", "data": "{}"}

    repair_completion = AsyncMock()
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor."
            "make_usage_tracked_proposal_completion",
            return_value=repair_completion,
        ) as make_repair_completion,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.stream_structured_question_tool_call",
            side_effect=_question_items,
        ) as stream_question,
        patch.object(
            processor,
            "handle_tool_call",
            side_effect=_handled_events,
        ) as handle_tool_call,
    ):
        dispatched = processor._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert [event["event"] for event in events] == ["status", "requirements_summary"]
    request = stream_question.call_args.kwargs["request"]
    assert request.ctx is ctx
    assert request.tool_call is tool_call
    assert stream_question.call_args.kwargs["repair_completion"] is repair_completion
    make_repair_completion.assert_called_once_with(
        litellm_client=processor.litellm_client,
        usage_tracker=usage_tracker,
    )
    assert handle_tool_call.call_args.kwargs["tool_calls"] == [recovered_call]
    assert handle_tool_call.call_args.kwargs["request_id"] == "question-recovery"
    assert handle_tool_call.call_args.kwargs["available_model_refs"] == {"model-a"}
    assert handle_tool_call.call_args.kwargs["available_kb_refs"] == {"kb-a"}
    assert handle_tool_call.call_args.kwargs["resource_catalog"] is ctx.resource_catalog


@pytest.mark.asyncio
async def test_dispatch_known_tool_call_routes_outline_flow_handler() -> None:
    submission = MagicMock(spec=ProposalSubmissionOwner)
    processor = _make_processor(proposal_submission=submission)
    tool_call = MagicMock()
    tool_call.function.name = PROPOSE_FLOW_TOOL_NAME
    ctx = _make_context()

    async def _events():
        yield {"event": "plan", "data": "{}"}

    submission.dispatch_submission_tool_call.return_value = _events()
    dispatched = processor._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
    assert dispatched is not None
    events = [event async for event in dispatched]

    assert [event["event"] for event in events] == ["plan"]
    submission.dispatch_submission_tool_call.assert_called_once_with(
        ctx=ctx, tool_call=tool_call
    )


@pytest.mark.asyncio
async def test_propose_plan_create_mode_forces_outline_flow_only() -> None:
    processor = _make_processor()
    outline_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Document analysis",
            "plan_rationale": "Analyze the document and produce a summary.",
            "final_output_type": "text",
            "steps": [{"name": "Analyze", "instructions": "Analyze the document."}],
        },
    )

    async def process_outline(**kwargs) -> ToolProcessingResult:
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=_store_compiled_plan,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.call_proposal_completion",
            new=AsyncMock(return_value=_make_response_with_tool_calls(outline_call)),
        ) as call_completion,
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[ConversationMessage(role="user", content="Build a flow")],
                new_messages_start=1,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-propose",
                flow=None,
            )
        ]

    assert [event["event"] for event in events] == ["plan"]
    assert call_completion.await_args.kwargs["request"].tool_choice == {
        "type": "function",
        "function": {"name": PROPOSE_FLOW_TOOL_NAME},
    }
    assert [
        schema["function"]["name"]
        for schema in call_completion.await_args.kwargs["request"].tool_schemas
    ] == [PROPOSE_FLOW_TOOL_NAME]


@pytest.mark.asyncio
async def test_propose_plan_provider_error_still_yields_planner_upstream_error() -> (
    None
):
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.call_proposal_completion",
        new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[ConversationMessage(role="user", content="Build a flow")],
                new_messages_start=1,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-first-attempt-provider-error",
                flow=None,
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "planner_upstream_error"
    assert payload["phase"] == "planner"
    assert payload["request_id"] == "req-first-attempt-provider-error"


@pytest.mark.asyncio
async def test_propose_plan_empty_completion_choices_yields_missing_tool_error() -> (
    None
):
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.call_proposal_completion",
        new=AsyncMock(return_value=SimpleNamespace(choices=())),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[ConversationMessage(role="user", content="Build a flow")],
                new_messages_start=1,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-empty-first-attempt",
                flow=None,
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "proposal_tool_missing"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-empty-first-attempt"


@pytest.mark.asyncio
async def test_propose_plan_preflights_scoped_model_change_on_ai_step_without_llm() -> (
    None
):
    processor = _make_processor()
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
    captured_specs: list[FlowDraftSpecCore] = []

    async def store_plan(**kwargs):
        captured_specs.append(kwargs["compiled"].content.spec)
        return await _store_compiled_plan(**kwargs)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.call_proposal_completion",
            new=AsyncMock(),
        ) as call_completion,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=store_plan,
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(
                    session_id=prior_plan.session_id,
                    tenant_id=prior_plan.tenant_id,
                ),
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="ändra modell till gpt 5.4 nano",
                    )
                ],
                new_messages_start=0,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=catalog.model_refs,
                available_kb_refs=None,
                resource_catalog=catalog,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-model-edit",
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_b",
                    target_step_name="Analysera mötet",
                    target_step_number=2,
                ),
                prior_plan_for_revision=prior_plan,
            )
        ]

    assert [event["event"] for event in events] == ["plan"]
    call_completion.assert_not_awaited()
    assert len(captured_specs) == 1
    revised_spec = captured_specs[0]
    assert revised_spec.steps[0].model_dump(mode="json") == prior_spec.steps[
        0
    ].model_dump(mode="json")
    assert revised_spec.steps[1].assistant_spec.model_ref == "model.gpt-5-4-nano"


@pytest.mark.asyncio
async def test_propose_plan_preflights_transcription_step_model_notice_without_llm() -> (
    None
):
    processor = _make_processor()
    catalog = build_ai_builder_resource_catalog(
        available_models=[
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
            )
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.call_proposal_completion",
        new=AsyncMock(),
    ) as call_completion:
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(
                    session_id=prior_plan.session_id,
                    tenant_id=prior_plan.tenant_id,
                ),
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="ändra modell till gpt 5.4 nano",
                    )
                ],
                new_messages_start=0,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=catalog.model_refs,
                available_kb_refs=None,
                resource_catalog=catalog,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-model-edit-transcription",
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                    target_step_name="Transkribera mötesljud",
                    target_step_number=1,
                ),
                prior_plan_for_revision=prior_plan,
            )
        ]

    assert [event["event"] for event in events] == ["text"]
    assert "transkriberar ljud" in json.loads(events[0]["data"])["text"]
    call_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_propose_plan_asks_before_planning_when_named_mcp_is_unavailable() -> (
    None
):
    processor = _make_processor()
    session_id = uuid4()
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "svelte-server",
                "name": "Svelte mcp",
                "description": "Developer documentation helpers for Svelte apps.",
                "tools": [{"id": "svelte-docs", "name": "get-documentation"}],
            }
        ],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Använd Time MCP för att hämta aktuell tid.",
            metadata={"ui_language": "sv"},
        )
    ]

    events = [
        event
        async for event in processor.propose_plan(
            turn=_make_turn(session_id=session_id),
            conversation=conversation,
            new_messages_start=0,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            max_output_tokens=4096,
            proposal_temperature=0.2,
            request_id="req-propose",
            flow=None,
        )
    ]

    assert [event["event"] for event in events] == ["text", "question"]
    question_payload = json.loads(events[1]["data"])
    assert question_payload["question_id"] == MCP_RESOURCE_SELECTION_QUESTION_ID
    assert "Time MCP" in question_payload["question"]
    assert [option["label"] for option in question_payload["options"]] == [
        "Fortsätt utan MCP",
        "Använd Svelte mcp",
    ]
    assert not processor.litellm_client.acompletion.await_count
    processor.repo.commit_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_propose_plan_asks_before_planning_when_named_mcp_is_enabled() -> None:
    processor = _make_processor()
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "description": "Kan hämta tiden.",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Använd Time MCP för att hämta aktuell tid.",
            metadata={"ui_language": "sv"},
        )
    ]

    events = [
        event
        async for event in processor.propose_plan(
            turn=_make_turn(),
            conversation=conversation,
            new_messages_start=0,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            max_output_tokens=4096,
            proposal_temperature=0.2,
            request_id="req-propose",
            flow=None,
        )
    ]

    assert [event["event"] for event in events] == ["text", "question"]
    question_payload = json.loads(events[1]["data"])
    assert question_payload["question_id"] == MCP_RESOURCE_SELECTION_QUESTION_ID
    assert [option["label"] for option in question_payload["options"]] == [
        "Fortsätt utan MCP",
        "Använd Time MCP",
    ]
    assert not processor.litellm_client.acompletion.await_count


@pytest.mark.asyncio
async def test_propose_plan_continues_after_user_declines_mcp_usage() -> None:
    processor = _make_processor()
    outline_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Time fallback",
            "plan_rationale": "Respond without external tools.",
            "steps": [{"name": "Answer", "instructions": "Build a response without MCP."}],
        },
    )
    processor.litellm_client.acompletion.return_value = _make_response_with_tool_calls(
        outline_call
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Använd Time MCP för att hämta aktuell tid.",
            metadata={"ui_language": "sv"},
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

    async def process_outline(**kwargs) -> ToolProcessingResult:
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=_store_compiled_plan,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=conversation,
                new_messages_start=2,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=catalog,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-propose",
                flow=None,
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    processor.litellm_client.acompletion.assert_awaited_once()
    assert "response_format" not in (
        processor.litellm_client.acompletion.await_args.kwargs
    )


@pytest.mark.asyncio
async def test_propose_plan_reasks_when_user_requests_mcp_after_declining() -> None:
    processor = _make_processor()
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "description": "Kan hämta tiden.",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Använd Time MCP för att hämta aktuell tid.",
            metadata={"ui_language": "sv"},
        ),
        ConversationMessage(
            role="user",
            content="Fortsätt utan MCP",
            metadata={
                "question_answer": {
                    "question_id": MCP_RESOURCE_SELECTION_QUESTION_ID,
                    "selected_values": [MCP_SELECTION_WITHOUT],
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="Jag ändrade mig, använd Time MCP ändå.",
            metadata={"ui_language": "sv"},
        ),
    ]

    events = [
        event
        async for event in processor.propose_plan(
            turn=_make_turn(),
            conversation=conversation,
            new_messages_start=2,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            max_output_tokens=4096,
            proposal_temperature=0.2,
            request_id="req-propose",
            flow=None,
        )
    ]

    assert [event["event"] for event in events] == ["text", "question"]
    question_payload = json.loads(events[1]["data"])
    assert question_payload["question_id"] == MCP_RESOURCE_SELECTION_QUESTION_ID
    assert [option["value"] for option in question_payload["options"]] == [
        MCP_SELECTION_WITHOUT,
        f"{MCP_SELECTION_USE_SERVER_PREFIX}mcp_server.time-mcp",
    ]
    assert not processor.litellm_client.acompletion.await_count


@pytest.mark.asyncio
async def test_propose_plan_persists_initial_proposal_token_usage() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Simple flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "instructions": "Classify the request."}],
        },
        tool_call_id="call-outline",
    )
    processor.litellm_client.acompletion.return_value = _make_response_with_tool_calls(
        tool_call,
        prompt_tokens=10,
        completion_tokens=7,
        total_tokens=17,
    )
    captured_metadata: list[dict[str, object] | None] = []

    async def process_outline(**kwargs) -> ToolProcessingResult:
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=store_plan,
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[{"role": "user", "content": "Bygg ett flöde"}],
                litellm_model="openai/gpt-5.4-nano",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-proposal-usage",
            )
        ]

    assert [event["event"] for event in events] == ["plan"]
    metadata = captured_metadata[0]
    assert isinstance(metadata, dict)
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["request_id"] == "req-proposal-usage"
    assert planner_telemetry["model"] == "openai/gpt-5.4-nano"
    assert planner_telemetry["prompt_tokens"] == 10
    assert planner_telemetry["completion_tokens"] == 7
    assert planner_telemetry["total_tokens"] == 17
    assert planner_telemetry["llm_calls_made"] == 1
    assert planner_telemetry["token_usage_source"] == "provider"
    assert planner_telemetry["token_usage_estimated"] is False
    assert planner_telemetry["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert planner_telemetry["proposal_first_attempt_success"] is True
    assert planner_telemetry["proposal_first_attempt_failure_kind"] is None
    assert planner_telemetry["proposal_repair_invocation_count"] == 0
    assert planner_telemetry["proposal_repair_invocation_reasons"] == []
    session_telemetry = metadata["session_telemetry"]
    assert session_telemetry["total_tokens_total"] == 17
    assert session_telemetry["last_token_usage_source"] == "provider"


@pytest.mark.asyncio
async def test_propose_plan_persists_aggregate_token_usage_after_repair() -> None:
    processor = _make_processor()
    failed_tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"flow_name": "Broken"},
        tool_call_id="call-outline-bad",
    )
    repaired_tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Repaired flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "instructions": "Classify the request."}],
        },
        tool_call_id="call-outline-repaired",
    )
    processor.litellm_client.acompletion.side_effect = [
        _make_response_with_tool_calls(
            failed_tool_call,
            prompt_tokens=10,
            completion_tokens=7,
            total_tokens=17,
        ),
        _make_response_with_tool_calls(
            repaired_tool_call,
            prompt_tokens=4,
            completion_tokens=3,
            total_tokens=7,
        ),
    ]
    captured_metadata: list[dict[str, object] | None] = []
    process_attempts = 0

    async def process_outline(**kwargs) -> ToolProcessingResult:
        nonlocal process_attempts
        process_attempts += 1
        if process_attempts == 1:
            return ToolProcessingResult(
                feedback="Invalid outline.",
                failure_kind="parse",
            )
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=store_plan,
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[{"role": "user", "content": "Bygg ett flöde"}],
                litellm_model="openai/gpt-5.4-nano",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-proposal-repair-usage",
            )
        ]

    assert [event["event"] for event in events] == ["status", "plan"]
    metadata = captured_metadata[0]
    assert isinstance(metadata, dict)
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["prompt_tokens"] == 14
    assert planner_telemetry["completion_tokens"] == 10
    assert planner_telemetry["total_tokens"] == 24
    assert planner_telemetry["llm_calls_made"] == 2
    assert planner_telemetry["repair_attempts"] == 1
    assert planner_telemetry["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert planner_telemetry["proposal_first_attempt_success"] is False
    assert planner_telemetry["proposal_first_attempt_failure_kind"] == "parse"
    assert planner_telemetry["proposal_repair_invocation_count"] == 1
    assert planner_telemetry["proposal_repair_invocation_reasons"] == ["parse"]
    assert planner_telemetry["token_usage_source"] == "provider"
    assert metadata["session_telemetry"]["total_tokens_total"] == 24


@pytest.mark.asyncio
async def test_propose_plan_keeps_missing_tool_as_first_attempt_after_forced_retry() -> (
    None
):
    processor = _make_processor()
    parallel_tool_call = _make_tool_call(
        CONFIRM_REQUIREMENTS_TOOL_NAME,
        {"summary": "Unexpected requirements confirmation."},
        tool_call_id="call-unexpected-confirm",
    )
    repaired_tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Recovered flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "instructions": "Classify the request."}],
        },
        tool_call_id="call-outline-recovered",
    )
    processor.litellm_client.acompletion.side_effect = [
        _make_response_with_tool_calls(
            _make_tool_call(
                PROPOSE_FLOW_TOOL_NAME,
                {
                    "flow_name": "Unexpected first flow",
                    "plan_rationale": "This should be retried because tool calls were parallel.",
                    "steps": [{"name": "Classify", "instructions": "Classify the request."}],
                },
                tool_call_id="call-outline-unexpected-parallel",
            ),
            parallel_tool_call,
            prompt_tokens=11,
            completion_tokens=5,
            total_tokens=16,
        ),
        _make_response_with_tool_calls(
            repaired_tool_call,
            prompt_tokens=6,
            completion_tokens=4,
            total_tokens=10,
        ),
    ]
    captured_metadata: list[dict[str, object] | None] = []

    async def process_outline(**kwargs) -> ToolProcessingResult:
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_create_intent_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=store_plan,
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                turn=_make_turn(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[{"role": "user", "content": "Bygg ett flöde"}],
                litellm_model="openai/gpt-5.4-nano",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=_empty_catalog(),
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-proposal-missing-tool",
            )
        ]

    assert [event["event"] for event in events] == ["plan"]
    metadata = captured_metadata[0]
    assert isinstance(metadata, dict)
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["llm_calls_made"] == 2
    assert planner_telemetry["repair_attempts"] == 1
    assert planner_telemetry["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert planner_telemetry["proposal_first_attempt_success"] is False
    assert (
        planner_telemetry["proposal_first_attempt_failure_kind"]
        == "missing_submission_tool"
    )
    assert planner_telemetry["proposal_repair_invocation_count"] == 1
    assert planner_telemetry["proposal_repair_invocation_reasons"] == [
        "missing_submission_tool"
    ]


@pytest.mark.asyncio
async def test_edit_proposal_returns_validation_when_snapshot_resource_is_unavailable() -> (
    None
):
    flow = MagicMock()
    flow.steps = [
        FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=1,
            user_description="Skapa rapport",
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
            mcp_policy="inherit",
        )
    ]
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar rapport."
    flow.metadata_json = {}
    arguments = {
        "plan_rationale": "Byt namn.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "name": "Skapa DOCX-rapport",
            }
        ],
    }

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            side_effect=AssistantSnapshotResourceUnavailableError(
                kind="knowledge_base",
                local_ref="missing-kb",
            ),
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(base_planning_state_version=7),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=_empty_catalog(),
        )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert (
        "resource used by the existing flow is no longer available" in result.feedback
    )
    assert "missing-kb" not in result.feedback


@pytest.mark.asyncio
async def test_edit_proposal_normalizes_loose_add_payload_output_fields() -> None:
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {}
    arguments = {
        "plan_rationale": "Lägg till granskning.",
        "steps": [
            {
                "kind": "add",
                "step": {
                    "name": "Granska rubriker",
                    "instructions": "Kontrollera rubrikernas underlag.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "rubriker",
                            "field_type": "array",
                            "description": "Rubriker som ska granskas.",
                            "item_fields": [
                                {
                                    "name": "rubrik",
                                    "field_type": "string",
                                    "description": "Rubrik.",
                                },
                                {
                                    "name": "underlag",
                                    "field_type": "object",
                                    "description": "Underlag.",
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    }
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ) as compile_edit,
    ):
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=_empty_catalog(),
        )

    assert result.compiled_proposal is not None
    proposal = compile_edit.call_args.args[0]
    payload = proposal.steps[0].step
    assert payload.output_fields is not None
    rubriker = payload.output_fields[0]
    assert rubriker.field_type == "array"
    assert rubriker.item_fields is not None
    assert [(field.name, field.field_type) for field in rubriker.item_fields] == [
        ("rubrik", "string"),
        ("underlag", "string"),
    ]


@pytest.mark.asyncio
async def test_edit_proposal_retries_on_contextual_quality_feedback() -> None:
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {}

    arguments = {
        "plan_rationale": "Byt bara slutformatet.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "output_type": "docx",
            }
        ],
    }
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(base_planning_state_version=7),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=_empty_catalog(),
        )

    assert result.compiled_proposal is not None
    assert result.has_events is False


@pytest.mark.asyncio
async def test_edit_proposal_asks_before_accepting_mcp_usage() -> None:
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {}
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

    arguments = {
        "plan_rationale": "Lägg till ett tidsteg.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "output_type": "json",
            }
        ],
    }
    compiled_spec = _make_flow_spec(
        model_ref=None,
        knowledge_refs=[],
        mcp_tool_refs=["mcp_tool.time-mcp-get-current-time"],
    )
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ) as prepare_spec,
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Lägg till ett steg som använder Time MCP.",
                    metadata={"ui_language": "sv"},
                )
            ],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=catalog,
        )

    assert result.compiled_proposal is not None
    assert result.has_events is False
    assert prepare_spec.call_args.kwargs["resource_catalog"] is catalog


@pytest.mark.asyncio
async def test_edit_proposal_enforces_without_mcp_selection() -> None:
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {}
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

    arguments = {
        "plan_rationale": "Lägg till ett tidsteg.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "output_type": "json",
            }
        ],
    }
    compiled_spec = _make_flow_spec(
        model_ref=None,
        knowledge_refs=[],
        mcp_tool_refs=["mcp_tool.time-mcp-get-current-time"],
    )
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Fortsätt utan MCP",
                    metadata={
                        "question_answer": {
                            "question_id": MCP_RESOURCE_SELECTION_QUESTION_ID,
                            "selected_values": [MCP_SELECTION_WITHOUT],
                        }
                    },
                )
            ],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=catalog,
        )

    assert result.compiled_proposal is not None
    assert result.has_events is False


@pytest.mark.asyncio
async def test_edit_proposal_passes_metadata_to_edit_compiler() -> None:
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {
        "form_schema": {
            "fields": [{"name": "referensnummer", "type": "text"}],
        }
    }

    arguments = {
        "plan_rationale": "Byt bara slutformatet.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "output_type": "docx",
            }
        ],
    }
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ) as compile_edit,
    ):
        turn = _make_turn(base_planning_state_version=7)
        await process_edit_arguments(
            turn=turn,
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=_empty_catalog(),
        )

    assert compile_edit.call_args is not None
    assert compile_edit.call_args.kwargs["current_metadata_json"] == flow.metadata_json


@pytest.mark.asyncio
async def test_edit_proposal_passes_flat_modify_step_to_compiler() -> None:
    flow = MagicMock()
    flow.steps = [
        FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=1,
            user_description="Skapa rapport",
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
            mcp_policy="inherit",
        )
    ]
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar rapport."
    flow.metadata_json = {}
    arguments = {
        "plan_rationale": "Byt slutsteget till DOCX och byt namn.",
        "steps": [
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_1",
                "name": "Skapa DOCX-rapport",
                "output_type": "docx",
            },
        ],
    }
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit = _make_edit_compilation(compiled_spec)
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_proposal",
            return_value=edit,
        ) as compile_edit,
    ):
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=_empty_catalog(),
        )

    assert result.compiled_proposal is not None
    proposal = compile_edit.call_args.args[0]
    assert len(proposal.steps) == 1
    step = proposal.steps[0]
    assert step.name == "Skapa DOCX-rapport"
    assert step.output_type == OutputType.DOCX


@pytest.mark.asyncio
async def test_handle_tool_call_builds_proposal_context_for_edit_handler() -> None:
    submission = MagicMock(spec=ProposalSubmissionOwner)
    processor = _make_processor(proposal_submission=submission)
    flow = MagicMock()
    snapshots = {uuid4(): {"name": "Assistant"}}
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "plan_rationale": "Byt slutformatet.",
            "steps": [],
        },
    )
    captured_ctx: ProposalTurnContext | None = None

    def _edit_handler(*, ctx: ProposalTurnContext, tool_call: MagicMock):
        nonlocal captured_ctx
        captured_ctx = ctx

        async def _events():
            yield {"event": "done", "data": ""}

        return _events()

    submission.dispatch_submission_tool_call.side_effect = _edit_handler
    events = [
        event
        async for event in processor.handle_tool_call(
            turn=_make_turn(),
            conversation=[],
            new_messages_start=0,
            tool_calls=[tool_call],
            text_content="draft",
            llm_messages=[{"role": "system", "content": "Prompt"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={"api_key": "sk-test"},
            available_model_refs={"model_a"},
            available_kb_refs={"kb_a"},
            max_output_tokens=4096,
            request_id="req-ctx",
            flow=flow,
            assistant_snapshots=snapshots,
        )
    ]

    assert events == [
        {"event": "done", "data": ""},
    ], (
        "Text content accompanying a submission tool call (EDIT_FLOW) must be "
        "suppressed from the stream so the user never sees raw planner chatter "
        "alongside the plan event."
    )
    assert captured_ctx is not None
    assert captured_ctx.request_id == "req-ctx"
    assert captured_ctx.base_planning_state_version == 0
    assert captured_ctx.text_content == "draft"
    assert captured_ctx.flow is flow
    assert captured_ctx.assistant_snapshots == snapshots
    submission.dispatch_submission_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_handle_tool_call_preserves_text_when_tool_is_clarification_only() -> (
    None
):
    """Counterpart to the EDIT/CREATE suppression: when the tool call is a
    clarification tool (ASK_STRUCTURED_QUESTION), the accompanying text IS a
    legitimate user-visible message and must still be streamed."""
    processor = _make_processor()
    tool_call = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        {"question": "Vilket format?", "options": ["pdf", "docx"]},
    )

    async def _question_items(**_kwargs):
        yield {"event": "done", "data": ""}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.stream_structured_question_tool_call",
        side_effect=_question_items,
    ):
        events = [
            event
            async for event in processor.handle_tool_call(
                turn=_make_turn(),
                conversation=[],
                new_messages_start=0,
                tool_calls=[tool_call],
                text_content="Jag behöver en detalj till.",
                llm_messages=[{"role": "system", "content": "Prompt"}],
                tool_schemas=[
                    {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}
                ],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={"api_key": "sk-test"},
                available_model_refs=None,
                available_kb_refs=None,
                max_output_tokens=4096,
                request_id="req-ctx-ask",
            )
        ]

    assert events[0] == {
        "event": "text",
        "data": '{"text":"Jag behöver en detalj till."}',
    }, (
        "Text accompanying a non-submission (clarification) tool call must still "
        f"be emitted as a text event; got: {events}"
    )


@pytest.mark.asyncio
async def test_handle_confirm_requirements_parse_failure_triggers_self_correction() -> (
    None
):
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_confirm"
    tool_call.function.name = CONFIRM_REQUIREMENTS_TOOL_NAME
    tool_call.function.arguments = json.dumps(
        {"summary": "Kort", "key_decisions": "inte-en-lista"}
    )
    ctx = _make_context()

    async def _events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor."
        "run_tool_self_correction",
        return_value=_events(),
    ) as repair:
        events = [
            event
            async for event in processor._handle_confirm_requirements(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    request = repair.call_args.args[0]
    assert "Invalid requirements summary" in request.error_message
    assert request.retry_config.target_tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_arguments", "expected_detail"),
    [
        ("{not json", "Expecting property name"),
        ("[1, 2]", "arguments must be a JSON object"),
    ],
)
async def test_handle_confirm_requirements_invalid_tool_arguments_self_correct(
    raw_arguments: str,
    expected_detail: str,
) -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_confirm"
    tool_call.function.name = CONFIRM_REQUIREMENTS_TOOL_NAME
    tool_call.function.arguments = raw_arguments
    ctx = _make_context()

    async def _events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor."
        "run_tool_self_correction",
        return_value=_events(),
    ) as repair:
        events = [
            event
            async for event in processor._handle_confirm_requirements(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    request = repair.call_args.args[0]
    assert request.error_message.startswith("Invalid requirements summary: ")
    assert expected_detail in request.error_message
    assert request.retry_config.target_tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME


@pytest.mark.asyncio
async def test_handle_confirm_requirements_owner_events_skip_self_correction() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        CONFIRM_REQUIREMENTS_TOOL_NAME,
        {
            "summary": "Redo att bygga.",
            "key_decisions": [{"topic": "Indata", "decision": "Text"}],
            "input_description": "Text",
            "output_description": "Rapport",
        },
        tool_call_id="call_confirm",
    )
    ctx = _make_context()
    followup_events = (
        {"event": "text", "data": '{"text":"Vilken indatakälla?"}'},
        {"event": "question", "data": "{}"},
    )

    async def _repair_events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor."
            "process_confirm_requirements",
            create=True,
            new=AsyncMock(return_value=ToolProcessingResult(events=followup_events)),
        ) as process_confirm,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor."
            "run_tool_self_correction",
            return_value=_repair_events(),
        ) as repair,
    ):
        events = [
            event
            async for event in processor._handle_confirm_requirements(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == list(followup_events)
    process_confirm.assert_awaited_once()
    repair.assert_not_called()


@pytest.mark.asyncio
async def test_handle_confirm_requirements_owner_feedback_triggers_self_correction() -> (
    None
):
    processor = _make_processor()
    tool_call = _make_tool_call(
        CONFIRM_REQUIREMENTS_TOOL_NAME,
        {
            "summary": "Redo att bygga.",
            "key_decisions": [{"topic": "Indata", "decision": "Text"}],
            "input_description": "Text",
            "output_description": "Rapport",
        },
        tool_call_id="call_confirm",
    )
    ctx = _make_context()

    async def _repair_events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor."
            "process_confirm_requirements",
            create=True,
            new=AsyncMock(
                return_value=ToolProcessingResult(
                    feedback="Missing source material.",
                    failure_kind="validation",
                )
            ),
        ) as process_confirm,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor."
            "run_tool_self_correction",
            return_value=_repair_events(),
        ) as repair,
    ):
        events = [
            event
            async for event in processor._handle_confirm_requirements(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    process_confirm.assert_awaited_once()
    repair.assert_called_once()
    assert repair.call_args.args[0].error_message == "Missing source material."
