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
from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
    MCP_SELECTION_WITHOUT,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryConfig,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from tests.unittests.flows.ai_builder.test_ai_builder_proposal_processor import (
    _builder_plan,
    _compiled_edit_proposal,
    _description_update_advisory,
    _flow_with_builder_description,
    _make_context,
    _make_flow_spec,
    _make_processor,
    _make_response_with_text,
    _make_retry_invocation,
    _make_tool_call,
    _make_turn,
)


def test_create_submission_schema_keeps_mcp_refs_free_form() -> None:
    schemas = _make_processor()._proposal_submission.active_submission_tool_schemas(
        flow=None,
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "server-1",
                "tools": [{"ref": "tool-1", "name": "lookup_case"}],
            }
        ],
        resource_catalog=None,
    )

    step_props = schemas[0]["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]
    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


@pytest.mark.asyncio
async def test_scoped_model_preflight_skips_existing_flow_edit_context() -> None:
    processor = _make_processor()
    ctx = _make_context(flow=SimpleNamespace(id=uuid4()))

    result = await processor._proposal_submission.preflight_scoped_model_revision_if_requested(
        ctx=ctx,
    )

    assert result is None


@pytest.mark.asyncio
async def test_scoped_model_preflight_returns_error_event_for_deterministic_failure() -> (
    None
):
    processor = _make_processor()
    ctx = _make_context(request_id="req-deterministic-failure")
    deterministic_failure = ToolProcessingResult(
        feedback="Scoped plan edit target `step_a` disappeared.",
        failure_kind="quality",
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission."
        "process_scoped_step_model_revision_if_requested",
        return_value=deterministic_failure,
    ):
        result = await processor._proposal_submission.preflight_scoped_model_revision_if_requested(
            ctx=ctx,
        )

    assert result is not None
    assert result.event is not None
    payload = json.loads(result.event["data"])
    assert payload["code"] == "bad_request"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-deterministic-failure"
    assert payload["details"] == {"failure_kind": "quality"}


@pytest.mark.asyncio
async def test_scoped_model_preflight_uses_bounded_server_tool_call_id() -> None:
    processor = _make_processor()
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {"id": "model-old", "name": "gpt-4o mini"},
            {"id": "model-nano", "name": "gpt-5.4-nano"},
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
        processor._proposal_submission._compiled_proposal_finalizer,
        "finalize_compiled_proposal",
        new=finalize,
    ):
        result = await processor._proposal_submission.preflight_scoped_model_revision_if_requested(
            ctx=ctx,
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = finalize.await_args.args[0]
    assert request.tool_call_id != f"server_scoped_model_revision:{ctx.request_id}"
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
async def test_outline_quality_failure_records_failed_first_attempt() -> None:
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-outline-quality",
        model="openai/gpt-5.4-nano",
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
        OUTLINE_FLOW_TOOL_NAME,
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
        events = [
            event
            async for event in processor._proposal_submission.handle_outline_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_tool"] == OUTLINE_FLOW_TOOL_NAME
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "quality"
    assert telemetry["proposal_repair_invocation_count"] == 1
    assert telemetry["proposal_repair_invocation_reasons"] == ["quality"]


@pytest.mark.asyncio
async def test_handle_outline_flow_tool_call_returns_architecture_error_without_repair() -> (
    None
):
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-architecture",
        model="openai/gpt-5.4-nano",
    )
    tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
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
        events = [
            event
            async for event in processor._proposal_submission.handle_outline_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    repair.assert_not_called()
    process_outline.assert_awaited_once()
    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["phase"] == "proposal"

    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
    assert telemetry["proposal_repair_invocation_reasons"] == []


@pytest.mark.asyncio
async def test_edit_flow_parse_failure_records_proposal_repair_reason() -> None:
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-edit-parse",
        model="openai/gpt-5.4-nano",
    )
    tool_call = MagicMock()
    tool_call.id = "call-edit"
    tool_call.function.name = EDIT_FLOW_TOOL_NAME
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
        events = [
            event
            async for event in processor._proposal_submission.handle_edit_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert events == [{"event": "error", "data": "{}"}]
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_tool"] == EDIT_FLOW_TOOL_NAME
    assert telemetry["proposal_first_attempt_success"] is False
    assert telemetry["proposal_first_attempt_failure_kind"] == "parse"
    assert telemetry["proposal_repair_invocation_count"] == 1
    assert telemetry["proposal_repair_invocation_reasons"] == ["parse"]


@pytest.mark.asyncio
async def test_edit_flow_retry_config_carries_invocation_context() -> None:
    processor = _make_processor()
    assistant_snapshots = {uuid4(): {"name": "Analys"}}
    resource_catalog = MagicMock()
    flow = MagicMock()
    plan_edit_context = MagicMock()
    prior_plan_for_revision = MagicMock()

    config = processor._proposal_submission._edit_flow_retry_config(
        assistant_snapshots=assistant_snapshots,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
        request_id="req",
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        usage_tracker=None,
    )

    assert isinstance(config, ToolRetryConfig)
    assert config.target_tool_name == EDIT_FLOW_TOOL_NAME
    process_signature = signature(config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_tool_name",
        "forced_tool_prompt",
        "process_tool_invocation",
    }
    assert "valid edit_flow tool call" in config.forced_tool_prompt

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
async def test_handle_edit_flow_repairs_compiled_edit_before_finalization() -> None:
    processor = _make_processor()
    flow = MagicMock()
    original = _compiled_edit_proposal()
    repaired = _compiled_edit_proposal(
        spec=original.spec.model_copy(update={"flow_description": "Repaired desc"})
    )
    ctx = _make_context(
        flow=flow,
        text_content="Assistant text",
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
    )
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
        tool_call_id="call-edit-repair",
    )
    process_edit = AsyncMock(
        return_value=ToolProcessingResult(compiled_proposal=original)
    )
    repair = AsyncMock(return_value=repaired)
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=process_edit,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.repair_compiled_edit_description_if_needed",
            new=repair,
        ),
        patch.object(
            processor._proposal_submission._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._proposal_submission.handle_edit_flow_tool_call(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    repair.assert_awaited_once()
    assert repair.await_args.kwargs["compiled"] is original
    assert repair.await_args.kwargs["flow"] is flow
    assert repair.await_args.kwargs["litellm_kwargs"] == {"timeout": 30}
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is repaired


@pytest.mark.asyncio
async def test_handle_edit_flow_description_repair_records_tokens_without_repair_attempt() -> (
    None
):
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-direct-description-repair",
        model="openai/gpt-5.4",
    )
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Old generated description"}),
        advisories=[_description_update_advisory()],
    )
    flow = _flow_with_builder_description("Old generated description")
    ctx = _make_context(
        flow=flow,
        usage_tracker=tracker,
        text_content="Assistant text",
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
    )
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
        tool_call_id="call-edit-description-repair",
    )
    processor.litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text(
            "New generated description",
            prompt_tokens=7,
            completion_tokens=4,
            total_tokens=11,
        )
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_submission.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._proposal_submission._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._proposal_submission.handle_edit_flow_tool_call(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 11
    assert telemetry["repair_attempts"] == 0
    request = finalize.await_args.args[0]
    assert request.compiled.spec.flow_description == "New generated description"


@pytest.mark.asyncio
async def test_retry_forced_proposal_after_text_uses_outline_flow_for_create_mode() -> (
    None
):
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission.run_forced_tool_retry_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(
                events=({"event": "plan", "data": "{}"},)
            )
        ),
    ) as retry_forced_tool:
        result = await processor._proposal_submission.retry_forced_proposal_after_text(
            correction_messages=[{"role": "system", "content": "Prompt"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
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
        )

    assert result == ({"event": "plan", "data": "{}"},)
    request = retry_forced_tool.await_args.args[0]
    assert request.retry_config.target_tool_name == OUTLINE_FLOW_TOOL_NAME
    process_signature = signature(request.retry_config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert isinstance(request.turn, SessionSendTurn)
    assert "Now call outline_flow" in request.retry_config.forced_tool_prompt


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

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_submission."
        "run_tool_self_correction",
        return_value=_events(),
    ) as repair:
        events = [
            event
            async for event in processor._proposal_submission.handle_edit_flow_tool_call(
                ctx=ctx, tool_call=tool_call
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    request = repair.call_args.args[0]
    assert "StepEditOperation" in request.error_message
    assert request.retry_config.target_tool_name == EDIT_FLOW_TOOL_NAME
