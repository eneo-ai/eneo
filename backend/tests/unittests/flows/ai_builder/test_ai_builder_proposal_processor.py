from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_edit_models import FlowEditDraft
from intric.flows.ai_builder.ai_builder_create_tool_schema import CREATE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
    ProposalContext,
    SubmissionToolHandlerConfig,
    ToolRetryConfig,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
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
        "resource_catalog": None,
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


def _make_flow_spec(*, model_ref: str | None, knowledge_refs: list[str]) -> FlowDraftSpecCore:
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
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )


def _make_create_draft(
    *,
    model_ref: str | None = None,
    knowledge_refs: list[str] | None = None,
) -> FlowCreateDraft:
    return FlowCreateDraft.model_validate(
        {
            "flow_name": "Nytt flöde",
            "plan_rationale": "Extraktion först.",
            "steps": [
                {
                    "name": "Extrahera",
                    "instructions": "Extrahera risker.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "model_ref": model_ref,
                    "knowledge_refs": knowledge_refs or [],
                    "runtime_upload": True,
                    "output_fields": [
                        {
                            "name": "risknivå",
                            "field_type": "string",
                            "description": "Risknivå.",
                            "required": True,
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_process_create_arguments_returns_parse_feedback() -> None:
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
        side_effect=ValueError("missing steps"),
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments={"flow_name": "Broken"},
            assistant_content="draft",
            tool_call_id="call_parse",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "parse"
    assert result.feedback == "Invalid create_flow arguments: missing steps"


@pytest.mark.asyncio
async def test_process_create_arguments_returns_quality_feedback_without_storing() -> None:
    processor = _make_processor()
    draft = _make_create_draft()
    spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    validation = SimpleNamespace(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
            return_value=draft,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_create_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_create_draft",
            return_value=spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=spec,
                validation=validation,
                failure_feedback=None,
            ),
        ),
        patch.object(processor, "_format_quality_feedback", return_value="Quality issue"),
        patch.object(processor, "_format_contextual_quality_feedback", return_value=None),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
        ) as store_plan,
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[ConversationMessage(role="user", content="Build a flow")],
            new_messages_start=1,
            arguments=draft.model_dump(mode="json"),
            assistant_content="draft",
            tool_call_id="call_quality",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert result.feedback == "Quality issue"
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_create_arguments_canonicalizes_unique_resource_aliases_before_store() -> None:
    processor = _make_processor()
    draft = _make_create_draft(
        model_ref="gpt-5.4-nano",
        knowledge_refs=["socio"],
    )
    validation = MagicMock(valid=True, errors=[])
    validation.add_error = MagicMock()
    plan = SimpleNamespace(id=uuid4())
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=[{"id": "model-uuid-1", "name": "gpt-5.4-nano"}],
        available_kbs=[{"id": "kb-uuid-1", "name": "socio"}],
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
            return_value=draft,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_create_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_create_draft",
            side_effect=lambda create_draft: _make_flow_spec(
                model_ref=create_draft.steps[0].model_ref,
                knowledge_refs=create_draft.steps[0].knowledge_refs,
            ),
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
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="draft",
            tool_call_id="call_canonical",
            available_model_refs={"model-uuid-1"},
            available_kb_refs={"kb-uuid-1"},
            resource_catalog=resource_catalog,
        )

    assert result.event is not None
    stored_spec = store_plan.await_args.kwargs["spec"]
    assistant_spec = stored_spec.steps[0].assistant_spec
    assert assistant_spec.model_ref == "model-uuid-1"
    assert assistant_spec.knowledge_refs == ["kb-uuid-1"]


@pytest.mark.asyncio
async def test_process_create_arguments_returns_validation_feedback_for_ambiguous_kb_alias() -> None:
    processor = _make_processor()
    draft = _make_create_draft(knowledge_refs=["socio"])
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            {"id": "kb-uuid-1", "name": "Socio"},
            {"id": "kb-uuid-2", "name": "socio"},
        ],
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
        return_value=draft,
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="draft",
            tool_call_id="call_ambiguous",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=resource_catalog,
        )

    assert result.event is None
    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "Ambiguous knowledge base reference 'socio'" in result.feedback
    assert "kb-uuid-1" in result.feedback


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
async def test_dispatch_known_tool_call_routes_create_flow_handler() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.name = CREATE_FLOW_TOOL_NAME
    ctx = _make_context()

    async def _events():
        yield {"event": "plan", "data": "{}"}

    with patch.object(
        processor,
        "_handle_create_flow_tool_call",
        return_value=_events(),
    ) as handle_create_flow:
        dispatched = processor._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
        assert dispatched is not None
        events = [event async for event in dispatched]

    assert events == [{"event": "plan", "data": "{}"}]
    handle_create_flow.assert_called_once_with(ctx=ctx, tool_call=tool_call)


@pytest.mark.asyncio
async def test_handle_create_flow_tool_call_returns_requirements_not_confirmed_error() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.arguments = "{}"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        request_id="req-create",
    )

    with (
        patch.object(
            processor,
            "emit_discovery_followup_if_needed",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.analyze_discovery_ready",
            return_value=True,
        ),
    ):
        events = [
            event
            async for event in processor._handle_create_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert [event["event"] for event in events] == ["error"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "requirements_not_confirmed"
    assert "creating a flow" in payload["message"]


@pytest.mark.asyncio
async def test_handle_create_flow_tool_call_invalid_json_requests_self_correction() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.function.arguments = "{broken"
    ctx = _make_context(
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        text_content="Här är planen.",
        request_id="req-create",
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
        ) as request_retry,
    ):
        events = [
            event
            async for event in processor._handle_create_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    kwargs = request_retry.call_args.kwargs
    assert kwargs["error_message"].startswith("Invalid create_flow arguments:")
    assert kwargs["retry_config"].target_tool_name == CREATE_FLOW_TOOL_NAME
    assert "Now call create_flow" in kwargs["retry_config"].forced_tool_prompt


@pytest.mark.asyncio
async def test_handle_submission_tool_call_runs_processor_once_with_flow_context() -> None:
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
                    target_tool_name=CREATE_FLOW_TOOL_NAME,
                    requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
                    parse_error_prefix="Invalid create_flow arguments",
                    invalid_result_message="Invalid create_flow draft.",
                    forced_tool_prompt="Now call create_flow.",
                    process_tool_arguments=process_tool_arguments,
                ),
            )
        ]

    assert events == [{"event": "plan", "data": "{}"}]
    process_tool_arguments.assert_awaited_once()
    assert "flow" not in process_tool_arguments.await_args.kwargs


@pytest.mark.asyncio
async def test_process_create_arguments_compiles_and_stores_plan() -> None:
    processor = _make_processor()
    draft = _make_create_draft()
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    create_validation = SpecValidationResult()
    compiled_validation = MagicMock(valid=True, errors=[])
    compiled_validation.add_error = MagicMock()
    plan = SimpleNamespace(id=uuid4())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
            return_value=draft,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_create_draft",
            return_value=create_validation,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_create_draft",
            return_value=compiled_spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
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
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_create",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.failure_kind is None
    assert result.event == {"event": "plan", "data": "{}"}
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_create_arguments_formats_structured_field_depth_errors_actionably() -> None:
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
        side_effect=ValueError(
            "1 validation error for FlowCreateDraft\n"
            "steps.1\n"
            "  Structured field nesting depth cannot exceed 3."
        ),
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments={"flow_name": "Broken"},
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_create",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "parse"
    assert result.feedback is not None
    assert "output_fields" in result.feedback
    assert "max 3 levels" in result.feedback
    assert "flatten" in result.feedback.casefold()


@pytest.mark.asyncio
async def test_process_create_arguments_formats_structured_field_entries_in_steps_actionably() -> None:
    processor = _make_processor()

    result = await processor._process_create_arguments(
        session_id=uuid4(),
        conversation=[],
        new_messages_start=0,
        arguments={
            "flow_name": "Kommunärende",
            "plan_rationale": "Struktur först.",
            "steps": [
                {
                    "name": "Extrahera risker",
                    "instructions": "Extrahera risker som strukturerad JSON.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "runtime_upload": True,
                    "runtime_required": True,
                    "output_fields": [
                        {
                            "name": "risker",
                            "field_type": "string",
                            "description": "Identifierade risker.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "osakerheter_och_risker",
                    "field_type": "string",
                    "description": "Osäkerheter och risker.",
                    "required": True,
                },
            ],
        },
        assistant_content="Här är mitt förslag:",
        tool_call_id="call_create",
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
    )

    assert result.event is None
    assert result.failure_kind == "recoverable_parse"
    assert result.feedback is not None
    assert "structured output field, not a step" in result.feedback
    assert "output_fields" in result.feedback
    assert "Every steps[] item must be a full create step object" in result.feedback


@pytest.mark.asyncio
async def test_process_create_arguments_formats_first_step_source_errors_actionably() -> None:
    processor = _make_processor()
    invalid_draft = FlowCreateDraft.model_validate(
        {
            "flow_name": "Ogiltigt flöde",
            "plan_rationale": "Testar första steget.",
            "steps": [
                {
                    "name": "Analys",
                    "instructions": "Analysera underlaget.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                }
            ],
        }
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
        return_value=invalid_draft,
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=invalid_draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_create",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "steps[0].input_source" in result.feedback
    assert "flow_input" in result.feedback
    assert "Only later steps may use previous_step or all_previous_steps" in result.feedback


@pytest.mark.asyncio
async def test_process_create_arguments_appends_actionable_quality_repair_rules() -> None:
    processor = _make_processor()
    draft = _make_create_draft()
    compiled_spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    compiled_validation = MagicMock(valid=True, errors=[])

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.parse_create_flow_arguments",
            return_value=draft,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.validate_create_draft",
            return_value=SpecValidationResult(),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.compile_create_draft",
            return_value=compiled_spec,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.prepare_compiled_spec_for_session",
            return_value=SimpleNamespace(
                spec=compiled_spec,
                validation=compiled_validation,
                failure_feedback=None,
            ),
        ),
        patch.object(processor, "_format_quality_feedback", return_value=None),
        patch.object(
            processor,
            "_format_contextual_quality_feedback",
            return_value=(
                "Quality issues:\n"
                "1. Användaren har valt DOCX som slutartefakt men sista steget producerar inte DOCX. "
                "Justera slutstegets output_type så att det matchar användarens val.\n"
                "2. Konversationen beskriver jämförelse eller samlad analys av flera dokument, men inget steg använder "
                "`input_source=\"all_previous_steps\"`. Använd en aggregerande eller jämförande koppling när flera dokument ska behandlas tillsammans."
            ),
        ),
    ):
        result = await processor._process_create_arguments(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            arguments=draft.model_dump(mode="json"),
            assistant_content="Här är mitt förslag:",
            tool_call_id="call_create",
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
        )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert result.feedback is not None
    assert "Create-flow quality repair rules:" in result.feedback
    assert "output_type to 'docx'" in result.feedback
    assert "input_source='all_previous_steps'" in result.feedback


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
    edit_result = MagicMock(compiled_spec=_make_flow_spec(model_ref=None, knowledge_refs=[]))
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
                "`output_mode=\"template_fill\"`."
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
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

    assert events == [{"event": "text", "data": '{"text":"draft"}'}, {"event": "done", "data": ""}]
    assert captured_ctx is not None
    assert captured_ctx.request_id == "req-ctx"
    assert captured_ctx.text_content == "draft"
    assert captured_ctx.flow is flow
    assert captured_ctx.assistant_snapshots == snapshots
    handle_edit.assert_called_once()


@pytest.mark.asyncio
async def test_request_self_correction_returns_typed_error_when_repair_completion_raises() -> None:
    processor = _make_processor()
    tool_call = _make_tool_call(
        CREATE_FLOW_TOOL_NAME,
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
                conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
                new_messages_start=1,
                error_message="Invalid flow specification: missing steps",
                llm_messages=[{"role": "system", "content": "Prompt"}],
                tool_call=tool_call,
                tool_schemas=[{"function": {"name": CREATE_FLOW_TOOL_NAME}}],
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
    assert config.target_tool_name == CREATE_FLOW_TOOL_NAME
    assert config.process_tool_arguments == processor._process_create_arguments
    assert config.process_tool_kwargs == {}
    assert "Now call create_flow" in config.forced_tool_prompt


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
async def test_retry_forced_proposal_after_text_uses_create_flow_for_create_mode() -> None:
    processor = _make_processor()

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_processor.run_retry_forced_tool_after_text",
        new=AsyncMock(return_value={"event": "plan", "data": "{}"}),
    ) as retry_forced_tool:
        result = await processor.retry_forced_proposal_after_text(
            correction_messages=[{"role": "system", "content": "Prompt"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": CREATE_FLOW_TOOL_NAME}}],
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
    assert kwargs["target_tool_name"] == CREATE_FLOW_TOOL_NAME
    assert kwargs["process_tool_arguments"] == processor._process_create_arguments
    assert "Now call create_flow" in kwargs["forced_tool_prompt"]


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
                "assumptions:[\"trasig\"]",
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
        events = [event async for event in processor._handle_edit_flow(ctx=ctx, tool_call=tool_call)]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    assert "StepEditOperation" in repair.call_args.kwargs["error_message"]
    assert repair.call_args.kwargs["retry_config"].target_tool_name == EDIT_FLOW_TOOL_NAME


@pytest.mark.asyncio
async def test_handle_confirm_requirements_parse_failure_triggers_self_correction() -> None:
    processor = _make_processor()
    tool_call = MagicMock()
    tool_call.id = "call_confirm"
    tool_call.function.name = CONFIRM_REQUIREMENTS_TOOL_NAME
    tool_call.function.arguments = json.dumps({"summary": "Kort", "key_decisions": "inte-en-lista"})
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
            async for event in processor._handle_confirm_requirements(ctx=ctx, tool_call=tool_call)
        ]

    assert events == [{"event": "status", "data": '{"status":"repairing"}'}]
    assert "Invalid requirements summary" in repair.call_args.kwargs["error_message"]
    assert (
        repair.call_args.kwargs["retry_config"].target_tool_name
        == CONFIRM_REQUIREMENTS_TOOL_NAME
    )
