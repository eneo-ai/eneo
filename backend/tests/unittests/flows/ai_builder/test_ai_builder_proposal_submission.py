from __future__ import annotations

import json
from time import perf_counter_ns
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorPhase,
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_status_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    LLMCompletionMessage,
    LLMCompletionToolCall,
    LLMCompletionToolCallFunction,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
    extract_requested_output_sections,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_retry import (
    ForcedToolRetryOutcome,
    build_self_correction_error_event,
)
from eneo.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
    _forced_submission_response,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ProposalMessageGroup,
    ToolProcessingResult,
    ToolRetryConfig,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    StepTriple,
)
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _compiled_edit_proposal,
    _compiled_outline_proposal,
    _description_update_advisory,
    _make_context,
    _make_flow_spec,
    _make_retry_invocation,
    _plan_stream_event,
)
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import (
    _flow_with_description,
    _make_response_with_text,
    _make_response_with_tool_calls,
    _make_submission,
    _make_tool_call,
    _store_compiled_plan,
)


def _route() -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


def _message_groups(
    messages: list[dict[str, object]],
) -> tuple[ProposalMessageGroup, ...]:
    return (
        ProposalMessageGroup(
            messages=tuple(messages),  # type: ignore[arg-type]
            kind="current_turn",
            protected=True,
        ),
    )


def _normalized_tool_call(name: str) -> LLMCompletionToolCall:
    return LLMCompletionToolCall(
        id=f"call-{name}",
        function=LLMCompletionToolCallFunction(name=name, arguments="{}"),
    )


def _wire_events(
    events: list[AIBuilderStreamEvent] | tuple[AIBuilderStreamEvent, ...],
) -> list[dict[str, str]]:
    return [encode_ai_builder_stream_event(event) for event in events]


def _normalized_message(
    *,
    tool_calls: tuple[LLMCompletionToolCall, ...],
    content: str = "text",
) -> LLMCompletionMessage:
    return LLMCompletionMessage(content=content, tool_calls=tool_calls)


@pytest.mark.asyncio
async def test_complex_authoring_spec_submits_once_without_repairs() -> None:
    authoring_spec = """
    Create a DOCX decision report from an uploaded audio recording.

    # Transcribe and review the recording
    Make the recording searchable and let the case owner correct the transcript.
    # Analyze stable evidence
    Extract grounded facts, risks, and recommended actions in a stable structure.
    # Write and review the decision report
    Write the complete report and let the case owner edit it.
    # Finalize the document
    Produce the complete revised document body for delivery.
    """
    requested_output_sections = extract_requested_output_sections(authoring_spec)
    assert not requested_output_sections.high_confidence

    proposal_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Decision report",
            "plan_rationale": "Ground, draft, review, and finalize one report.",
            "steps": [
                {
                    "name": "Transcribe and review recording",
                    "instructions": (
                        "Transcribe the audio recording and let the case owner "
                        "correct the transcript before analysis."
                    ),
                    "output_type": "text",
                    "review_mode": "edit",
                },
                {
                    "name": "Analyze stable decision evidence",
                    "instructions": (
                        "Extract grounded facts, risks, and recommended actions "
                        "from the corrected transcript."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "string",
                            "description": "Grounded facts from the source.",
                        },
                        {
                            "name": "risks",
                            "field_type": "string",
                            "description": "Grounded risks from the source.",
                        },
                        {
                            "name": "actions",
                            "field_type": "string",
                            "description": "Recommended actions grounded in the source.",
                        },
                    ],
                },
                {
                    "name": "Write and review decision report",
                    "instructions": (
                        "Write the complete final decision report from the extracted "
                        "facts, risks, and actions, then let the case owner edit it."
                    ),
                    "output_type": "text",
                    "review_mode": "edit",
                },
            ],
        },
        tool_call_id="call-complex-authoring-spec",
    )
    provider_response = _make_response_with_tool_calls(
        proposal_call,
        prompt_tokens=3_200,
        completion_tokens=1_100,
        total_tokens=4_300,
    )
    submission = _make_submission()
    assert isinstance(submission, ProposalSubmissionOwner)
    submission.litellm_client.acompletion = AsyncMock(return_value=provider_response)
    planning_state = PlanningState.empty()
    planning_state.architecture_commit = finalize_architecture_commit(
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
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
    )
    turn = _make_context().turn
    captured_compiled: list[CompiledProposal] = []
    captured_telemetry: list[dict[str, object]] = []

    async def store_plan(**kwargs: object):
        compiled = kwargs["compiled"]
        assistant_metadata = kwargs["assistant_metadata"]
        assert isinstance(compiled, CompiledProposal)
        assert isinstance(assistant_metadata, dict)
        planner_telemetry = assistant_metadata.get("planner_telemetry")
        assert isinstance(planner_telemetry, dict)
        captured_compiled.append(compiled)
        captured_telemetry.append(
            {str(key): value for key, value in planner_telemetry.items()}
        )
        return await _store_compiled_plan(**kwargs)

    started_ns = perf_counter_ns()
    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        events = _wire_events(
            [
                event
                async for event in submission.run_active_submission_attempt(
                    turn=turn,
                    conversation=[
                        ConversationMessage(role="user", content=authoring_spec)
                    ],
                    new_messages_start=1,
                    message_groups=_message_groups(
                        [{"role": "system", "content": "Prompt"}]
                    ),
                    completion_model_route=_route(),
                    available_model_refs=None,
                    available_kb_refs=None,
                    resource_catalog=resource_catalog,
                    max_output_tokens=8_192,
                    proposal_temperature=0.2,
                    request_id="req-complex-authoring-spec",
                    planning_state=planning_state,
                    requested_output_sections=requested_output_sections,
                )
            ]
        )
    elapsed_ms = (perf_counter_ns() - started_ns) // 1_000_000

    assert [event["event"] for event in events] == ["plan"]
    provider_calls = submission.litellm_client.acompletion.await_count
    assert provider_calls == 1
    compiled = captured_compiled[0]
    step_names = [step.name for step in compiled.content.spec.steps]
    assert len(step_names) == len({name.casefold() for name in step_names})
    review_steps = [
        step for step in compiled.content.spec.steps if step.review_policy is not None
    ]
    assert len(review_steps) == 2
    assert all(step.output_type.value in {"json", "text"} for step in review_steps)
    planner_telemetry = captured_telemetry[0]
    assert planner_telemetry["llm_calls_made"] == 1
    assert planner_telemetry["repair_attempts"] == 0
    assert planner_telemetry["total_tokens"] == 4_300
    assert provider_calls < 5
    assert planner_telemetry["repair_attempts"] < 4
    assert planner_telemetry["total_tokens"] < 85_009
    assert elapsed_ms < 155_900


@pytest.mark.parametrize(
    "message",
    [
        _normalized_message(tool_calls=()),
        _normalized_message(
            tool_calls=(
                _normalized_tool_call(PROPOSE_FLOW_TOOL_NAME),
                _normalized_tool_call(PROPOSE_FLOW_TOOL_NAME),
            ),
        ),
        _normalized_message(
            tool_calls=(_normalized_tool_call("confirm_requirements"),),
        ),
    ],
)
def test_forced_submission_response_rejects_missing_parallel_or_wrong_tool(
    message: LLMCompletionMessage,
) -> None:
    assert _forced_submission_response(message=message) is None


def test_forced_submission_response_accepts_one_active_submission_tool() -> None:
    tool_call = _normalized_tool_call(PROPOSE_FLOW_TOOL_NAME)

    response = _forced_submission_response(
        message=_normalized_message(
            tool_calls=(tool_call,),
            content="Här är planen.",
        ),
    )

    assert response is not None
    assert response.tool_call is tool_call
    assert response.text_content == "Här är planen."


@pytest.mark.asyncio
async def test_create_propose_flow_architecture_error_returns_event_without_repair() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-architecture",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Audio report",
            "plan_rationale": "Create a report from audio.",
            "steps": [
                {"name": "Summarize", "instructions": "Summarize the recording."}
            ],
        },
        tool_call_id="call-architecture",
    )
    planning_state = PlanningState.empty()
    planning_state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "audio_to_artifact_report",
                "text_to_artifact_report",
            ],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        usage_tracker=tracker,
        request_id="req-architecture",
        text_content="",
        planning_state=planning_state,
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_tool_self_correction"
    ) as repair:
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    repair.assert_not_called()
    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["phase"] == "proposal"
    assert payload["details"]["architecture_error_code"] == (
        "architecture_materialization_failed"
    )
    assert payload["details"]["architecture_error_detail"] == (
        "The confirmed architecture pattern is not supported by create assembly."
    )
    assert payload["details"]["failure_code"] == (
        "assembly_unsupported_architecture_hints"
    )
    assert payload["details"]["reason"] == "unsupported_architecture_hints"

    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
    assert telemetry["proposal_repair_invocation_reasons"] == []


@pytest.mark.asyncio
async def test_create_propose_flow_ambiguous_structured_source_returns_event_without_repair() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-ambiguous-structured-source",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Ambiguous report",
            "plan_rationale": "Two structured stages precede section writers.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract source facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "source_facts",
                            "field_type": "string",
                            "description": "Facts from the source.",
                        }
                    ],
                },
                {
                    "name": "Prepare report facts",
                    "instructions": "Prepare report facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "report_facts",
                            "field_type": "string",
                            "description": "Facts prepared for the report.",
                        }
                    ],
                },
                {
                    "name": "Write findings",
                    "instructions": "Write the findings section.",
                    "output_type": "text",
                },
                {
                    "name": "Write recommendations",
                    "instructions": "Write the recommendations section.",
                    "output_type": "text",
                },
            ],
        },
        tool_call_id="call-ambiguous-structured-source",
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Build a report")],
        usage_tracker=tracker,
        request_id="req-ambiguous-structured-source",
        text_content="",
    )

    async def _unexpected_repair_events(_request):
        yield build_status_event(AIBuilderStatus.REPAIRING)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_tool_self_correction",
        side_effect=_unexpected_repair_events,
    ) as repair:
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    repair.assert_not_called()
    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["phase"] == "proposal"
    assert payload["details"]["architecture_error_code"] == (
        "architecture_materialization_failed"
    )
    assert payload["details"]["architecture_error_detail"] == (
        "Step 3: Consolidate the required facts into one structured preparation "
        "step, or use one supported terminal aggregate before adding section writers."
    )
    assert payload["details"]["failure_code"] == (
        "section_writer_structured_source_ambiguous"
    )
    assert payload["details"]["reason"] == (
        "section_writer_structured_source_ambiguous"
    )
    assert payload["details"]["step_index"] == 3

    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
    assert telemetry["proposal_repair_invocation_reasons"] == []
    assert telemetry["llm_calls_made"] == 0
    assert telemetry["repair_attempts"] == 0


@pytest.mark.asyncio
async def test_create_propose_flow_retryable_assembly_rejection_invokes_repair() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-assembly-rejection",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Invalid previous refs",
            "plan_rationale": "The model authored backend wiring.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write a summary from a previous field.",
                    "uses_previous_fields": [{"from_step": 1, "field_path": "summary"}],
                }
            ],
        },
        tool_call_id="call-assembly-rejection",
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        usage_tracker=tracker,
        request_id="req-assembly-rejection",
        text_content="",
    )
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="uses_previous_fields is backend-owned wiring.",
            failure_kind="validation",
            failure_codes=frozenset({"assembly_explicit_refs_not_supported"}),
        )
    )

    async def _repair_events(request):
        assert request.failure_codes == frozenset(
            {"assembly_explicit_refs_not_supported"}
        )
        yield build_status_event(AIBuilderStatus.REPAIRING)

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction",
            side_effect=_repair_events,
        ) as repair,
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    repair.assert_called_once()
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "validation"
    assert telemetry["proposal_repair_invocation_count"] == 1
    assert telemetry["proposal_repair_invocation_reasons"] == ["validation"]


@pytest.mark.asyncio
async def test_edit_propose_flow_architecture_error_is_not_translated_to_create_error() -> (
    None
):
    submission = _make_submission()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "steps": []},
        tool_call_id="call-edit-architecture",
    )
    ctx = _make_context(
        flow=SimpleNamespace(id=uuid4(), steps=[]),
        request_id="req-edit-architecture",
    )
    process_edit = AsyncMock(
        side_effect=AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="edit should not translate this",
            log_context={"surface": "edit"},
        )
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction"
        ) as repair,
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        pytest.raises(AIBuilderArchitectureError),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        _ = [event async for event in dispatched]

    repair.assert_not_called()
    process_edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_propose_flow_user_message_emits_text_event() -> None:
    submission = _make_submission()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Need details",
            "plan_rationale": "Ask for missing detail.",
            "steps": [],
        },
        tool_call_id="call-create-user-message",
    )
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(user_message="I need one more detail.")
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(), tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert len(events) == 1
    assert events[0]["event"] == "text"
    assert json.loads(events[0]["data"]) == {"text": "I need one more detail."}


@pytest.mark.asyncio
async def test_create_propose_flow_plural_events_emit_in_order() -> None:
    submission = _make_submission()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Ready",
            "plan_rationale": "Emit multiple events.",
            "steps": [],
        },
        tool_call_id="call-create-events",
    )
    expected_events = (
        build_status_event(AIBuilderStatus.REPAIRING),
        _plan_stream_event(),
    )
    expected_wire_events = _wire_events(expected_events)
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(events=expected_events)
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(), tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == expected_wire_events


@pytest.mark.asyncio
async def test_edit_propose_flow_plural_events_emit_in_order() -> None:
    submission = _make_submission()
    compiled = _compiled_edit_proposal()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
        tool_call_id="call-edit-events",
    )
    expected_events = (
        build_status_event(AIBuilderStatus.REPAIRING),
        _plan_stream_event(),
    )
    expected_wire_events = _wire_events(expected_events)
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=compiled)
    )
    finalize = AsyncMock(return_value=ToolProcessingResult(events=expected_events))

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(flow=_flow_with_description("Old description")),
            tool_call=tool_call,
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == expected_wire_events


@pytest.mark.asyncio
async def test_edit_propose_flow_user_message_routes_to_self_correction() -> None:
    submission = _make_submission()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
        tool_call_id="call-edit-user-message",
    )
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(
            user_message="I need one more detail.",
            failure_kind="validation",
        )
    )

    async def _repair_events(_request):
        yield build_status_event(AIBuilderStatus.REPAIRING)

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction",
            side_effect=_repair_events,
        ) as repair,
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(flow=_flow_with_description("Old description")),
            tool_call=tool_call,
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    repair.assert_called_once()


@pytest.mark.asyncio
async def test_create_propose_flow_finalization_uses_default_assistant_content() -> (
    None
):
    submission = _make_submission()
    compiled = _compiled_outline_proposal()
    finalize = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=compiled)
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Create",
            "plan_rationale": "Create a flow.",
            "steps": [],
        },
        tool_call_id="call-create-finalize",
    )
    assistant_metadata = {"planner_telemetry": {"preexisting": True}}

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(
                text_content="Provider prose",
                assistant_metadata=assistant_metadata,
            ),
            tool_call=tool_call,
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert [event["event"] for event in events] == ["plan"]
    request = finalize.await_args.args[0]
    assert request.assistant_content == "Här är mitt förslag:"
    assert request.assistant_metadata is assistant_metadata
    assert request.metadata_tool_call is tool_call


@pytest.mark.asyncio
async def test_create_propose_flow_retry_does_not_preserve_failed_attempt_step_count() -> (
    None
):
    submission = _make_submission()
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Document analysis",
            "plan_rationale": "Analyze documents.",
            "steps": [
                {"name": "Read", "instructions": "Read the material."},
                {"name": "Extract", "instructions": "Extract key facts."},
                {"name": "Compare", "instructions": "Compare findings."},
                {"name": "Report", "instructions": "Create the report."},
            ],
        },
        tool_call_id="call-outline",
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        request_id="req-outline-retry",
    )
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="Invalid propose_flow arguments: bad shape",
            failure_kind="parse",
        )
    )

    async def _events():
        yield build_status_event(AIBuilderStatus.REPAIRING)

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction",
            return_value=_events(),
        ) as repair,
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_create_intent_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    process_outline.assert_awaited_once()
    retry_config = repair.call_args.args[0].retry_config
    assert isinstance(retry_config, ToolRetryConfig)
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_kind",
        "forced_tool_prompt",
        "process_tool_invocation",
    }


@pytest.mark.asyncio
async def test_proposal_retry_config_finalizes_create_compiled_proposal_with_invocation_context() -> (
    None
):
    submission = _make_submission()
    compiled = _compiled_outline_proposal()
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=compiled)
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )
    tracker = ProposalTurnTelemetry(
        request_id="req-outline-retry-finalize",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    resource_catalog = MagicMock()
    flow = MagicMock()
    invocation = _make_retry_invocation(
        resource_catalog=resource_catalog,
        flow=flow,
        new_messages_start=3,
        arguments={"flow_name": "Retry", "plan_rationale": "Retry", "steps": []},
        assistant_content="Här är mitt korrigerade förslag:",
        assistant_metadata={"planner_telemetry": {"request_id": "req"}},
        tool_call_id="call-outline-retry-finalize",
    )

    requested_output_sections = RequestedOutputSections(
        sections=("Summary", "Findings", "Risks", "Recommendations"),
        confidence="high",
    )
    config = submission._proposal_retry_config(
        target_kind=TargetKind.CREATE,
        assistant_snapshots=None,
        request_id="req-outline-retry-finalize",
        planning_state=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=tracker,
        requested_output_sections=requested_output_sections,
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission."
            "process_create_intent_arguments",
            new=process_outline,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert [event.event for event in result.events] == ["plan"]
    process_outline.assert_awaited_once()
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.turn is invocation.turn
    assert request.conversation is invocation.conversation
    assert request.new_messages_start == 3
    assert request.tool_name == PROPOSE_FLOW_TOOL_NAME
    assert request.target_kind == TargetKind.CREATE
    assert request.arguments is invocation.arguments
    assert request.assistant_content == invocation.assistant_content
    assert request.assistant_metadata is invocation.assistant_metadata
    assert request.tool_call_id == "call-outline-retry-finalize"
    assert request.metadata_tool_call is None
    assert request.compiled is compiled
    assert request.resource_catalog is resource_catalog
    assert request.flow is flow
    assert request.request_id == "req-outline-retry-finalize"
    assert request.usage_tracker is tracker
    assert request.requested_output_sections is requested_output_sections


@pytest.mark.asyncio
async def test_create_propose_flow_self_correction_preserves_unknown_provider_outcome() -> (
    None
):
    litellm_client = AsyncMock()
    submission = _make_submission(litellm_client=litellm_client)
    tool_call = MagicMock()
    tool_call.id = "call_retry"
    tool_call.function.name = PROPOSE_FLOW_TOOL_NAME
    tool_call.function.arguments = "{"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        request_id="req-self-correction",
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
    )

    litellm_client.acompletion = AsyncMock(
        side_effect=RuntimeError("provider unavailable")
    )
    dispatched = submission.dispatch_submission_tool_call(ctx=ctx, tool_call=tool_call)
    assert dispatched is not None
    with pytest.raises(AIBuilderProviderOutcomeUnknownException):
        _ = [event async for event in dispatched]


@pytest.mark.asyncio
async def test_edit_propose_flow_parse_failure_records_proposal_repair_reason() -> None:
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-edit-parse",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.EDIT,
    )
    tool_call = MagicMock()
    tool_call.id = "call-edit"
    tool_call.function.name = PROPOSE_FLOW_TOOL_NAME
    tool_call.function.arguments = "{not-json"
    ctx = _make_context(
        usage_tracker=tracker,
        request_id="req-edit-parse",
        text_content="",
        flow=SimpleNamespace(id=uuid4()),
    )

    async def _repair_events(_request):
        yield build_self_correction_error_event(feedback=None, failure_kind=None)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_tool_self_correction",
        side_effect=_repair_events,
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert [event["event"] for event in events] == ["error"]
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "parse"
    assert telemetry["proposal_repair_invocation_count"] == 1
    assert telemetry["proposal_repair_invocation_reasons"] == ["parse"]


@pytest.mark.asyncio
async def test_edit_propose_flow_does_not_run_create_prerequisites() -> None:
    submission = _make_submission()
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "steps": []},
        tool_call_id="call-edit-no-prerequisites",
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
        new=process_edit,
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(flow=SimpleNamespace(id=uuid4(), steps=[])),
            tool_call=tool_call,
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert [event["event"] for event in events] == ["plan"]
    process_edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_proposal_retry_config_carries_edit_invocation_context() -> None:
    submission = _make_submission()
    assistant_snapshots = {uuid4(): {"name": "Analys"}}
    resource_catalog = MagicMock()
    flow = MagicMock()
    plan_edit_context = MagicMock()
    prior_plan_for_revision = MagicMock()

    config = submission._proposal_retry_config(
        target_kind=TargetKind.EDIT,
        assistant_snapshots=assistant_snapshots,
        request_id="req",
        planning_state=None,
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        usage_tracker=None,
        requested_output_sections=RequestedOutputSections.empty(),
    )

    assert isinstance(config, ToolRetryConfig)
    assert config.target_kind == TargetKind.EDIT
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_kind",
        "forced_tool_prompt",
        "process_tool_invocation",
    }
    assert "valid propose_flow tool call" in config.forced_tool_prompt

    process_edit = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )
    invocation = _make_retry_invocation(
        flow=flow,
        resource_catalog=resource_catalog,
        assistant_metadata={"planner_telemetry": {"request_id": "req"}},
        arguments={"plan_rationale": "Edit", "operations": []},
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
        new=process_edit,
    ):
        result = await config.process_tool_invocation(invocation)

    assert [event.event for event in result.events] == ["plan"]
    process_edit.assert_awaited_once()
    assert process_edit.await_args.kwargs["turn"] is invocation.turn
    assert process_edit.await_args.kwargs["conversation"] is invocation.conversation
    assert process_edit.await_args.kwargs["flow"] is flow
    assert process_edit.await_args.kwargs["assistant_snapshots"] is assistant_snapshots
    assert process_edit.await_args.kwargs["resource_catalog"] is resource_catalog
    assert process_edit.await_args.kwargs["plan_edit_context"] is plan_edit_context
    assert (
        process_edit.await_args.kwargs["prior_plan_for_revision"]
        is prior_plan_for_revision
    )


@pytest.mark.asyncio
async def test_edit_propose_flow_retry_preserves_description_advisory_without_completion() -> (
    None
):
    litellm_client = AsyncMock()
    submission = _make_submission(litellm_client=litellm_client)
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-retry-edit-advisory",
        model="openai/gpt-5.4",
        target_kind=TargetKind.EDIT,
    )
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Old generated description"}),
        advisories=[_description_update_advisory()],
    )
    flow = _flow_with_description("Old generated description")
    config = submission._proposal_retry_config(
        target_kind=TargetKind.EDIT,
        assistant_snapshots=None,
        request_id="req-forced-retry-edit-advisory",
        planning_state=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=tracker,
        requested_output_sections=RequestedOutputSections.empty(),
    )
    invocation = _make_retry_invocation(
        flow=flow,
        arguments={"plan_rationale": "Edit", "operations": []},
    )
    litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text("New generated description")
    )
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=original)
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert [event.event for event in result.events] == ["plan"]
    litellm_client.acompletion.assert_not_awaited()
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is original
    assert request.compiled.content.edit is not None
    assert [advisory.code for advisory in request.compiled.content.edit.advisories] == [
        "flow_description_update_required"
    ]


@pytest.mark.asyncio
async def test_edit_propose_flow_preserves_description_advisory_without_completion() -> (
    None
):
    litellm_client = AsyncMock()
    submission = _make_submission(litellm_client=litellm_client)
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Old generated description"}),
        advisories=[_description_update_advisory()],
    )
    flow = _flow_with_description("Old generated description")
    ctx = _make_context(
        flow=flow,
        text_content="Assistant text",
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
        tool_call_id="call-edit-advisory",
    )
    litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text("New generated description")
    )
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=original)
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(events=(_plan_stream_event(),))
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert [event["event"] for event in events] == ["plan"]
    litellm_client.acompletion.assert_not_awaited()
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is original
    assert request.compiled.content.edit is not None
    assert [advisory.code for advisory in request.compiled.content.edit.advisories] == [
        "flow_description_update_required"
    ]
    assert request.assistant_content == "Assistant text"


@pytest.mark.asyncio
async def test__retry_forced_proposal_after_text_uses_create_target_for_create_mode() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-retry-create",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=4096,
        request_id=tracker.request_id,
        usage_tracker=tracker,
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_forced_tool_retry_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(events=(_plan_stream_event(),))
        ),
    ) as retry_forced_tool:
        result = await submission._retry_forced_proposal_after_text(
            ctx=ctx,
            correction_message_groups=_message_groups(
                [{"role": "system", "content": "Prompt"}]
            ),
            assistant_text="Här är planen.",
        )

    assert result is not None
    assert [event.event for event in result] == ["plan"]
    request = retry_forced_tool.await_args.args[0]
    assert request.retry_config.target_kind == TargetKind.CREATE
    assert request.ctx is ctx
    assert request.truncation_error_phase == AIBuilderErrorPhase.PROPOSAL
    assert "Now call propose_flow" in request.retry_config.forced_tool_prompt


@pytest.mark.asyncio
async def test__retry_forced_proposal_after_text_uses_edit_target_for_edit_mode() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-retry-edit",
        model="openai/gpt-5.4",
        target_kind=TargetKind.EDIT,
    )
    flow = SimpleNamespace(steps=[])
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Redigera flödet")],
        new_messages_start=1,
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=4096,
        request_id=tracker.request_id,
        flow=flow,
        usage_tracker=tracker,
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_forced_tool_retry_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(events=(_plan_stream_event(),))
        ),
    ) as retry_forced_tool:
        result = await submission._retry_forced_proposal_after_text(
            ctx=ctx,
            correction_message_groups=_message_groups(
                [{"role": "system", "content": "Prompt"}]
            ),
            assistant_text="Här är planen.",
        )

    assert result is not None
    assert [event.event for event in result] == ["plan"]
    request = retry_forced_tool.await_args.args[0]
    assert request.retry_config.target_kind == TargetKind.EDIT
    assert request.ctx is ctx
    assert "propose_flow" in request.retry_config.forced_tool_prompt


@pytest.mark.asyncio
async def test_edit_propose_flow_parse_failure_triggers_self_correction() -> None:
    submission = _make_submission()
    tool_call = MagicMock()
    tool_call.id = "call_edit"
    tool_call.function.name = PROPOSE_FLOW_TOOL_NAME
    tool_call.function.arguments = json.dumps(
        {
            "plan_rationale": "Lägg till citerande textsteg.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_type": "text",
                },
                'assumptions:["trasig"]',
            ],
        }
    )
    ctx = _make_context(flow=MagicMock(steps=[MagicMock(step_order=1)]))

    async def _events():
        yield build_status_event(AIBuilderStatus.REPAIRING)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_submission.run_tool_self_correction",
        return_value=_events(),
    ) as repair:
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = _wire_events([event async for event in dispatched])

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    request = repair.call_args.args[0]
    assert "OrderedEditProposal" in request.error_message
    assert request.retry_config.target_kind == TargetKind.EDIT
