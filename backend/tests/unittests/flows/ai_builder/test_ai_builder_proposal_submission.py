from __future__ import annotations

import json
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
    MCP_SELECTION_WITHOUT,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
)
from intric.flows.ai_builder.ai_builder_proposal_submission import (
    _forced_submission_response,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.flows.flow_authoring_spec import OutputType
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _builder_plan,
    _compiled_edit_proposal,
    _compiled_outline_proposal,
    _description_update_advisory,
    _make_context,
    _make_flow_spec,
    _make_retry_invocation,
    _make_turn,
)
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import (
    _flow_with_description,
    _make_response_with_text,
    _make_submission,
    _make_tool_call,
)


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def test_create_submission_schema_keeps_mcp_refs_free_form() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "server-1",
                "tools": [{"ref": "tool-1", "name": "lookup_case"}],
            }
        ],
    )
    schemas = _make_submission()._active_submission_tool_schemas(
        flow=None,
        resource_catalog=catalog,
    )

    step_props = schemas[0]["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]
    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


@pytest.mark.parametrize(
    ("message", "submission_tool_name"),
    [
        (SimpleNamespace(tool_calls=None, content="text"), PROPOSE_FLOW_TOOL_NAME),
        (SimpleNamespace(tool_calls=[], content="text"), PROPOSE_FLOW_TOOL_NAME),
        (
            SimpleNamespace(
                tool_calls=[
                    _make_tool_call(PROPOSE_FLOW_TOOL_NAME, {}),
                    _make_tool_call(PROPOSE_FLOW_TOOL_NAME, {}),
                ],
                content="text",
            ),
            PROPOSE_FLOW_TOOL_NAME,
        ),
        (
            SimpleNamespace(
                tool_calls=[_make_tool_call(PROPOSE_FLOW_TOOL_NAME, {})],
                content="text",
            ),
            "confirm_requirements",
        ),
    ],
)
def test_forced_submission_response_rejects_missing_parallel_wrong_or_unsupported_tools(
    message: SimpleNamespace, submission_tool_name: str
) -> None:
    assert (
        _forced_submission_response(
            message=message,
            submission_tool_name=submission_tool_name,
        )
        is None
    )


def test_forced_submission_response_accepts_one_active_submission_tool() -> None:
    tool_call = _make_tool_call(PROPOSE_FLOW_TOOL_NAME, {})

    response = _forced_submission_response(
        message=SimpleNamespace(tool_calls=[tool_call], content="Här är planen."),
        submission_tool_name=PROPOSE_FLOW_TOOL_NAME,
    )

    assert response is not None
    assert response.tool_call is tool_call
    assert response.text_content == "Här är planen."


@pytest.mark.asyncio
async def test_scoped_revision_preflight_skips_existing_flow_edit_context() -> None:
    submission = _make_submission()
    ctx = _make_context(flow=SimpleNamespace(id=uuid4()))

    result = await submission._preflight_scoped_step_revision_if_requested(
        ctx=ctx,
    )

    assert result is None


@pytest.mark.asyncio
async def test_scoped_revision_preflight_returns_error_event_for_deterministic_failure() -> (
    None
):
    submission = _make_submission()
    ctx = _make_context(request_id="req-deterministic-failure")
    deterministic_failure = ToolProcessingResult(
        feedback="Scoped plan edit target `step_a` disappeared.",
        failure_kind="quality",
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission."
        "process_scoped_step_revision_if_requested",
        return_value=deterministic_failure,
    ):
        result = await submission._preflight_scoped_step_revision_if_requested(
            ctx=ctx,
        )

    assert result is not None
    assert result.event is not None
    payload = json.loads(result.event["data"])
    assert payload["code"] == "bad_request"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-deterministic-failure"
    assert "selected step change" in payload["message"]
    assert "selected model change" not in payload["message"]
    assert payload["details"] == {"failure_kind": "quality"}


@pytest.mark.asyncio
async def test_scoped_revision_preflight_uses_bounded_server_tool_call_id() -> None:
    submission = _make_submission()
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    finalize = AsyncMock(return_value=({"event": "plan", "data": "{}"},))
    ctx = _make_context(
        conversation=[
            ConversationMessage(role="user", content="byt modell till gpt 5.4 nano")
        ],
        prior_plan_for_revision=prior_plan,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_a",
        ),
        resource_catalog=catalog,
        available_model_refs=catalog.model_refs,
        request_id="00000000-0000-0000-0000-000000000000",
    )

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await submission._preflight_scoped_step_revision_if_requested(
            ctx=ctx,
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = finalize.await_args.args[0]
    assert request.tool_call_id != f"server_scoped_model_revision:{ctx.request_id}"
    assert "scoped_step_revision" in request.tool_call_id
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "kan du ändra så att jag får en pdf fil istället?",
        "utdatat ska vara pdf fil",
    ],
)
async def test_scoped_revision_preflight_finalizes_terminal_pdf_revision(
    message: str,
) -> None:
    submission = _make_submission()
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    finalize = AsyncMock(return_value=({"event": "plan", "data": "{}"},))
    ctx = _make_context(
        conversation=[
            ConversationMessage(
                role="user",
                content=message,
            )
        ],
        prior_plan_for_revision=prior_plan,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_a",
        ),
        request_id="00000000-0000-0000-0000-000000000001",
    )

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await submission._preflight_scoped_step_revision_if_requested(
            ctx=ctx,
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = finalize.await_args.args[0]
    assert request.arguments["revision_kind"] == "scoped_step_direct"
    assert request.assistant_content == "Jag har uppdaterat det valda steget."
    assert request.compiled.spec.steps[0].output_type == OutputType.PDF
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
async def test_create_propose_flow_quality_failure_records_failed_first_attempt() -> (
    None
):
    submission = _make_submission()
    tracker = ProposalTurnTelemetry(
        request_id="req-outline-quality",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
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
            content="Fortsätt utan MCP",
            metadata={
                "question_answer": {
                    "question_id": MCP_RESOURCE_SELECTION_QUESTION_ID,
                    "selected_values": [MCP_SELECTION_WITHOUT],
                }
            },
        )
    ]
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {
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
        tool_call_id="call-outline-quality",
    )
    ctx = _make_context(
        conversation=conversation,
        resource_catalog=catalog,
        usage_tracker=tracker,
        request_id="req-outline-quality",
        text_content="",
    )

    async def _repair_events(_request):
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction",
            side_effect=_repair_events,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "quality"
    assert telemetry["proposal_repair_invocation_count"] == 1
    assert telemetry["proposal_repair_invocation_reasons"] == ["quality"]


@pytest.mark.asyncio
async def test_handle_create_propose_flow_tool_call_returns_architecture_error_without_repair() -> (
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
            "steps": [{"name": "Summarize", "task": "Summarize the recording."}],
        },
        tool_call_id="call-architecture",
    )
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        usage_tracker=tracker,
        request_id="req-architecture",
        text_content="",
    )
    process_outline = AsyncMock(
        side_effect=AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="invalid skeleton",
            log_context={"surface": "test"},
        )
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction"
        ) as repair,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_outline_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    repair.assert_not_called()
    process_outline.assert_awaited_once()
    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["phase"] == "proposal"
    assert payload["details"]["architecture_error_code"] == (
        "architecture_materialization_failed"
    )
    assert payload["details"]["architecture_error_detail"] == "invalid skeleton"
    assert payload["details"]["surface"] == "test"

    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
    assert telemetry["proposal_repair_invocation_reasons"] == []


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
            "intric.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction"
        ) as repair,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
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
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_outline_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(), tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

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
        {"event": "status", "data": '{"status":"one"}'},
        {"event": "plan", "data": "{}"},
    )
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(events=expected_events)
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_outline_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(), tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == list(expected_events)


@pytest.mark.asyncio
async def test_create_propose_flow_finalization_uses_default_assistant_content() -> (
    None
):
    submission = _make_submission()
    compiled = _compiled_outline_proposal()
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
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

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_outline_arguments",
            new=process_outline,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(text_content="Provider prose"), tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "plan", "data": "{}"}]
    request = finalize.await_args.args[0]
    assert request.assistant_content == "Här är mitt förslag:"


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
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="Invalid propose_flow arguments: bad shape",
            failure_kind="parse",
        )
    )

    async def _events():
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission."
            "run_tool_self_correction",
            return_value=_events(),
        ) as repair,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_outline_arguments",
            new=process_outline,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    process_outline.assert_awaited_once()
    retry_config = repair.call_args.args[0].retry_config
    assert isinstance(retry_config, ToolRetryConfig)
    process_signature = signature(retry_config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_tool_name",
        "target_kind",
        "forced_tool_prompt",
        "process_tool_invocation",
    }


@pytest.mark.asyncio
async def test_create_propose_flow_retry_config_finalizes_compiled_proposal_with_invocation_context() -> (
    None
):
    submission = _make_submission()
    compiled = _compiled_outline_proposal()
    process_outline = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=compiled)
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
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

    config = submission._create_propose_flow_retry_config(
        request_id="req-outline-retry-finalize",
        planning_state=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=tracker,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission."
            "process_outline_arguments",
            new=process_outline,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "plan", "data": "{}"}
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


@pytest.mark.asyncio
async def test_create_propose_flow_self_correction_returns_typed_error_when_completion_raises() -> (
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

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
    ):
        litellm_client.acompletion = AsyncMock(
            side_effect=RuntimeError("provider unavailable")
        )
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert [event["event"] for event in events] == ["status", "error"]
    error_payload = json.loads(events[1]["data"])
    assert error_payload["schema_version"] == 2
    assert error_payload["code"] == "planner_upstream_error"
    assert error_payload["category"] == "upstream"
    assert error_payload["phase"] == "self_correction"
    assert error_payload["request_id"] == "req-self-correction"


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
        yield {"event": "error", "data": "{}"}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission."
        "run_tool_self_correction",
        side_effect=_repair_events,
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "error", "data": "{}"}]
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
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )
    tool_call = _make_tool_call(
        PROPOSE_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "steps": []},
        tool_call_id="call-edit-no-prerequisites",
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.resolve_requirements_state"
        ) as requirements,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.build_discovery_runtime_result",
            new=AsyncMock(),
        ) as discovery,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
    ):
        dispatched = submission.dispatch_submission_tool_call(
            ctx=_make_context(flow=SimpleNamespace(id=uuid4(), steps=[])),
            tool_call=tool_call,
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "plan", "data": "{}"}]
    requirements.assert_not_called()
    discovery.assert_not_awaited()
    process_edit.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_propose_flow_retry_config_carries_invocation_context() -> None:
    submission = _make_submission()
    assistant_snapshots = {uuid4(): {"name": "Analys"}}
    resource_catalog = MagicMock()
    flow = MagicMock()
    plan_edit_context = MagicMock()
    prior_plan_for_revision = MagicMock()

    config = submission._edit_propose_flow_retry_config(
        assistant_snapshots=assistant_snapshots,
        request_id="req",
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        usage_tracker=None,
    )

    assert isinstance(config, ToolRetryConfig)
    assert config.target_tool_name == PROPOSE_FLOW_TOOL_NAME
    assert config.target_kind == TargetKind.EDIT
    process_signature = signature(config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_tool_name",
        "target_kind",
        "forced_tool_prompt",
        "process_tool_invocation",
    }
    assert "valid propose_flow tool call" in config.forced_tool_prompt

    process_edit = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )
    invocation = _make_retry_invocation(
        flow=flow,
        resource_catalog=resource_catalog,
        assistant_metadata={"planner_telemetry": {"request_id": "req"}},
        arguments={"plan_rationale": "Edit", "operations": []},
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
        new=process_edit,
    ):
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "plan", "data": "{}"}
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
    config = submission._edit_propose_flow_retry_config(
        assistant_snapshots=None,
        request_id="req-forced-retry-edit-advisory",
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=tracker,
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
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch.object(
            CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "plan", "data": "{}"}
    litellm_client.acompletion.assert_not_awaited()
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is original
    assert request.compiled.edit is not None
    assert [advisory.code for advisory in request.compiled.edit.advisories] == [
        "flow_description_update_required"
    ]


@pytest.mark.asyncio
async def test_handle_edit_propose_flow_preserves_description_advisory_without_completion() -> (
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
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
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
        events = [event async for event in dispatched]

    assert events == [{"event": "plan", "data": "{}"}]
    litellm_client.acompletion.assert_not_awaited()
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is original
    assert request.compiled.edit is not None
    assert [advisory.code for advisory in request.compiled.edit.advisories] == [
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

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.run_forced_tool_retry_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(
                events=({"event": "plan", "data": "{}"},)
            )
        ),
    ) as retry_forced_tool:
        result = await submission._retry_forced_proposal_after_text(
            correction_messages=[{"role": "system", "content": "Prompt"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            max_output_tokens=4096,
            flow=None,
            usage_tracker=tracker,
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = retry_forced_tool.await_args.args[0]
    assert request.retry_config.target_tool_name == PROPOSE_FLOW_TOOL_NAME
    assert request.retry_config.target_kind == TargetKind.CREATE
    process_signature = signature(request.retry_config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert isinstance(request.turn, SessionSendTurn)
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

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.run_forced_tool_retry_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(
                events=({"event": "plan", "data": "{}"},)
            )
        ),
    ) as retry_forced_tool:
        result = await submission._retry_forced_proposal_after_text(
            correction_messages=[{"role": "system", "content": "Prompt"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Redigera flödet")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            max_output_tokens=4096,
            flow=SimpleNamespace(steps=[]),
            usage_tracker=tracker,
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = retry_forced_tool.await_args.args[0]
    assert request.retry_config.target_tool_name == PROPOSE_FLOW_TOOL_NAME
    assert request.retry_config.target_kind == TargetKind.EDIT
    assert "propose_flow" in request.retry_config.forced_tool_prompt


@pytest.mark.asyncio
async def test_handle_edit_propose_flow_parse_failure_triggers_self_correction() -> (
    None
):
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
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission."
        "run_tool_self_correction",
        return_value=_events(),
    ) as repair:
        dispatched = submission.dispatch_submission_tool_call(
            ctx=ctx, tool_call=tool_call
        )
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    request = repair.call_args.args[0]
    assert "OrderedEditSubmission" in request.error_message
    assert request.retry_config.target_tool_name == PROPOSE_FLOW_TOOL_NAME
