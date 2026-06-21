from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_proposal_repair_runtime import (
    ForcedToolAfterTextRequest,
    ProposalSelfCorrectionRequest,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=3,
    )


def _tool_response(*, tool_name: str, arguments: dict[str, object]) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_runtime",
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        ),
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call])
            )
        ]
    )


def _original_tool_call() -> SimpleNamespace:
    return SimpleNamespace(
        id="call_original",
        function=SimpleNamespace(name=PROPOSE_FLOW_TOOL_NAME, arguments="{}"),
    )


@pytest.mark.asyncio
async def test_forced_tool_runtime_architecture_error_uses_sanitized_event_and_telemetry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-runtime",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="invalid skeleton",
        )

    result = await run_forced_tool_retry_after_text(
        ForcedToolAfterTextRequest(
            correction_messages=[{"role": "user", "content": "Build"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=4096,
            retry_config=ToolRetryConfig(
                target_tool_name=PROPOSE_FLOW_TOOL_NAME,
                target_kind=TargetKind.CREATE,
                forced_tool_prompt="Now call propose_flow.",
                process_tool_invocation=process_invocation,
            ),
            forced_proposal_temperature=0.3,
            repair_completion=AsyncMock(
                return_value=_tool_response(
                    tool_name=PROPOSE_FLOW_TOOL_NAME,
                    arguments={
                        "flow_name": "Broken",
                        "plan_rationale": "R",
                        "steps": [],
                    },
                )
            ),
            request_id="req-forced-runtime",
            usage_tracker=tracker,
        )
    )

    assert result.events is not None
    assert [event["event"] for event in result.events] == ["error"]
    payload = json.loads(result.events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0


@pytest.mark.asyncio
async def test_self_correction_runtime_architecture_error_uses_sanitized_event_and_telemetry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-self-correction-runtime",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        raise AIBuilderArchitectureError(
            public_code="architecture_critic_invariant_failed",
            detail="critic invariant failed",
        )

    request = ProposalSelfCorrectionRequest(
        turn=_make_turn(),
        request_id="req-self-correction-runtime",
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        error_message="Invalid flow",
        llm_messages=[{"role": "user", "content": "Build"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=4096,
        self_correction_temperature=0.2,
        self_correction_bumped_temperature=0.5,
        max_self_correction_retries=3,
        repair_completion=AsyncMock(
            return_value=_tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={"flow_name": "Broken", "plan_rationale": "R", "steps": []},
            )
        ),
        retry_config=ToolRetryConfig(
            target_tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=TargetKind.CREATE,
            forced_tool_prompt="Now call propose_flow.",
            process_tool_invocation=process_invocation,
        ),
        forced_proposal_temperature=0.3,
        usage_tracker=tracker,
    )

    events = [event async for event in run_tool_self_correction(request)]

    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[1]["data"])
    assert payload["code"] == "architecture_critic_invariant_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
