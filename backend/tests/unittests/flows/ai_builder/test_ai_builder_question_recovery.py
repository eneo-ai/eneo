from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
    DiscoveryAnalysis,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_event_models import StructuredQuestionPayload
from intric.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from intric.flows.ai_builder.ai_builder_question_recovery import (
    RecoveredToolDispatchRequest,
    StructuredQuestionRecoveryRequest,
    stream_structured_question_tool_call,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
)
from intric.flows.ai_builder.planning_state import PlanningState


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=0,
    )


def _make_tool_call(
    name: str,
    arguments: dict[str, object],
    *,
    tool_call_id: str | None = None,
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = tool_call_id or f"call_{uuid4().hex[:8]}"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


def _make_response_with_tool_calls(*tool_calls: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=list(tool_calls),
                    content=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


def _make_response_with_text(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=None,
                    content=content,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


def _question_payload(question_id: str = "final_output_mode") -> dict[str, object]:
    return {
        "question_id": question_id,
        "question": "Vad ska flödet producera som slutresultat?",
        "options": [
            {"id": "structured_text", "label": "Text"},
            {"id": "pdf_document", "label": "PDF"},
        ],
        "selection_mode": "single",
        "allow_custom": True,
    }


def _conversation_with_answered_final_output_mode() -> list[ConversationMessage]:
    return [
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
    ]


def _make_request(
    *,
    tool_call: MagicMock | None = None,
    tool_schemas: list[dict[str, object]] | None = None,
    conversation: list[ConversationMessage] | None = None,
    usage_tracker: ProposalTurnTelemetry | None = None,
) -> StructuredQuestionRecoveryRequest:
    return StructuredQuestionRecoveryRequest(
        turn=_make_turn(),
        conversation=conversation or [ConversationMessage(role="user", content="Bygg")],
        new_messages_start=len(conversation or []),
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_call=tool_call
        or _make_tool_call(ASK_STRUCTURED_QUESTION_TOOL_NAME, _question_payload()),
        tool_schemas=tool_schemas
        or [{"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=4096,
        flow=None,
        assistant_metadata=None,
        usage_tracker=usage_tracker,
    )


def _runtime_result(followup: BackendQuestion | None = None) -> DiscoveryRuntimeResult:
    return DiscoveryRuntimeResult(
        discovery_block_message=None,
        discovery_analysis=DiscoveryAnalysis(issues=()),
        planning_state=PlanningState.empty(),
        followup=followup,
    )


def _backend_question() -> BackendQuestion:
    return BackendQuestion(
        question_data=StructuredQuestionPayload.model_validate(
            {
                "question_id": "input_material_mode",
                "question": "Vilken typ av underlag ska flödet ta emot?",
                "options": [
                    {
                        "id": "audio",
                        "label": "Ljud",
                        "description": "Spela in eller ladda upp ljud.",
                        "value": "audio",
                    }
                ],
                "selection_mode": "single",
                "allow_custom": True,
            }
        ),
        assistant_text="Jag behöver förstå indata bättre.",
    )


@pytest.mark.asyncio
async def test_question_recovery_uses_backend_followup_when_only_question_tool_available() -> (
    None
):
    repo = AsyncMock()

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result(_backend_question())),
        ) as build_runtime,
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=AsyncMock(),
        ) as proposal_completion,
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=repo,
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(
                    conversation=_conversation_with_answered_final_output_mode()
                ),
            )
        ]

    assert [event["event"] for event in events] == ["text", "question"]
    build_runtime.assert_awaited_once()
    repo.commit_turn.assert_awaited_once()
    proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_question_recovery_recovers_with_requirements_dispatch_when_discovery_ready() -> (
    None
):
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

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(side_effect=[_runtime_result(), _runtime_result()]),
        ) as build_runtime,
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=True,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=AsyncMock(return_value=_make_response_with_tool_calls(summary_call)),
        ) as proposal_completion,
    ):
        items = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(
                    conversation=_conversation_with_answered_final_output_mode()
                ),
            )
        ]

    assert [item["event"] for item in items if isinstance(item, dict)] == ["status"]
    dispatch = next(
        item for item in items if isinstance(item, RecoveredToolDispatchRequest)
    )
    assert dispatch.tool_calls == [summary_call]
    assert dispatch.request_id == "question-recovery"
    assert [schema["function"]["name"] for schema in dispatch.tool_schemas] == [
        CONFIRM_REQUIREMENTS_TOOL_NAME
    ]
    assert proposal_completion.await_args.kwargs["request"].tool_choice == {
        "type": "function",
        "function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME},
    }
    assert build_runtime.await_count == 2


@pytest.mark.asyncio
async def test_question_recovery_returns_typed_error_when_no_followup_exists() -> None:
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(side_effect=[_runtime_result(), _runtime_result()]),
        ) as build_runtime,
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=False,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=AsyncMock(),
        ) as proposal_completion,
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(
                    conversation=_conversation_with_answered_final_output_mode()
                ),
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "question_recovery_unavailable"
    assert build_runtime.await_count == 2
    proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_question_recovery_handles_empty_completion_choices() -> None:
    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=True,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=AsyncMock(return_value=SimpleNamespace(choices=())),
        ),
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(
                    conversation=_conversation_with_answered_final_output_mode()
                ),
            )
        ]

    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "planner_invalid_repair_response"
    assert payload["phase"] == "question_recovery"


@pytest.mark.asyncio
async def test_question_recovery_exhausts_repeated_structured_question_after_retry() -> (
    None
):
    repeated_question = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        _question_payload(),
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=False,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=AsyncMock(
                side_effect=[
                    _make_response_with_tool_calls(repeated_question),
                    _make_response_with_tool_calls(repeated_question),
                ]
            ),
        ) as proposal_completion,
    ):
        items = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(
                    tool_call=repeated_question,
                    conversation=_conversation_with_answered_final_output_mode(),
                    tool_schemas=[
                        {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}},
                        {"function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}},
                    ],
                ),
            )
        ]

    assert [item["event"] for item in items] == ["status", "error"]
    payload = json.loads(items[-1]["data"])
    assert payload["code"] == "question_recovery_exhausted"
    assert proposal_completion.await_count == 2


@pytest.mark.asyncio
async def test_question_recovery_streams_repairing_before_completion_resolves() -> None:
    completion_started = asyncio.Event()
    release_completion = asyncio.Event()

    async def _completion(**_kwargs):
        completion_started.set()
        await release_completion.wait()
        return _make_response_with_text("Kan du förtydliga?")

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=False,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.call_proposal_completion",
            new=_completion,
        ),
    ):
        stream = stream_structured_question_tool_call(
            repo=AsyncMock(),
            litellm_client=AsyncMock(),
            self_correction_temperature=0.2,
            request=_make_request(
                conversation=_conversation_with_answered_final_output_mode(),
                tool_schemas=[
                    {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}},
                    {"function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}},
                ],
            ),
        )
        first = await anext(stream)
        next_item_task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(completion_started.wait(), timeout=1)

        assert first == {"event": "status", "data": '{"status":"repairing"}'}
        assert not next_item_task.done()

        release_completion.set()
        second = await next_item_task

    assert second == {"event": "text", "data": '{"text":"Kan du förtydliga?"}'}


@pytest.mark.asyncio
async def test_handle_structured_question_persists_supported_backend_question() -> None:
    persisted_events = (
        {"event": "question", "data": '{"question_id":"final_output_mode"}'},
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.persist_backend_question",
            new=AsyncMock(return_value=SimpleNamespace(events=persisted_events)),
        ) as persist_question,
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(),
            )
        ]

    assert events == list(persisted_events)
    persist_question.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_structured_question_persists_fallback_text_for_invalid_question_payload() -> (
    None
):
    invalid_question = _make_tool_call(
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
        {"question": "Vad vill du göra?"},
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.persist_tool_turn",
            new=AsyncMock(return_value=1),
        ) as persist_turn,
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(tool_call=invalid_question),
            )
        ]

    assert [event["event"] for event in events] == ["text"]
    persist_turn.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_arguments", "expected_detail"),
    [
        ("{not json", "Expecting property name"),
        ("[1, 2]", "arguments must be a JSON object"),
    ],
)
async def test_handle_structured_question_rejects_invalid_tool_arguments(
    raw_arguments: str,
    expected_detail: str,
) -> None:
    tool_call = MagicMock()
    tool_call.id = "call_question"
    tool_call.function.name = ASK_STRUCTURED_QUESTION_TOOL_NAME
    tool_call.function.arguments = raw_arguments

    with patch(
        "intric.flows.ai_builder.ai_builder_question_recovery."
        "build_discovery_runtime_result",
        new=AsyncMock(return_value=_runtime_result()),
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=AsyncMock(),
                self_correction_temperature=0.2,
                request=_make_request(tool_call=tool_call),
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "invalid_question_payload"
    assert payload["phase"] == "question"
    assert payload["message"].startswith("Invalid question: ")
    assert expected_detail in payload["message"]


@pytest.mark.asyncio
async def test_question_recovery_completion_counts_as_repair() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-question",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    litellm_client = SimpleNamespace(
        acompletion=AsyncMock(return_value=_make_response_with_text("Förtydliga."))
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery."
            "build_discovery_runtime_result",
            new=AsyncMock(return_value=_runtime_result()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_question_recovery.analyze_discovery_ready",
            return_value=False,
        ),
    ):
        events = [
            item
            async for item in stream_structured_question_tool_call(
                repo=AsyncMock(),
                litellm_client=litellm_client,
                self_correction_temperature=0.2,
                request=_make_request(
                    conversation=_conversation_with_answered_final_output_mode(),
                    tool_schemas=[
                        {"function": {"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}},
                        {"function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}},
                    ],
                    usage_tracker=tracker,
                ),
            )
        ]

    assert [event["event"] for event in events] == ["status", "text"]
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["repair_attempts"] == 1
