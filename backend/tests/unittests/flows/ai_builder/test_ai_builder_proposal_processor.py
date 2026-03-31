from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
    ProposalContext,
)


def _make_processor(**overrides) -> AIBuilderProposalProcessor:
    defaults = {
        "user": MagicMock(tenant_id=uuid4()),
        "repo": AsyncMock(),
        "litellm_client": AsyncMock(),
        "self_correction_temperature": 0.2,
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
        "max_output_tokens": 4096,
        "request_id": "req-1",
        "flow": None,
        "assistant_snapshots": None,
        "text_content": None,
    }
    defaults.update(overrides)
    return ProposalContext(**defaults)


def _make_response_with_tool_calls(*tool_calls: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=list(tool_calls),
                    content=None,
                )
            )
        ]
    )


def _make_tool_call(
    name: str, arguments: dict[str, object], tool_call_id: str | None = None
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = tool_call_id or f"call_{uuid4().hex[:8]}"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


@pytest.mark.asyncio
async def test_process_proposal_arguments_returns_parse_feedback() -> None:
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.parse_propose_flow_arguments",
        side_effect=ValueError("missing steps"),
    ):
        result = await processor._process_proposal_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments={"flow_name": "Broken"},
            assistant_content="draft",
            tool_call_id="call_parse",
            available_model_refs=None,
            available_kb_refs=None,
        )

    assert result.plan_event is None
    assert result.failure_kind == "parse"
    assert result.feedback == "Invalid flow specification: missing steps"


@pytest.mark.asyncio
async def test_process_proposal_arguments_returns_quality_feedback_without_storing() -> None:
    processor = _make_processor()
    spec = SimpleNamespace(steps=[])
    validation = SimpleNamespace(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_propose_flow_arguments",
            return_value=spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_assumptions",
            return_value=["assumption"],
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_reasoning",
            return_value="reasoning",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_plan_rationale",
            return_value="rationale",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_spec",
            return_value=validation,
        ),
        patch.object(processor, "_format_quality_feedback", return_value="Quality issue"),
        patch.object(processor, "_format_contextual_quality_feedback", return_value=None),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
        ) as store_plan,
    ):
        result = await processor._process_proposal_arguments(
            session_id=uuid4(),
            conversation=[ConversationMessage(role="user", content="Build a flow")],
            new_messages_start=1,
            arguments={"flow_name": "Quality"},
            assistant_content="draft",
            tool_call_id="call_quality",
            available_model_refs=None,
            available_kb_refs=None,
        )

    assert result.plan_event is None
    assert result.failure_kind == "quality"
    assert result.feedback == "Quality issue"
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_proposal_arguments_stores_plan_and_returns_event() -> None:
    processor = _make_processor()
    spec = SimpleNamespace(steps=[])
    validation = SimpleNamespace(valid=True, errors=[])
    plan = SimpleNamespace(id=uuid4())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_propose_flow_arguments",
            return_value=spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_assumptions",
            return_value=["assumption"],
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_reasoning",
            return_value="reasoning",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_plan_rationale",
            return_value="rationale",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_spec",
            return_value=validation,
        ),
        patch.object(processor, "_format_quality_feedback", return_value=None),
        patch.object(processor, "_format_contextual_quality_feedback", return_value=None),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.build_plan_event",
            return_value={"event": "plan", "data": "{}"},
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
            return_value=(plan, {"foo": "bar"}),
        ) as store_plan,
    ):
        result = await processor._process_proposal_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments={"flow_name": "Stored"},
            assistant_content="draft",
            tool_call_id="call_store",
            available_model_refs=None,
            available_kb_refs=None,
        )

    assert result.failure_kind is None
    assert result.plan_event is not None
    assert result.plan_event["event"] == "plan"
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_proposal_arguments_strips_create_mode_existing_step_ref_before_store() -> None:
    processor = _make_processor()
    spec = SimpleNamespace(
        flow_name="Stored",
        steps=[
            SimpleNamespace(
                plan_step_ref="step_a",
                existing_step_ref="step_a",
            )
        ],
    )
    validation = SimpleNamespace(valid=True, errors=[])
    plan = SimpleNamespace(id=uuid4())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_propose_flow_arguments",
            return_value=spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_assumptions",
            return_value=["assumption"],
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_reasoning",
            return_value="reasoning",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.extract_plan_rationale",
            return_value="rationale",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.normalize_compiled_spec_for_session",
            side_effect=lambda draft, *, target_kind: SimpleNamespace(
                flow_name=draft.flow_name,
                steps=[
                    SimpleNamespace(
                        plan_step_ref="step_a",
                        existing_step_ref=None,
                    )
                ],
            ),
        ) as normalize_spec,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_spec",
            return_value=validation,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_compiled_spec_for_session",
            return_value=SimpleNamespace(errors=[]),
        ),
        patch.object(processor, "_format_quality_feedback", return_value=None),
        patch.object(processor, "_format_contextual_quality_feedback", return_value=None),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.build_plan_event",
            return_value={"event": "plan", "data": "{}"},
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
            return_value=(plan, {"foo": "bar"}),
        ) as store_plan,
    ):
        result = await processor._process_proposal_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments={"flow_name": "Stored"},
            assistant_content="draft",
            tool_call_id="call_store",
            available_model_refs=None,
            available_kb_refs=None,
        )

    assert result.failure_kind is None
    normalize_spec.assert_called_once()
    stored_spec = store_plan.await_args.kwargs["spec"]
    assert stored_spec.steps[0].existing_step_ref is None


@pytest.mark.asyncio
async def test_request_non_question_continuation_uses_backend_followup_when_only_question_tool_available() -> None:
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
                tool_schemas=[{"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                max_output_tokens=4096,
                flow=None,
                original_question_id="final_output_mode",
            )
        ]

    assert events == followup_events
    emit_followup.assert_awaited_once()
    repair_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_non_question_continuation_recovers_with_requirements_summary_when_discovery_ready() -> None:
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
                tool_schemas=[{"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
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
        schema["function"]["name"] for schema in repair_completion.await_args.kwargs["tool_schemas"]
    ] == [CONFIRM_REQUIREMENTS_TOOL_NAME]


@pytest.mark.asyncio
async def test_request_non_question_continuation_returns_typed_error_when_no_followup_exists() -> None:
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
                conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
                new_messages_start=1,
                llm_messages=[],
                tool_call=repeated_question,
                tool_schemas=[{"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
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
async def test_handle_tool_call_builds_proposal_context_for_proposal_handler() -> None:
    processor = _make_processor()
    flow = MagicMock()
    snapshots = {uuid4(): {"name": "Assistant"}}
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
            "flow_name": "Draft",
            "steps": [],
        },
    )
    captured_ctx: ProposalContext | None = None

    def _proposal_handler(*, ctx: ProposalContext, tool_call: MagicMock):
        nonlocal captured_ctx
        captured_ctx = ctx

        async def _events():
            yield {"event": "done", "data": ""}

        return _events()

    with (
        patch.object(
            processor,
            "_dispatch_known_tool_call",
            return_value=None,
        ),
        patch.object(
            processor,
            "_handle_propose_flow_tool_call",
            side_effect=_proposal_handler,
        ) as handle_propose,
    ):
        events = [
            event
            async for event in processor.handle_tool_call(
                session_id=uuid4(),
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

    assert events == [{"event": "text", "data": '{"text":"draft"}'}, {"event": "done", "data": ""}]
    assert captured_ctx is not None
    assert captured_ctx.request_id == "req-ctx"
    assert captured_ctx.text_content == "draft"
    assert captured_ctx.flow is flow
    assert captured_ctx.assistant_snapshots == snapshots
    handle_propose.assert_called_once()


def test_build_tool_retry_messages_appends_assistant_tool_call_and_feedback() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "propose_flow"
    tool_call.function.arguments = '{"flow_name":"Draft"}'

    messages = processor._build_tool_retry_messages(
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_call=tool_call,
        tool_feedback="Please fix the draft.",
    )

    assert messages[0] == {"role": "system", "content": "Prompt"}
    assert messages[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "propose_flow",
                "arguments": '{"flow_name":"Draft"}',
            },
        }],
    }
    assert messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "Please fix the draft.",
    }


@pytest.mark.asyncio
async def test_request_self_correction_returns_typed_error_when_repair_completion_raises() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        "propose_flow",
        {
            "flow_name": "Utredningsflöde",
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
                conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
                new_messages_start=1,
                error_message="Invalid flow specification: missing steps",
                llm_messages=[{"role": "system", "content": "Prompt"}],
                tool_call=tool_call,
                tool_schemas=[{"function": {"name": "propose_flow"}}],
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                max_output_tokens=4096,
                flow=None,
            )
        ]

    assert [event["event"] for event in events] == ["status", "error"]
    error_payload = json.loads(events[1]["data"])
    assert error_payload["code"] == "planner_upstream_error"
    assert error_payload["phase"] == "self_correction"


@pytest.mark.asyncio
async def test_persist_tool_turn_appends_messages_and_persists_new_slice() -> None:
    repo = AsyncMock()
    processor = _make_processor(repo=repo)
    tool_call = MagicMock()
    tool_call.id = "call_2"
    tool_call.function.name = "confirm_requirements"
    conversation = [ConversationMessage(role="user", content="Build a document flow")]

    await processor._persist_tool_turn(
        session_id=uuid4(),
        conversation=conversation,
        new_messages_start=1,
        tool_call=tool_call,
        arguments={"summary": "A document flow"},
        tool_content="Requirements presented to user. Awaiting confirmation.",
        metadata={"requirements_version": "req-v1"},
    )

    assert conversation[-2] == ConversationMessage(
        role="assistant",
        content=None,
        tool_calls=[{
            "id": "call_2",
            "name": "confirm_requirements",
            "arguments": {"summary": "A document flow"},
        }],
    )
    assert conversation[-1] == ConversationMessage(
        role="tool",
        content="Requirements presented to user. Awaiting confirmation.",
        tool_call_id="call_2",
        metadata={"requirements_version": "req-v1"},
    )
    repo.append_session_messages.assert_awaited_once()
