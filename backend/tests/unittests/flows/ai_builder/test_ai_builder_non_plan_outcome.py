from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from eneo.flows.ai_builder.ai_builder_create_compile_context import CreateCompileContext
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    build_decline_flow_change_tool_schema,
    decline_message,
    decline_reason_from_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_telemetry import PLANNER_TELEMETRY_KEY
from eneo.flows.ai_builder.ai_builder_tool_names import (
    DECLINE_FLOW_CHANGE_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from eneo.flows.ai_builder.ai_builder_tools import validate_native_strict_schema
from tests.unittests.flows.ai_builder.proposal_turn_builders import _make_context
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import (
    _make_submission,
    _make_tool_call,
    _make_usage,
)


def _usage_tracker() -> ProposalTurnTelemetry:
    tracker = ProposalTurnTelemetry(
        request_id="r" * 64,
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    tracker.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )
    return tracker


def _decline_context(repo: AsyncMock, **overrides: object):
    defaults: dict[str, object] = {
        "decline_tool_schema": build_decline_flow_change_tool_schema(),
        "compile_context": CreateCompileContext(ui_language="sv"),
        "request_id": "r" * 64,
        "usage_tracker": _usage_tracker(),
    }
    defaults.update(overrides)
    return _make_context(**defaults)


def test_decline_tool_schema_is_native_strict() -> None:
    schema = build_decline_flow_change_tool_schema()

    assert schema["function"]["name"] == DECLINE_FLOW_CHANGE_TOOL_NAME
    validate_native_strict_schema(schema["function"]["parameters"])


def test_only_contract_reasons_decline() -> None:
    assert (
        decline_reason_from_arguments({"reason": "model_choice_belongs_to_step_editor"})
        == "model_choice_belongs_to_step_editor"
    )
    assert decline_reason_from_arguments({"reason": "because I said so"}) is None
    assert decline_reason_from_arguments({}) is None
    assert (
        decline_reason_from_arguments(
            {"reason": "model_choice_belongs_to_step_editor", "note": "extra"}
        )
        is None
    )


@pytest.mark.parametrize(
    ("ui_language", "expected"),
    [
        ("sv", "Jag kan inte byta modell åt dig — det gör du i stegredigeraren."),
        (
            "en",
            "I can't change the model for you — you pick it in the step editor.",
        ),
        (None, "Jag kan inte byta modell åt dig — det gör du i stegredigeraren."),
    ],
)
def test_the_server_owns_the_declined_sentence(
    ui_language: str | None, expected: str
) -> None:
    assert (
        decline_message("model_choice_belongs_to_step_editor", ui_language=ui_language)
        == expected
    )


@pytest.mark.asyncio
async def test_a_model_change_request_is_declined_without_a_plan() -> None:
    repo = AsyncMock()
    repo.commit_turn = AsyncMock(return_value=7)
    submission = _make_submission(repo=repo)
    conversation: list[object] = []
    tool_call = _make_tool_call(
        DECLINE_FLOW_CHANGE_TOOL_NAME,
        {"reason": "model_choice_belongs_to_step_editor"},
        tool_call_id="call-decline",
    )

    dispatched = submission.dispatch_submission_tool_call(
        ctx=_decline_context(repo, conversation=conversation),
        tool_call=tool_call,
    )

    assert dispatched is not None
    events = [encode_ai_builder_stream_event(event) async for event in dispatched]
    assert [event["event"] for event in events] == ["text"]
    assert json.loads(events[0]["data"]) == {
        "text": "Jag kan inte byta modell åt dig — det gör du i stegredigeraren."
    }
    repo.create_plan.assert_not_awaited()
    repo.commit_turn.assert_awaited_once()
    stored = repo.commit_turn.await_args.kwargs["new_messages"]
    assert [message.role for message in stored] == ["assistant", "tool"]
    # A declined turn costs a provider call, and the session's durable
    # telemetry has to show it like any other committed turn.
    telemetry = (stored[0].metadata or {})[PLANNER_TELEMETRY_KEY]
    assert telemetry["total_tokens"] == 30
    assert telemetry["tool_call_count"] == 1
    assert stored[0].tool_calls[0]["name"] == DECLINE_FLOW_CHANGE_TOOL_NAME
    assert stored[0].tool_calls[0]["arguments"] == {
        "reason": "model_choice_belongs_to_step_editor"
    }


def test_a_repair_request_never_offers_the_decline_tool() -> None:
    """A repair answers a rejected proposal; declining is not one of its options.

    Both repair parsers accept `propose_flow` only, so offering the decline
    tool there would spend a bounded provider call on an answer the turn
    cannot read.
    """
    ctx = _make_context(decline_tool_schema=build_decline_flow_change_tool_schema())

    initial = ctx.completion_request(temperature=0.1)
    repair = ctx.completion_request(temperature=0.1, counts_as_repair=True)

    assert [schema["function"]["name"] for schema in initial.tool_schemas] == [
        PROPOSE_FLOW_TOOL_NAME,
        DECLINE_FLOW_CHANGE_TOOL_NAME,
    ]
    assert initial.tool_choice == "required"
    assert [schema["function"]["name"] for schema in repair.tool_schemas] == [
        PROPOSE_FLOW_TOOL_NAME
    ]
    assert repair.tool_choice == forced_tool_choice(PROPOSE_FLOW_TOOL_NAME)


@pytest.mark.asyncio
async def test_a_reason_outside_the_contract_never_answers_the_turn() -> None:
    repo = AsyncMock()
    submission = _make_submission(repo=repo)
    tool_call = _make_tool_call(
        DECLINE_FLOW_CHANGE_TOOL_NAME,
        {"reason": "i_would_rather_not"},
        tool_call_id="call-decline-unknown",
    )

    dispatched = submission.dispatch_submission_tool_call(
        ctx=_decline_context(repo),
        tool_call=tool_call,
    )

    assert dispatched is not None
    assert [event async for event in dispatched] == []
    repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_decline_is_ignored_when_the_turn_never_offered_it() -> None:
    repo = AsyncMock()
    submission = _make_submission(repo=repo)
    tool_call = _make_tool_call(
        DECLINE_FLOW_CHANGE_TOOL_NAME,
        {"reason": "model_choice_belongs_to_step_editor"},
        tool_call_id="call-decline-unoffered",
    )

    dispatched = submission.dispatch_submission_tool_call(
        ctx=_make_context(decline_tool_schema=None),
        tool_call=tool_call,
    )

    assert dispatched is not None
    assert [event async for event in dispatched] == []
    repo.commit_turn.assert_not_awaited()
