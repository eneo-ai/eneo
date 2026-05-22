from __future__ import annotations

import json
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder import (
    ai_builder_proposal_processor as proposal_processor_module,
)
from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    description_hash,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    PlannerPlanEnvelope,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
    CompiledEditResult,
    EditAdvisory,
    FlowEditDiff,
    FlowEditDraft,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_edit_proposal import (
    process_edit_arguments,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_RESOURCE_SELECTION_QUESTION_ID,
    MCP_SELECTION_USE_SERVER_PREFIX,
    MCP_SELECTION_WITHOUT,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
    ProposalContext,
    _active_submission_tool_schemas,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_question_recovery import (
    RecoveredToolDispatchRequest,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AssistantSnapshotResourceUnavailableError,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)


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


def _make_turn(
    *,
    session_id=None,
    tenant_id=None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


def _make_context(**overrides) -> ProposalContext:
    turn = overrides.pop("turn", None) or _make_turn(
        session_id=overrides.pop("session_id", None),
        base_planning_state_version=overrides.pop("base_planning_state_version", 0),
    )
    defaults = {
        "turn": turn,
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


def _make_retry_invocation(**overrides) -> ToolRetryInvocation:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "arguments": {"flow_name": "Test", "plan_rationale": "R", "steps": []},
        "assistant_content": "Här är mitt korrigerade förslag:",
        "tool_call_id": "call_retry",
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "flow": None,
        "assistant_metadata": None,
    }
    defaults.update(overrides)
    return ToolRetryInvocation(**defaults)


def _stored_plan_result(*, plan=None, envelope=None):
    return SimpleNamespace(
        plan=plan or MagicMock(id=uuid4()),
        envelope=envelope or MagicMock(),
        new_planning_state_version=1,
    )


def _compiled_outline_proposal() -> CompiledProposal:
    spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    return CompiledProposal(
        spec=spec,
        assumptions=(),
        plan_rationale="Classify incoming text.",
        reasoning=None,
        validation=SpecValidationResult(),
    )


def _compiled_outline_proposal_with_validation(
    validation: SpecValidationResult,
) -> CompiledProposal:
    compiled = _compiled_outline_proposal()
    return CompiledProposal(
        spec=compiled.spec,
        assumptions=compiled.assumptions,
        plan_rationale=compiled.plan_rationale,
        reasoning=compiled.reasoning,
        validation=validation,
        resource_bindings=compiled.resource_bindings,
        edit_result=compiled.edit_result,
        aggregation_intent=compiled.aggregation_intent,
    )


def _compiled_edit_proposal(
    *,
    spec: FlowDraftSpecCore | None = None,
    advisories: list[EditAdvisory] | None = None,
) -> CompiledProposal:
    compiled_spec = spec or _make_flow_spec(model_ref=None, knowledge_refs=[])
    compiled_edit = CompiledEditResult(
        compiled_spec=compiled_spec,
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        original_draft=FlowEditDraft(operations=[]),
        base_flow_revision=7,
        advisories=advisories or [],
    )
    return CompiledProposal(
        spec=compiled_spec,
        assumptions=(),
        plan_rationale="Update the flow.",
        reasoning=None,
        validation=SpecValidationResult(),
        edit_result=BuilderPlanEditResult(compiled_edit=compiled_edit),
    )


def _description_update_advisory() -> EditAdvisory:
    return EditAdvisory(
        code="flow_description_update_required",
        message="Refresh the flow description.",
        severity="warning",
        field="flow_description",
    )


def _flow_with_builder_description(description: str) -> SimpleNamespace:
    return SimpleNamespace(
        description=description,
        metadata_json={
            "ai_builder": {
                "description": DescriptionProvenance(
                    mode="builder_managed",
                    last_generated_hash=description_hash(description),
                ).model_dump(mode="json")
            }
        },
    )


async def _store_compiled_plan(**kwargs):
    return _stored_plan_result(
        envelope=PlannerPlanEnvelope(spec=kwargs["spec"]),
    )


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


def _make_response_with_text(
    content: str,
    *,
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
                finish_reason="stop",
                message=SimpleNamespace(
                    tool_calls=None,
                    content=content,
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


def test_self_correction_error_event_keeps_internal_feedback_out_of_user_message() -> (
    None
):
    event = AIBuilderProposalProcessor._build_self_correction_error_event(
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
    event = AIBuilderProposalProcessor._build_self_correction_error_event(
        feedback="Invalid edit_flow arguments: operations.0.add_payload.knowledge_refs",
        failure_kind="parse",
    )

    payload = json.loads(event["data"])
    assert payload["code"] == "self_correction_invalid_payload"
    assert "incomplete plan configuration" in payload["message"]
    assert "operations.0" not in payload["message"]


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


def _make_compiled_edit_result(compiled_spec: FlowDraftSpecCore) -> CompiledEditResult:
    return CompiledEditResult(
        compiled_spec=compiled_spec,
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        original_draft=FlowEditDraft(operations=[]),
        base_flow_revision=7,
    )


async def _single_plan_event(**_kwargs):
    yield {"event": "plan", "data": "{}"}


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
        resource_catalog=None,
    )

    step_props = schemas[0]["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]
    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_proposal_turn_telemetry_counts_only_explicit_repair_calls() -> None:
    tracker = ProposalTurnTelemetry(
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
async def test_dispatch_known_tool_call_routes_question_recovery_dispatch_result() -> (
    None
):
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.name = ASK_STRUCTURED_QUESTION_TOOL_NAME
    ctx = _make_context(
        available_model_refs={"model-a"},
        available_kb_refs={"kb-a"},
        resource_catalog=MagicMock(),
        assistant_snapshots=MagicMock(),
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

    with (
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
    assert request.tool_call is tool_call
    assert handle_tool_call.call_args.kwargs["tool_calls"] == [recovered_call]
    assert handle_tool_call.call_args.kwargs["request_id"] == "question-recovery"
    assert handle_tool_call.call_args.kwargs["available_model_refs"] == {"model-a"}
    assert handle_tool_call.call_args.kwargs["available_kb_refs"] == {"kb-a"}
    assert handle_tool_call.call_args.kwargs["resource_catalog"] is ctx.resource_catalog


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

    assert [event["event"] for event in events] == ["plan"]
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
            "handle_tool_call",
            side_effect=_handled_events,
        ) as handle_tool_call,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.call_proposal_completion_with_usage",
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

    assert [event["event"] for event in events] == ["plan"]
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
            turn=_make_turn(session_id=session_id),
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
                turn=_make_turn(),
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
    assert "response_format" not in (
        processor.litellm_client.acompletion.await_args.kwargs
    )
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
            turn=_make_turn(),
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
        f"{MCP_SELECTION_USE_SERVER_PREFIX}mcp_server.time-mcp",
    ]
    assert not processor.litellm_client.acompletion.await_count


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

    async def _repair_events(**_kwargs):
        yield {"event": "status", "data": '{"status":"repairing"}'}

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch.object(
            processor,
            "_request_tool_self_correction",
            side_effect=_repair_events,
        ),
    ):
        events = [
            event
            async for event in processor._handle_outline_flow_tool_call(
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
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch.object(processor, "_request_tool_self_correction") as repair,
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_outline_arguments",
            new=process_outline,
        ),
    ):
        events = [
            event
            async for event in processor._handle_outline_flow_tool_call(
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
async def test_self_correction_architecture_error_uses_sanitized_event() -> None:
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-repair-architecture",
        model="openai/gpt-5.4-nano",
    )
    tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Broken",
            "plan_rationale": "Broken.",
            "steps": [{"name": "Broken", "task": "Broken."}],
        },
        tool_call_id="call-repair-architecture",
    )
    ctx = _make_context(
        usage_tracker=tracker,
        request_id="req-repair-architecture",
    )

    async def _raise_architecture_error(**_kwargs):
        raise AIBuilderArchitectureError(
            public_code="architecture_critic_invariant_failed",
            detail="critic invariant failed",
            log_context={"critic_issue_ids": "pdf_terminal_output_alignment"},
        )
        yield {"event": "unused", "data": "{}"}

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.run_request_self_correction",
        new=_raise_architecture_error,
    ):
        events = [
            event
            async for event in processor._request_tool_self_correction(
                ctx=ctx,
                error_message="Invalid flow",
                tool_call=tool_call,
                retry_config=ToolRetryConfig(
                    target_tool_name=OUTLINE_FLOW_TOOL_NAME,
                    forced_tool_prompt="Now call outline_flow.",
                    process_tool_invocation=AsyncMock(),
                ),
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "architecture_critic_invariant_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0


@pytest.mark.asyncio
async def test_forced_tool_architecture_error_uses_sanitized_event() -> None:
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-architecture",
        model="openai/gpt-5.4-nano",
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.run_retry_forced_tool_after_text",
        new=AsyncMock(
            side_effect=AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                detail="invalid skeleton",
            )
        ),
    ):
        outcome = await processor.retry_forced_tool_after_text(
            correction_messages=[{"role": "user", "content": "Build"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=4096,
            target_tool_name=OUTLINE_FLOW_TOOL_NAME,
            forced_tool_prompt="Now call outline_flow.",
            process_tool_invocation=AsyncMock(),
            usage_tracker=tracker,
            request_id="req-forced-architecture",
        )

    assert outcome.events is not None
    assert [event["event"] for event in outcome.events] == ["error"]
    payload = json.loads(outcome.events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0


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

    async def _repair_events(**_kwargs):
        yield {"event": "error", "data": "{}"}

    with patch.object(
        processor,
        "_request_tool_self_correction",
        side_effect=_repair_events,
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(
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
    captured_metadata: list[dict[str, object] | None] = []

    async def process_outline(**kwargs) -> ToolProcessingResult:
        return ToolProcessingResult(compiled_proposal=_compiled_outline_proposal())

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_outline_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_outline_arguments",
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
    assert planner_telemetry["proposal_first_attempt_tool"] == OUTLINE_FLOW_TOOL_NAME
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
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_outline_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_outline_arguments",
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
    metadata = captured_metadata[0]
    assert isinstance(metadata, dict)
    planner_telemetry = metadata["planner_telemetry"]
    assert planner_telemetry["prompt_tokens"] == 14
    assert planner_telemetry["completion_tokens"] == 10
    assert planner_telemetry["total_tokens"] == 24
    assert planner_telemetry["llm_calls_made"] == 2
    assert planner_telemetry["repair_attempts"] == 1
    assert planner_telemetry["proposal_first_attempt_tool"] == OUTLINE_FLOW_TOOL_NAME
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
    repaired_tool_call = _make_tool_call(
        OUTLINE_FLOW_TOOL_NAME,
        {
            "flow_name": "Recovered flow",
            "plan_rationale": "Classify incoming text.",
            "steps": [{"name": "Classify", "task": "Classify the request."}],
        },
        tool_call_id="call-outline-recovered",
    )
    processor.litellm_client.acompletion.side_effect = [
        _make_response_with_text(
            "Här är ett förslag i text.",
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
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_outline_arguments",
            new=process_outline,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_create_proposal.process_outline_arguments",
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
                available_models=None,
                available_kbs=None,
                available_model_refs=None,
                available_kb_refs=None,
                resource_catalog=None,
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
    assert planner_telemetry["proposal_first_attempt_tool"] == OUTLINE_FLOW_TOOL_NAME
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
    process_outline = AsyncMock(
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
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_outline_arguments",
            new=process_outline,
        ),
    ):
        events = [
            event
            async for event in processor._handle_outline_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    process_outline.assert_awaited_once()
    retry_config = repair.call_args.kwargs["retry_config"]
    assert isinstance(retry_config, ToolRetryConfig)
    process_signature = signature(retry_config.process_tool_invocation)
    assert list(process_signature.parameters) == ["invocation"]
    assert set(ToolRetryConfig.__dataclass_fields__) == {
        "target_tool_name",
        "forced_tool_prompt",
        "process_tool_invocation",
    }


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
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {"name": "Skapa DOCX-rapport"},
            }
        ],
    }

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
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
            resource_catalog=None,
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
        "operations": [
            {
                "op": "add",
                "placement": {"position": "append"},
                "add_payload": {
                    "name": "Granska rubriker",
                    "instructions": "Kontrollera rubrikernas underlag.",
                    "input_source": "previous_step",
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
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ) as compile_edit,
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=None,
        )

    assert result.compiled_proposal is not None
    draft = compile_edit.call_args.args[0]
    payload = draft.operations[0].add_payload
    assert payload is not None
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
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
        ),
    ):
        result = await process_edit_arguments(
            turn=_make_turn(base_planning_state_version=7),
            conversation=[],
            arguments=draft.model_dump(mode="json"),
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=None,
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
        mcp_tool_refs=["mcp_tool.time-mcp-get-current-time"],
    )
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
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
            arguments=draft.model_dump(mode="json"),
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
        mcp_tool_refs=["mcp_tool.time-mcp-get-current-time"],
    )
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
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
            arguments=draft.model_dump(mode="json"),
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=catalog,
        )

    assert result.compiled_proposal is not None
    assert result.has_events is False


@pytest.mark.asyncio
async def test_edit_proposal_passes_metadata_to_edit_validator() -> None:
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
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
        ) as validate_edit,
    ):
        turn = _make_turn(base_planning_state_version=7)
        await process_edit_arguments(
            turn=turn,
            conversation=[],
            arguments=draft.model_dump(mode="json"),
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=None,
        )

    assert validate_edit.call_args is not None
    assert validate_edit.call_args.kwargs["current_metadata_json"] == flow.metadata_json


@pytest.mark.asyncio
async def test_edit_proposal_canonicalizes_duplicate_modify_ops_before_validation() -> (
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
        "plan_rationale": "Byt slutsteget till DOCX och byt namn.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {"name": "Skapa DOCX-rapport"},
            },
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {"output_type": "docx"},
            },
        ],
    }
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
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
            resource_catalog=None,
        )

    assert result.compiled_proposal is not None
    compiled_draft = compile_edit.call_args.args[0]
    assert len(compiled_draft.operations) == 1
    patch_payload = compiled_draft.operations[0].patch
    assert patch_payload is not None
    assert patch_payload.name == "Skapa DOCX-rapport"
    assert patch_payload.output_type == OutputType.DOCX


@pytest.mark.asyncio
async def test_edit_proposal_returns_specific_feedback_for_conflicting_duplicate_modifies() -> (
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
        "plan_rationale": "Två olika namn för samma steg.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {"name": "Skapa rapport"},
            },
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {"name": "Skapa DOCX"},
            },
        ],
    }

    with patch(
        "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft"
    ) as compile_edit:
        result = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
            resource_catalog=None,
        )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "conflicting patch fields" in result.feedback
    assert "existing_step_1: name" in result.feedback
    compile_edit.assert_not_called()


@pytest.mark.asyncio
async def test_edit_proposal_normalizes_mechanical_refs_before_validation() -> None:
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
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit_result = _make_compiled_edit_result(compiled_spec)
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
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
            return_value=edit_result,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.validate_edit_draft",
            return_value=SpecValidationResult(),
        ) as validate_edit,
    ):
        await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=None,
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
async def test_edit_proposal_returns_validation_feedback_for_explicit_mechanics_conflict() -> (
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
        "plan_rationale": "Byt till mallfyllning.",
        "operations": [
            {
                "op": "modify",
                "target_ref": "existing_step_1",
                "patch": {
                    "output_mode": "template_fill",
                    "output_type": "pdf",
                },
            }
        ],
    }

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_edit_proposal.compile_edit_draft",
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
            resource_catalog=None,
        )

    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "output_mode 'template_fill'" in result.feedback
    assert "output_type 'pdf'" in result.feedback
    compile_edit.assert_not_called()


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
                turn=_make_turn(),
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
    assert captured_ctx.base_planning_state_version == 0
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
async def test_outline_self_correction_returns_typed_error_when_completion_raises() -> (
    None
):
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_retry"
    tool_call.function.arguments = "{"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        request_id="req-self-correction",
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.resolve_requirements_state",
            return_value=SimpleNamespace(confirmed=True),
        ),
    ):
        processor.litellm_client.acompletion = AsyncMock(
            side_effect=RuntimeError("provider unavailable")
        )
        events = [
            event
            async for event in processor._handle_outline_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert [event["event"] for event in events] == ["status", "error"]
    error_payload = json.loads(events[1]["data"])
    assert error_payload["schema_version"] == 2
    assert error_payload["code"] == "planner_upstream_error"
    assert error_payload["category"] == "upstream"
    assert error_payload["phase"] == "self_correction"
    assert error_payload["request_id"] == "req-self-correction"


@pytest.mark.asyncio
async def test_edit_flow_retry_config_carries_invocation_context() -> None:
    processor = _make_processor()
    assistant_snapshots = {uuid4(): {"name": "Analys"}}
    resource_catalog = MagicMock()
    flow = MagicMock()
    plan_edit_context = MagicMock()
    prior_plan_for_revision = MagicMock()

    config = processor._edit_flow_retry_config(
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
        "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
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
async def test_edit_flow_retry_config_repairs_compiled_edit_before_finalization() -> (
    None
):
    processor = _make_processor()
    flow = MagicMock()
    original = _compiled_edit_proposal()
    repaired = _compiled_edit_proposal(
        spec=original.spec.model_copy(update={"flow_description": "Repaired desc"})
    )
    config = processor._edit_flow_retry_config(
        assistant_snapshots=None,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
        request_id="req-retry-edit",
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=None,
    )
    invocation = _make_retry_invocation(
        flow=flow,
        arguments={"plan_rationale": "Edit", "operations": []},
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
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=process_edit,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.repair_compiled_edit_description_if_needed",
            new=repair,
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "plan", "data": "{}"}
    repair.assert_awaited_once()
    assert repair.await_args.kwargs["compiled"] is original
    assert repair.await_args.kwargs["flow"] is flow
    completion = repair.await_args.kwargs["call_proposal_completion"]
    assert callable(completion)
    assert getattr(completion, "__self__", None) is None
    finalize.assert_awaited_once()
    request = finalize.await_args.args[0]
    assert request.compiled is repaired


@pytest.mark.asyncio
async def test_edit_flow_retry_config_description_repair_records_tokens_without_repair_attempt() -> (
    None
):
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-retry-description-repair",
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
    processor.litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text(
            "New generated description",
            prompt_tokens=9,
            completion_tokens=3,
            total_tokens=12,
        )
    )
    config = processor._edit_flow_retry_config(
        assistant_snapshots=None,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=2048,
        request_id=tracker.request_id,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        usage_tracker=tracker,
    )
    invocation = _make_retry_invocation(
        flow=flow,
        arguments={"plan_rationale": "Edit", "operations": []},
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        result = await config.process_tool_invocation(invocation)

    assert result.event == {"event": "plan", "data": "{}"}
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 12
    assert telemetry["repair_attempts"] == 0
    request = finalize.await_args.args[0]
    assert request.compiled.spec.flow_description == "New generated description"


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
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=process_edit,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.repair_compiled_edit_description_if_needed",
            new=repair,
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
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
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 11
    assert telemetry["repair_attempts"] == 0
    request = finalize.await_args.args[0]
    assert request.compiled.spec.flow_description == "New generated description"


@pytest.mark.asyncio
async def test_edit_description_repair_rejection_still_records_spent_tokens() -> None:
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-rejected-description-repair",
        model="openai/gpt-5.4",
    )
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Old generated description"}),
        advisories=[_description_update_advisory()],
    )
    ctx = _make_context(
        flow=_flow_with_builder_description("Old generated description"),
        usage_tracker=tracker,
    )
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
    )
    processor.litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text(
            "",
            prompt_tokens=8,
            completion_tokens=1,
            total_tokens=9,
        )
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 9
    assert telemetry["repair_attempts"] == 0
    request = finalize.await_args.args[0]
    assert request.compiled is original


@pytest.mark.asyncio
async def test_ineligible_edit_description_repair_does_not_record_completion_usage() -> (
    None
):
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-ineligible-description-repair",
        model="openai/gpt-5.4",
    )
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Manual description"}),
        advisories=[_description_update_advisory()],
    )
    ctx = _make_context(
        flow=SimpleNamespace(description="Manual description", metadata_json=None),
        usage_tracker=tracker,
    )
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
    )
    processor.litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text(
            "Should not be used",
            prompt_tokens=8,
            completion_tokens=1,
            total_tokens=9,
        )
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    processor.litellm_client.acompletion.assert_not_awaited()
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 0
    assert telemetry["total_tokens"] is None
    request = finalize.await_args.args[0]
    assert request.compiled is original


@pytest.mark.asyncio
async def test_edit_description_repair_without_provider_usage_records_estimate() -> (
    None
):
    processor = _make_processor()
    tracker = ProposalTurnTelemetry(
        request_id="req-estimated-description-repair",
        model="openai/gpt-5.4",
    )
    original = _compiled_edit_proposal(
        spec=_make_flow_spec(
            model_ref=None,
            knowledge_refs=[],
        ).model_copy(update={"flow_description": "Old generated description"}),
        advisories=[_description_update_advisory()],
    )
    ctx = _make_context(
        flow=_flow_with_builder_description("Old generated description"),
        usage_tracker=tracker,
    )
    tool_call = _make_tool_call(
        EDIT_FLOW_TOOL_NAME,
        {"plan_rationale": "Edit", "operations": []},
    )
    processor.litellm_client.acompletion = AsyncMock(
        return_value=_make_response_with_text("New generated description")
    )
    finalize = AsyncMock(
        return_value=ToolProcessingResult(event={"event": "plan", "data": "{}"})
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.process_edit_arguments",
            new=AsyncMock(
                return_value=ToolProcessingResult(compiled_proposal=original)
            ),
        ),
        patch.object(
            processor._compiled_proposal_finalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        events = [
            event
            async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    telemetry = tracker.build_planner_telemetry(tool_call_count=1)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["repair_attempts"] == 0
    assert telemetry["token_usage_source"] == "litellm_estimate"
    assert telemetry["token_usage_estimated"] is True
    assert telemetry["total_tokens"] is not None
    assert telemetry["total_tokens"] > 0


@pytest.mark.asyncio
async def test_retry_forced_proposal_after_text_uses_outline_flow_for_create_mode() -> (
    None
):
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.run_retry_forced_tool_after_text",
        new=AsyncMock(
            return_value=ForcedToolRetryOutcome(
                events=({"event": "plan", "data": "{}"},)
            )
        ),
    ) as retry_forced_tool:
        result = await processor.retry_forced_proposal_after_text(
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
    kwargs = retry_forced_tool.await_args.kwargs
    assert kwargs["target_tool_name"] == OUTLINE_FLOW_TOOL_NAME
    process_signature = signature(kwargs["process_tool_invocation"])
    assert list(process_signature.parameters) == ["invocation"]
    assert isinstance(kwargs["turn"], SessionSendTurn)
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
        patch.object(
            processor,
            "_request_tool_self_correction",
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
        patch.object(
            processor,
            "_request_tool_self_correction",
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
    assert repair.call_args.kwargs["error_message"] == "Missing source material."
