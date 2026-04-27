from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_edit_models import FlowEditDraft
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
    MCP_SELECTION_USE_SERVER_PREFIX,
    MCP_SELECTION_WITHOUT,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    BuilderPlan,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
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
    ProposalContext,
    ProposalUsageTracker,
    SubmissionToolHandlerConfig,
    ToolProcessingResult,
    ToolRetryConfig,
    _active_submission_tool_schemas,
    _terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult


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


def _make_context(**overrides) -> ProposalContext:
    defaults = {
        "session_id": uuid4(),
        "conversation": [],
        "new_messages_start": 0,
        "llm_messages": [],
        "tool_schemas": [],
        "litellm_model": "openai/gpt-5.4",
        "litellm_kwargs": {},
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "max_output_tokens": 4096,
        "request_id": "req-1",
        "flow": None,
        "assistant_snapshots": None,
        "text_content": None,
    }
    defaults.update(overrides)
    return ProposalContext(**defaults)


def _make_response_with_tool_calls(
    *tool_calls: MagicMock,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> SimpleNamespace:
    usage = (
        None
        if prompt_tokens is None and completion_tokens is None and total_tokens is None
        else SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    tool_calls=list(tool_calls),
                    content=None,
                ),
            )
        ],
        usage=usage,
    )


def _make_tool_call(
    name: str, arguments: dict[str, object], tool_call_id: str | None = None
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = tool_call_id or f"call_{uuid4().hex[:8]}"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


def _make_flow_spec(
    *,
    model_ref: str | None,
    knowledge_refs: list[str],
    mcp_server_refs: list[str] | None = None,
    mcp_tool_refs: list[str] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Grounded flow",
        flow_description="Desc",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(
                    instructions="Gör analysen.",
                    model_ref=model_ref,
                    knowledge_refs=knowledge_refs,
                    mcp_server_refs=mcp_server_refs or [],
                    mcp_tool_refs=mcp_tool_refs or [],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
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


async def _single_plan_event(**_kwargs):
    yield {"event": "plan", "data": "{}"}


def test_plan_edit_output_intent_preserves_prior_document_terminal_type() -> None:
    spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    spec = spec.model_copy(
        update={
            "steps": [spec.steps[0].model_copy(update={"output_type": OutputType.PDF})]
        }
    )
    plan = _make_plan(spec)
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=plan.id,
        target_plan_step_ref="step_a",
    )

    output_type = _terminal_output_type_for_conversation(
        [
            ConversationMessage(
                role="user",
                content="Gör språket mer formellt i den här delen.",
            )
        ],
        plan_edit_context=context,
        prior_plan=plan,
    )

    assert output_type == OutputType.PDF


def test_plan_edit_output_intent_uses_latest_explicit_document_change() -> None:
    spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    plan = _make_plan(spec)
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=plan.id,
        target_plan_step_ref="step_a",
    )

    output_type = _terminal_output_type_for_conversation(
        [
            ConversationMessage(
                role="user",
                content="Ändra slutresultatet så att jag får en PDF-fil.",
            )
        ],
        plan_edit_context=context,
        prior_plan=plan,
    )

    assert output_type == OutputType.PDF


def test_create_submission_schema_keeps_mcp_refs_free_form() -> None:
    schemas = _active_submission_tool_schemas(
        flow=None,
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "server-1",
                "tools": [{"ref": "tool-1", "name": "lookup_case"}],
            }
        ],
    )

    step_props = schemas[0]["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]
    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_proposal_usage_tracker_counts_only_explicit_repair_calls() -> None:
    tracker = ProposalUsageTracker(
        request_id="req-tracker",
        model="openai/gpt-5.4-nano",
    )

    tracker.record_response(
        _make_response_with_tool_calls(
            _make_tool_call(OUTLINE_FLOW_TOOL_NAME, {"flow_name": "Initial"}),
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
        ),
        messages=[{"role": "user", "content": "Build"}],
    )
    tracker.record_response(
        _make_response_with_tool_calls(
            _make_tool_call(OUTLINE_FLOW_TOOL_NAME, {"flow_name": "Auxiliary"}),
            prompt_tokens=4,
            completion_tokens=1,
            total_tokens=5,
        ),
        messages=[{"role": "user", "content": "Auxiliary"}],
    )
    tracker.record_response(
        _make_response_with_tool_calls(
            _make_tool_call(OUTLINE_FLOW_TOOL_NAME, {"flow_name": "Repaired"}),
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
        ),
        messages=[{"role": "user", "content": "Repair"}],
        counts_as_repair=True,
    )

    telemetry = tracker.build_planner_telemetry(tool_call_count=1)

    assert telemetry["llm_calls_made"] == 3
    assert telemetry["repair_attempts"] == 1
    assert telemetry["total_tokens"] == 22


@pytest.mark.asyncio
async def test_request_non_question_continuation_uses_backend_followup_when_only_question_tool_available() -> (
    None
):
    repo = AsyncMock()
    processor = _make_processor(repo=repo)
    repeated_question = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        {
            "question_id": "final_output_mode",
            "question": "Vad ska flödet producera som slutresultat?",
            "options": [
                {"id": "structured_text", "label": "Text"},
                {"id": "pdf_document", "label": "PDF"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        },
    )
    followup_events = [
        {"event": "text", "data": '{"text":"Jag behöver förstå indata bättre."}'},
        {
            "event": "question",
            "data": (
                '{"question_id":"input_material_mode","question":"Vilken typ av underlag ska flödet ta emot?"}'
            ),
        },
    ]

    with (
        patch.object(
            processor,
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=followup_events),
        ) as emit_followup,
        patch.object(
            processor,
            "_call_repair_completion",
            new=AsyncMock(),
        ) as repair_completion,
    ):
        events = [
            event
            async for event in processor.request_non_question_continuation(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(role="user", content="Skapa ett flöde"),
                    ConversationMessage(
                        role="user",
                        content="PDF-dokument",
                        metadata={
                            "question_answer": {
                                "question_id": "final_output_mode",
                                "selected_option_id": "pdf_document",
                                "answer": "pdf_document",
                            }
                        },
                    ),
                ],
                new_messages_start=2,
                llm_messages=[],
                tool_call=repeated_question,
                tool_schemas=[
                    {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}
                ],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                flow=None,
                original_question_id="final_output_mode",
            )
        ]

    assert events == followup_events
    emit_followup.assert_awaited_once()
    repair_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_non_question_continuation_recovers_with_requirements_summary_when_discovery_ready() -> (
    None
):
    processor = _make_processor()
    repeated_question = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        {
            "question_id": "final_output_mode",
            "question": "Vad ska flödet producera som slutresultat?",
            "options": [
                {"id": "structured_text", "label": "Text"},
                {"id": "pdf_document", "label": "PDF"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        },
    )
    summary_call = _make_tool_call(
        CONFIRM_REQUIREMENTS_TOOL_NAME,
        {
            "summary": "Ett ljudbaserat transkriberingsflöde som levererar PDF.",
            "key_decisions": [
                {"topic": "Input", "decision": "Ljudfil"},
                {"topic": "Output", "decision": "PDF"},
            ],
            "input_description": "Användaren laddar upp en ljudfil.",
            "output_description": "Flödet producerar en PDF-sammanfattning.",
        },
    )

    async def _handled_events():
        yield {"event": "requirements_summary", "data": "{}"}

    with (
        patch.object(
            processor,
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=[]),
        ) as emit_followup,
        patch.object(
            processor,
            "_call_repair_completion",
            new=AsyncMock(return_value=_make_response_with_tool_calls(summary_call)),
        ) as repair_completion,
        patch.object(
            processor,
            "handle_tool_call",
            return_value=_handled_events(),
        ) as handle_tool_call,
    ):
        events = [
            event
            async for event in processor.request_non_question_continuation(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="Skapa en ljudfil transkriberare samt sammanfattare",
                        metadata={"ui_language": "sv"},
                    ),
                    ConversationMessage(
                        role="user",
                        content="PDF-dokument",
                        metadata={
                            "question_answer": {
                                "question_id": "final_output_mode",
                                "selected_option_id": "pdf_document",
                                "answer": "pdf_document",
                            },
                            "ui_language": "sv",
                        },
                    ),
                ],
                new_messages_start=2,
                llm_messages=[],
                tool_call=repeated_question,
                tool_schemas=[
                    {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}
                ],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                flow=None,
                original_question_id="final_output_mode",
            )
        ]

    assert [event["event"] for event in events] == ["status", "requirements_summary"]
    assert events[0]["data"] == '{"status":"repairing"}'
    emit_followup.assert_awaited_once()
    handle_tool_call.assert_called_once()
    assert repair_completion.await_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME},
    }
    assert [
        schema["function"]["name"]
        for schema in repair_completion.await_args.kwargs["tool_schemas"]
    ] == [CONFIRM_REQUIREMENTS_TOOL_NAME]


@pytest.mark.asyncio
async def test_request_non_question_continuation_returns_typed_error_when_no_followup_exists() -> (
    None
):
    processor = _make_processor()
    repeated_question = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        {
            "question_id": "processing_scope",
            "question": "Hur ska flödet arbeta?",
            "options": [
                {"id": "single_case", "label": "Ett ärende åt gången"},
                {"id": "batch_cases", "label": "Många ärenden"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        },
    )

    with (
        patch.object(
            processor,
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=[]),
        ) as emit_followup,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.analyze_discovery_ready",
            return_value=False,
        ),
        patch.object(
            processor,
            "_call_repair_completion",
            new=AsyncMock(),
        ) as repair_completion,
    ):
        events = [
            event
            async for event in processor.request_non_question_continuation(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[],
                tool_call=repeated_question,
                tool_schemas=[
                    {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}
                ],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                flow=None,
                original_question_id="processing_scope",
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "question_recovery_unavailable"
    emit_followup.assert_awaited_once()
    repair_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_known_tool_call_routes_structured_question_handler() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.name = ASK_STRUCTURED_QUESTION_TOOL_NAME
    ctx = _make_context()

    async def _events():
        yield {"event": "question", "data": "{}"}

    with patch.object(
        processor,
        "_handle_structured_question",
        return_value=_events(),
    ) as handle_structured_question:
        dispatched = processor._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "question", "data": "{}"}]
    handle_structured_question.assert_called_once_with(ctx=ctx, tool_call=tool_call)


@pytest.mark.asyncio
async def test_dispatch_known_tool_call_routes_outline_flow_handler() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.name = OUTLINE_FLOW_TOOL_NAME
    ctx = _make_context()

    async def _events():
        yield {"event": "plan", "data": "{}"}

    with patch.object(
        processor,
        "_handle_outline_flow_tool_call",
        return_value=_events(),
    ) as handle_outline_flow:
        dispatched = processor._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "plan", "data": "{}"}]
    handle_outline_flow.assert_called_once_with(ctx=ctx, tool_call=tool_call)


@pytest.mark.asyncio
async def test_propose_plan_create_mode_forces_outline_flow_only() -> None:
    processor = _make_processor()
    outline_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Document analysis",
            "plan_rationale": "Analyze the document and produce a summary.",
            "runtime_input": {"input_type": "document", "required": True},
            "final_output_type": "text",
            "steps": [{"name": "Analyze", "task": "Analyze the document."}],
        },
    )

    async def _handled_events(**_kwargs):
        yield {"event": "plan", "data": "{}"}

    with (
        patch.object(
            processor,
            "_call_repair_completion",
            new=AsyncMock(return_value=_make_response_with_tool_calls(outline_call)),
        ) as call_completion,
        patch.object(
            processor,
            "handle_tool_call",
            side_effect=_handled_events,
        ) as handle_tool_call,
    ):
        events = [
            event
            async for event in processor.propose_plan(
                session_id=uuid4(),
                conversation=[ConversationMessage(role="user", content="Build a flow")],
                new_messages_start=1,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-propose",
                flow=None,
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    assert call_completion.await_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": OUTLINE_FLOW_TOOL_NAME},
    }
    assert [
        schema["function"]["name"]
        for schema in call_completion.await_args.kwargs["tool_schemas"]
    ] == [OUTLINE_FLOW_TOOL_NAME]
    assert handle_tool_call.call_args.kwargs["tool_calls"] == [outline_call]
    assert [
        schema["function"]["name"]
        for schema in handle_tool_call.call_args.kwargs["tool_schemas"]
    ] == [OUTLINE_FLOW_TOOL_NAME]


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
            session_id=session_id,
            conversation=conversation,
            new_messages_start=0,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=catalog,
            max_output_tokens=4096,
            proposal_temperature=0.2,
            request_id="req-propose",
            flow=None,
            lease_request_id=uuid4(),
            lease_lock_token=uuid4(),
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
            session_id=uuid4(),
            conversation=conversation,
            new_messages_start=0,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
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
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Time fallback",
            "plan_rationale": "Respond without external tools.",
            "steps": [{"name": "Answer", "task": "Build a response without MCP."}],
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

    with patch.object(
        processor,
        "handle_tool_call",
        side_effect=_single_plan_event,
    ) as handle_tool_call:
        events = [
            event
            async for event in processor.propose_plan(
                session_id=uuid4(),
                conversation=conversation,
                new_messages_start=2,
                llm_messages=[{"role": "system", "content": "Prompt"}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
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
    assert handle_tool_call.call_args.kwargs["tool_calls"] == [outline_call]


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
            session_id=uuid4(),
            conversation=conversation,
            new_messages_start=2,
            llm_messages=[{"role": "system", "content": "Prompt"}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
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
        f"{MCP_SELECTION_USE_SERVER_PREFIX}time-server",
    ]
    assert not processor.litellm_client.acompletion.await_count


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

    result = await processor._process_outline_arguments(
        session_id=uuid4(),
        conversation=conversation,
        new_messages_start=0,
        arguments={
            "flow_name": "Time flow",
            "plan_rationale": "Use MCP despite the user's decline.",
            "steps": [
                {
                    "name": "Hämta tid",
                    "task": "Hämta aktuell tid via Time MCP.",
                    "mcp_tool_refs": ["current-time"],
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
async def test_handle_submission_tool_call_runs_processor_once_with_flow_context() -> (
    None
):
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call-edit"
    tool_call.function.arguments = "{}"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        flow=SimpleNamespace(id=uuid4()),
        text_content="Här är planen.",
        request_id="req-edit-once",
    )
    process_tool_arguments = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
        return_value=SimpleNamespace(confirmed=True),
    ):
        events = [
            event
            async for event in processor._handle_submission_tool_call(
                ctx=ctx,
                tool_call=tool_call,
                config=SubmissionToolHandlerConfig(
                    target_tool_name=EDIT_FLOW_TOOL_NAME,
                    requirements_not_confirmed_message="Requirements must be confirmed before editing a flow.",
                    parse_error_prefix="Invalid edit_flow arguments",
                    invalid_result_message="Invalid edit_flow draft.",
                    forced_tool_prompt="Now call edit_flow.",
                    process_tool_arguments=process_tool_arguments,
                    include_flow_context=True,
                ),
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    process_tool_arguments.assert_awaited_once()
    assert process_tool_arguments.await_args.kwargs["flow"] is ctx.flow


@pytest.mark.asyncio
async def test_handle_submission_tool_call_omits_flow_context_by_default() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call-create"
    tool_call.function.arguments = "{}"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        flow=SimpleNamespace(id=uuid4()),
        text_content="Här är planen.",
        request_id="req-create-once",
    )
    process_tool_arguments = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
        return_value=SimpleNamespace(confirmed=True),
    ):
        events = [
            event
            async for event in processor._handle_submission_tool_call(
                ctx=ctx,
                tool_call=tool_call,
                config=SubmissionToolHandlerConfig(
                    target_tool_name=OUTLINE_FLOW_TOOL_NAME,
                    requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
                    parse_error_prefix="Invalid outline_flow arguments",
                    invalid_result_message="Invalid outline_flow draft.",
                    forced_tool_prompt="Now call outline_flow.",
                    process_tool_arguments=process_tool_arguments,
                ),
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    process_tool_arguments.assert_awaited_once()
    assert "flow" not in process_tool_arguments.await_args.kwargs


@pytest.mark.asyncio
async def test_propose_plan_persists_initial_proposal_token_usage() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Simple flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "task": "Classify the request."}],
        },
        tool_call_id="call-outline",
    )
    processor.litellm_client.acompletion.return_value = _make_response_with_tool_calls(
        tool_call,
        prompt_tokens=10,
        completion_tokens=7,
        total_tokens=17,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch.object(
            processor,
            "_process_outline_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
            ),
        ) as process_outline,
    ):
        events = [
            event
            async for event in processor.propose_plan(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[{"role": "user", "content": "Bygg ett flöde"}],
                litellm_model="openai/gpt-5.4-nano",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-proposal-usage",
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    metadata = process_outline.await_args.kwargs["assistant_metadata"]
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["request_id"] == "req-proposal-usage"
    assert planner_telemetry["model"] == "openai/gpt-5.4-nano"
    assert planner_telemetry["prompt_tokens"] == 10
    assert planner_telemetry["completion_tokens"] == 7
    assert planner_telemetry["total_tokens"] == 17
    assert planner_telemetry["llm_calls_made"] == 1
    assert planner_telemetry["token_usage_source"] == "provider"
    assert planner_telemetry["token_usage_estimated"] is False
    session_telemetry = metadata["session_telemetry"]
    assert session_telemetry["total_tokens_total"] == 17
    assert session_telemetry["last_token_usage_source"] == "provider"


@pytest.mark.asyncio
async def test_propose_plan_persists_aggregate_token_usage_after_repair() -> None:
    processor = _make_processor()
    failed_tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {"flow_name": "Broken"},
        tool_call_id="call-outline-bad",
    )
    repaired_tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Repaired flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "task": "Classify the request."}],
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

    async def process_outline(**kwargs) -> ToolProcessingResult:
        captured_metadata.append(kwargs.get("assistant_metadata"))
        if len(captured_metadata) == 1:
            return ToolProcessingResult(
                feedback="Invalid outline.",
                failure_kind="parse",
            )
        return ToolProcessingResult(event={"event": "plan", "data": "{}"})

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch.object(
            processor,
            "_process_outline_arguments",
            new=process_outline,
        ),
    ):
        events = [
            event
            async for event in processor.propose_plan(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                llm_messages=[{"role": "user", "content": "Bygg ett flöde"}],
                litellm_model="openai/gpt-5.4-nano",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                proposal_temperature=0.2,
                request_id="req-proposal-repair-usage",
            )
        ]

    assert [event["event"] for event in events] == ["status", "plan"]
    metadata = captured_metadata[1]
    assert isinstance(metadata, dict)
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["prompt_tokens"] == 14
    assert planner_telemetry["completion_tokens"] == 10
    assert planner_telemetry["total_tokens"] == 24
    assert planner_telemetry["llm_calls_made"] == 2
    assert planner_telemetry["repair_attempts"] == 1
    assert planner_telemetry["token_usage_source"] == "provider"
    assert metadata["session_telemetry"]["total_tokens_total"] == 24


@pytest.mark.asyncio
async def test_outline_retry_does_not_preserve_failed_attempt_step_count() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Document analysis",
            "plan_rationale": "Analyze documents.",
            "steps": [
                {"name": "Read", "task": "Read the material."},
                {"name": "Extract", "task": "Extract key facts."},
                {"name": "Compare", "task": "Compare findings."},
                {"name": "Report", "task": "Create the report."},
            ],
        },
        tool_call_id="call-outline",
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        request_id="req-outline-retry",
    )
    process_tool_arguments = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="Invalid outline_flow arguments: bad shape",
            failure_kind="parse",
        )
    )

    async def _events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch.object(
            processor,
            "_request_tool_self_correction",
            return_value=_events(),
        ) as repair,
    ):
        events = [
            event
            async for event in processor._handle_submission_tool_call(
                ctx=ctx,
                tool_call=tool_call,
                config=SubmissionToolHandlerConfig(
                    target_tool_name=OUTLINE_FLOW_TOOL_NAME,
                    requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
                    parse_error_prefix="Invalid outline_flow arguments",
                    invalid_result_message="Invalid outline_flow draft.",
                    forced_tool_prompt="Now call outline_flow.",
                    process_tool_arguments=process_tool_arguments,
                ),
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    retry_config = repair.call_args.kwargs["retry_config"]
    assert retry_config.process_tool_kwargs == {"planning_state": None}


@pytest.mark.asyncio
async def test_process_edit_arguments_retries_on_contextual_quality_feedback() -> None:
    processor = _make_processor()
    flow = MagicMock()
    flow.steps = []
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar PDF idag."
    flow.metadata_json = {}

    draft = FlowEditDraft.model_validate(
        {
            "plan_rationale": "Byt bara slutformatet.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "docx"},
                }
            ],
        }
    )
    edit_result = MagicMock(
        compiled_spec=_make_flow_spec(model_ref=None, knowledge_refs=[])
    )
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=edit_result.compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
        patch.object(
            processor,
            "_format_contextual_quality_feedback",
            return_value=(
                "Quality issues:\n"
                "Konversationen efterfrågar genererad DOCX utan mall, men planen använder fortfarande "
                '`output_mode="template_fill"`.'
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
            return_value=(MagicMock(), MagicMock()),
        ) as store_plan,
    ):
        result = await processor._process_edit_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_edit",
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            max_output_tokens=1024,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert result.feedback is not None
    assert "template_fill" in result.feedback
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_edit_arguments_asks_before_accepting_mcp_usage() -> None:
    processor = _make_processor()
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

    draft = FlowEditDraft.model_validate(
        {
            "plan_rationale": "Lägg till ett tidsteg.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "json"},
                }
            ],
        }
    )
    compiled_spec = _make_flow_spec(
        model_ref=None,
        knowledge_refs=[],
        mcp_tool_refs=["current-time"],
    )
    edit_result = MagicMock(compiled_spec=compiled_spec, advisories=[])
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ) as prepare_spec,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
        ) as store_plan,
    ):
        result = await processor._process_edit_arguments(
            session_id=uuid4(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Lägg till ett steg som använder Time MCP.",
                    metadata={"ui_language": "sv"},
                )
            ],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_edit",
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            max_output_tokens=1024,
            resource_catalog=catalog,
        )

    assert [event["event"] for event in result.iter_events()] == ["text", "question"]
    question_payload = json.loads(result.iter_events()[1]["data"])
    assert question_payload["question_id"] == MCP_RESOURCE_SELECTION_QUESTION_ID
    assert [option["value"] for option in question_payload["options"]] == [
        MCP_SELECTION_WITHOUT,
        f"{MCP_SELECTION_USE_SERVER_PREFIX}time-server",
    ]
    assert prepare_spec.call_args.kwargs["resource_catalog"] is catalog
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_edit_arguments_enforces_without_mcp_selection() -> None:
    processor = _make_processor()
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

    draft = FlowEditDraft.model_validate(
        {
            "plan_rationale": "Lägg till ett tidsteg.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "json"},
                }
            ],
        }
    )
    compiled_spec = _make_flow_spec(
        model_ref=None,
        knowledge_refs=[],
        mcp_tool_refs=["current-time"],
    )
    edit_result = MagicMock(compiled_spec=compiled_spec, advisories=[])
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
        ) as store_plan,
    ):
        result = await processor._process_edit_arguments(
            session_id=uuid4(),
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
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_edit",
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            max_output_tokens=1024,
            resource_catalog=catalog,
        )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert result.feedback is not None
    assert "continue without MCP" in result.feedback
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_edit_arguments_passes_metadata_to_edit_validator() -> None:
    processor = _make_processor()
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

    draft = FlowEditDraft.model_validate(
        {
            "plan_rationale": "Byt bara slutformatet.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "docx"},
                }
            ],
        }
    )
    edit_result = MagicMock(
        compiled_spec=_make_flow_spec(model_ref=None, knowledge_refs=[])
    )
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=edit_result.compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_edit_draft",
            return_value=SpecValidationResult(),
        ) as validate_edit,
        patch.object(
            processor,
            "_format_contextual_quality_feedback",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.build_plan_event",
            return_value={"event": "plan", "data": "{}"},
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
            return_value=(MagicMock(), MagicMock()),
        ) as store_plan,
    ):
        await processor._process_edit_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_edit",
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            max_output_tokens=1024,
            resource_catalog=None,
        )

    assert validate_edit.call_args is not None
    assert validate_edit.call_args.kwargs["current_metadata_json"] == flow.metadata_json
    store_plan.assert_awaited_once()
    assert store_plan.await_args is not None
    assert store_plan.await_args.kwargs["flow"] is flow


@pytest.mark.asyncio
async def test_process_edit_arguments_normalizes_mechanical_refs_before_validation() -> (
    None
):
    processor = _make_processor()
    flow = MagicMock()
    flow.steps = [
        MagicMock(
            step_order=1,
            output_type="json",
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        MagicMock(step_order=2, output_type="text", output_contract=None),
    ]
    flow.draft_revision = 7
    flow.name = "Rapportflöde"
    flow.description = "Skapar rapport."
    flow.metadata_json = {
        "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
    }
    arguments = {
        "plan_rationale": "Uppdatera kopplingar.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_2",
                "patch": {
                    "uses_previous_fields": [
                        {"from_step": 1, "field_path": "summary"},
                        {"from_step": 1, "field_path": "invented"},
                    ],
                    "uses_form_fields": ["case_id", "invented_field"],
                },
            }
        ],
    }
    edit_result = MagicMock(
        compiled_spec=_make_flow_spec(model_ref=None, knowledge_refs=[])
    )
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=edit_result.compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_edit_draft",
            return_value=SpecValidationResult(),
        ) as validate_edit,
        patch.object(
            processor,
            "_format_contextual_quality_feedback",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.build_plan_event",
            return_value={"event": "plan", "data": "{}"},
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        await processor._process_edit_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=arguments,
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_edit",
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            max_output_tokens=1024,
            resource_catalog=None,
        )

    assert validate_edit.call_args is not None
    normalized_draft = validate_edit.call_args.args[0]
    patch_payload = normalized_draft.operations[0].patch
    assert patch_payload is not None
    assert [
        (ref.from_step, ref.field_path) for ref in patch_payload.uses_previous_fields
    ] == [
        (1, "summary"),
    ]
    assert patch_payload.uses_form_fields == ["case_id"]


@pytest.mark.asyncio
async def test_handle_tool_call_builds_proposal_context_for_edit_handler() -> None:
    processor = _make_processor()
    flow = MagicMock()
    snapshots = {uuid4(): {"name": "Assistant"}}
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {
            "plan_rationale": "Byt slutformatet.",
            "operations": [],
        },
    )
    captured_ctx: ProposalContext | None = None

    def _edit_handler(*, ctx: ProposalContext, tool_call: MagicMock):
        nonlocal captured_ctx
        captured_ctx = ctx

        async def _events():
            yield {"event": "done", "data": ""}

        return _events()

    with patch.object(
        processor,
        "_handle_edit_flow",
        side_effect=_edit_handler,
    ) as handle_edit:
        events = [
            event
            async for event in processor.handle_tool_call(
                session_id=uuid4(),
                conversation=[],
                new_messages_start=0,
                tool_calls=[tool_call],
                text_content="draft",
                llm_messages=[{"role": "system", "content": "Prompt"}],
                tool_schemas=[{"function": {"name": EDIT_FLOW_TOOL_NAME}}],
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
    assert captured_ctx.text_content == "draft"
    assert captured_ctx.flow is flow
    assert captured_ctx.assistant_snapshots == snapshots
    handle_edit.assert_called_once()


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

    def _question_handler(*, ctx: ProposalContext, tool_call: MagicMock):
        async def _events():
            yield {"event": "done", "data": ""}

        return _events()

    with patch.object(
        processor,
        "_handle_structured_question",
        side_effect=_question_handler,
    ):
        events = [
            event
            async for event in processor.handle_tool_call(
                session_id=uuid4(),
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
async def test_request_self_correction_returns_typed_error_when_repair_completion_raises() -> (
    None
):
    processor = _make_processor()
    tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Utredningsflöde",
            "plan_rationale": "Kort plan.",
            "steps": [],
        },
        tool_call_id="call_retry",
    )

    with patch.object(
        processor,
        "_call_repair_completion",
        new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
    ):
        events = [
            event
            async for event in processor.request_self_correction(
                session_id=uuid4(),
                conversation=[
                    ConversationMessage(role="user", content="Bygg ett flöde")
                ],
                new_messages_start=1,
                error_message="Invalid flow specification: missing steps",
                llm_messages=[{"role": "system", "content": "Prompt"}],
                tool_call=tool_call,
                tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
                max_output_tokens=4096,
                flow=None,
            )
        ]

    assert [event["event"] for event in events] == ["status", "error"]
    error_payload = json.loads(events[1]["data"])
    assert error_payload["code"] == "planner_upstream_error"
    assert error_payload["phase"] == "self_correction"


@pytest.mark.asyncio
async def test_submission_retry_config_returns_typed_create_retry_config() -> None:
    processor = _make_processor()

    config = processor._submission_retry_config(
        flow=None,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=4096,
    )

    assert isinstance(config, ToolRetryConfig)
    assert config.target_tool_name == OUTLINE_FLOW_TOOL_NAME
    assert config.process_tool_arguments == processor._process_outline_arguments
    assert config.process_tool_kwargs == {}
    assert "Now call outline_flow" in config.forced_tool_prompt


@pytest.mark.asyncio
async def test_submission_retry_config_returns_typed_edit_retry_config() -> None:
    processor = _make_processor()
    assistant_snapshots = {uuid4(): {"name": "Analys"}}
    resource_catalog = MagicMock()

    config = processor._submission_retry_config(
        flow=MagicMock(),
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
        assistant_snapshots=assistant_snapshots,
        resource_catalog=resource_catalog,
    )

    assert isinstance(config, ToolRetryConfig)
    assert config.target_tool_name == EDIT_FLOW_TOOL_NAME
    assert config.process_tool_arguments == processor._process_edit_arguments
    assert config.process_tool_kwargs == {
        "assistant_snapshots": assistant_snapshots,
        "litellm_model": "openai/gpt-5.4",
        "litellm_kwargs": {"timeout": 30},
        "max_output_tokens": 2048,
        "resource_catalog": resource_catalog,
    }
    assert "valid edit_flow tool call" in config.forced_tool_prompt


@pytest.mark.asyncio
async def test_retry_forced_proposal_after_text_uses_outline_flow_for_create_mode() -> (
    None
):
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.run_retry_forced_tool_after_text",
        new=AsyncMock(return_value={"event": "plan", "data": "{}"}),
    ) as retry_forced_tool:
        result = await processor.retry_forced_proposal_after_text(
            correction_messages=[{"role": "system", "content": "Prompt"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            session_id=uuid4(),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            max_output_tokens=4096,
            flow=None,
        )

    assert result == {"event": "plan", "data": "{}"}
    kwargs = retry_forced_tool.await_args.kwargs
    assert kwargs["target_tool_name"] == OUTLINE_FLOW_TOOL_NAME
    assert kwargs["process_tool_arguments"] == processor._process_outline_arguments
    assert "Now call outline_flow" in kwargs["forced_tool_prompt"]


@pytest.mark.asyncio
async def test_handle_edit_flow_parse_failure_triggers_self_correction() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_edit"
    tool_call.function.name = EDIT_FLOW_TOOL_NAME
    tool_call.function.arguments = json.dumps(
        {
            "plan_rationale": "Lägg till citerande textsteg.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {"output_type": "text"},
                },
                'assumptions:["trasig"]',
            ],
        }
    )
    ctx = _make_context(flow=MagicMock(steps=[MagicMock(step_order=1)]))

    async def _events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with patch.object(
        processor,
        "_request_tool_self_correction",
        return_value=_events(),
    ) as repair:
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    assert "StepEditOperation" in repair.call_args.kwargs["error_message"]
    assert (
        repair.call_args.kwargs["retry_config"].target_tool_name == EDIT_FLOW_TOOL_NAME
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

    with patch.object(
        processor,
        "_request_tool_self_correction",
        return_value=_events(),
    ) as repair:
        events = [
            event
            async for event in processor._handle_confirm_requirements(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    assert "Invalid requirements summary" in repair.call_args.kwargs["error_message"]
    assert (
        repair.call_args.kwargs["retry_config"].target_tool_name
        == CONFIRM_REQUIREMENTS_TOOL_NAME
    )
