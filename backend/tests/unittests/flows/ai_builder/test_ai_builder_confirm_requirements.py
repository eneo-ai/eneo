from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_confirm_requirements import (
    ConfirmRequirementsProcessingRequest,
    ConfirmRequirementsRetryConfigRequest,
    build_confirm_requirements_retry_config,
    process_confirm_requirements,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_summary_from_metadata,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=0,
    )


def _valid_requirements_arguments() -> dict[str, object]:
    return {
        "summary": "Bygg ett mötesflöde.",
        "key_decisions": [
            {
                "topic": "Indata",
                "decision": "Användaren laddar upp mötesljud.",
            }
        ],
        "input_description": "Mötesljud vid körning.",
        "output_description": "Mötesprotokoll i DOCX.",
        "assumptions": ["DOCX ska skapas på svenska."],
        "manual_setup_notes": ["Koppla transkriberingsmodell."],
    }


def _make_request(**overrides: object) -> ConfirmRequirementsProcessingRequest:
    repo = AsyncMock()
    repo.commit_turn.return_value = 12
    turn = _make_turn()
    defaults = {
        "repo": repo,
        "turn": turn,
        "conversation": [ConversationMessage(role="user", content="Bygg mötesflöde")],
        "new_messages_start": 1,
        "arguments": _valid_requirements_arguments(),
        "tool_call_id": "call_confirm",
        "flow": None,
        "litellm_client": AsyncMock(),
        "litellm_model": "openai/gpt-5.4",
        "litellm_kwargs": {"timeout": 30},
        "tenant_id": turn.tenant_id,
        "assistant_metadata": {"planner_telemetry": {"request_id": "req-1"}},
    }
    defaults.update(overrides)
    return ConfirmRequirementsProcessingRequest(**defaults)


@pytest.mark.asyncio
async def test_process_confirm_requirements_persists_metadata_and_emits_summary() -> (
    None
):
    request = _make_request()

    with patch(
        "intric.flows.ai_builder.ai_builder_confirm_requirements."
        "build_discovery_block_message_runtime",
        new=AsyncMock(
            return_value=(
                None,
                SimpleNamespace(assumptions=["Ljud transkriberas."]),
                None,
            )
        ),
    ):
        result = await process_confirm_requirements(request)

    assert result.feedback is None
    assert result.failure_kind is None
    assert result.new_planning_state_version == 12
    assert result.event is not None
    assert result.event["event"] == "requirements_summary"
    payload = RequirementsSummaryPayload.model_validate_json(result.event["data"])
    assert payload.assumptions == [
        "Ljud transkriberas.",
        "DOCX ska skapas på svenska.",
    ]
    assert payload.requirements_version == build_requirements_version(
        payload.model_copy(update={"requirements_version": None}, deep=True)
    )

    request.repo.commit_turn.assert_awaited_once()
    assert len(request.conversation) == 3
    assistant_message = request.conversation[1]
    tool_message = request.conversation[2]
    assert assistant_message.metadata == {"planner_telemetry": {"request_id": "req-1"}}
    assert assistant_message.tool_calls is not None
    assert json.loads(json.dumps(assistant_message.tool_calls))[0]["name"] == (
        "confirm_requirements"
    )
    persisted_summary = requirements_summary_from_metadata(tool_message.metadata)
    assert persisted_summary is not None
    assert persisted_summary.requirements_version == payload.requirements_version
    assert persisted_summary.requirements_summary.summary == "Bygg ett mötesflöde."


@pytest.mark.asyncio
async def test_process_confirm_requirements_parse_failure_returns_feedback() -> None:
    request = _make_request(
        arguments={"summary": "Kort", "key_decisions": "inte-en-lista"},
    )

    result = await process_confirm_requirements(request)

    assert result.event is None
    assert result.events == ()
    assert result.failure_kind == "parse"
    assert result.feedback is not None
    assert "Invalid requirements summary" in result.feedback
    request.repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_confirm_requirements_validation_followup_returns_events() -> (
    None
):
    request = _make_request(allow_discovery_followup=True)
    followup = SimpleNamespace(
        events=[
            {"event": "text", "data": '{"text":"Vilken indatakälla?"}'},
            {"event": "question", "data": "{}"},
        ],
        new_planning_state_version=17,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_confirm_requirements."
            "build_discovery_block_message_runtime",
            new=AsyncMock(
                return_value=("Missing source material.", SimpleNamespace(), None)
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_confirm_requirements."
            "assistant_metadata_with_usage",
            return_value={"planner_telemetry": {"tool_call_count": 1}},
        ) as metadata_with_usage,
        patch(
            "intric.flows.ai_builder.ai_builder_confirm_requirements."
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=followup),
        ) as emit_followup,
    ):
        result = await process_confirm_requirements(request)

    assert result.event is None
    assert result.events == tuple(followup.events)
    assert result.feedback is None
    assert result.failure_kind is None
    assert result.new_planning_state_version == 17
    metadata_with_usage.assert_called_once()
    assert metadata_with_usage.call_args.kwargs["tool_calls"] == [
        {"name": "ask_structured_question"}
    ]
    emit_followup.assert_awaited_once()
    assert emit_followup.await_args.kwargs["assistant_metadata"] == {
        "planner_telemetry": {"tool_call_count": 1}
    }
    request.repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_confirm_requirements_validation_without_followup_returns_feedback() -> (
    None
):
    request = _make_request(allow_discovery_followup=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_confirm_requirements."
            "build_discovery_block_message_runtime",
            new=AsyncMock(
                return_value=("Missing source material.", SimpleNamespace(), None)
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_confirm_requirements."
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=None),
        ) as emit_followup,
    ):
        result = await process_confirm_requirements(request)

    assert result.event is None
    assert result.events == ()
    assert result.failure_kind == "validation"
    assert result.feedback == "Missing source material."
    emit_followup.assert_awaited_once()
    request.repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_requirements_retry_config_carries_invocation_context() -> None:
    repo = AsyncMock()
    tenant_id = uuid4()
    config = build_confirm_requirements_retry_config(
        ConfirmRequirementsRetryConfigRequest(
            repo=repo,
            litellm_client=AsyncMock(),
            tenant_id=tenant_id,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={"timeout": 30},
        )
    )
    turn = _make_turn()
    invocation = ToolRetryInvocation(
        turn=turn,
        conversation=[ConversationMessage(role="user", content="Bygg")],
        new_messages_start=1,
        arguments=_valid_requirements_arguments(),
        assistant_content="Retry",
        tool_call_id="call_retry",
        available_model_refs=None,
        available_kb_refs=None,
        flow=SimpleNamespace(),
        assistant_metadata={"planner_telemetry": {"request_id": "retry"}},
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_confirm_requirements."
        "process_confirm_requirements",
        new=AsyncMock(
            return_value=ToolProcessingResult(
                event={"event": "requirements_summary", "data": "{}"}
            )
        ),
    ) as process_confirm:
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "requirements_summary", "data": "{}"}
    process_confirm.assert_awaited_once()
    request = process_confirm.await_args.args[0]
    assert request.repo is repo
    assert request.turn is turn
    assert request.conversation is invocation.conversation
    assert request.flow is invocation.flow
    assert request.litellm_model == "openai/gpt-5.4"
    assert request.litellm_kwargs == {"timeout": 30}
    assert request.tenant_id == tenant_id
    assert request.assistant_metadata == {"planner_telemetry": {"request_id": "retry"}}
    assert request.allow_discovery_followup is False
