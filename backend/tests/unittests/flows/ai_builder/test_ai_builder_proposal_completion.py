from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    BadRequestError,
    RateLimitError,
    Timeout,
    UnprocessableEntityError,
)

from eneo.ai_models.completion_models.completion_model import CompletionModel
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder import (
    ai_builder_error_contract as error_contract_module,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderKnownProviderRejectionException,
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    call_proposal_completion,
    make_usage_tracked_proposal_completion,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalCallKind,
    ProposalTurnTelemetry,
    assistant_metadata_with_usage,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCallBudget,
    ProposalMessageGroup,
    ProposalRequestBudget,
    append_protected_repair_group,
    flatten_proposal_message_groups,
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionRequest as ProposalCompletionRequestContract,
)
from eneo.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.tenants.tenant import TenantInDB


def _route(
    *,
    model: str = "openai/gpt-5.4",
    kwargs: dict[str, object] | None = None,
    supported: SupportedModelKwargs | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=supported
        or SupportedModelKwargs(temperature=ModelKwargCapability(supported=True)),
    )


def _completion_request(
    *,
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> ProposalCompletionRequestContract:
    return ProposalCompletionRequestContract(
        message_groups=(
            ProposalMessageGroup(
                messages=tuple(messages),  # type: ignore[arg-type]
                kind="current_turn",
                protected=True,
            ),
        ),
        **kwargs,
    )


def _unprocessable_entity_error() -> UnprocessableEntityError:
    return UnprocessableEntityError(
        "sensitive-provider-material",
        model="private-model",
        llm_provider="private-provider",
        response=httpx.Response(
            422,
            request=httpx.Request(
                "POST",
                "https://provider.invalid/v1/chat/completions",
            ),
        ),
    )


async def _resolved_route(
    capabilities: dict[str, object] | None,
) -> ResolvedCompletionModelRoute:
    now = datetime.now(timezone.utc)
    tenant = TenantInDB.model_construct(id=uuid4(), name="Test tenant")
    model = CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-test",
        nickname="GPT test",
        max_input_tokens=4096,
        max_output_tokens=1024,
        is_deprecated=False,
        vision=False,
        reasoning=False,
        tenant_id=tenant.id,
        provider_id=uuid4(),
        provider_type="openai",
        model_kwargs_capabilities=capabilities,
    )
    provider = ResolvedLiteLLMProvider(
        id=model.provider_id,
        tenant_id=tenant.id,
        name="Test provider",
        provider_type="openai",
        credentials={"api_key": "test-only"},
        config={},
    )
    encryption_service = MagicMock()
    encryption_service.is_active.return_value = False
    completion_service = CompletionService(
        context_builder=MagicMock(),
        tenant=tenant,
        session=AsyncMock(),
        encryption_service=encryption_service,
    )
    with patch(
        "eneo.model_providers.infrastructure.litellm_provider.load_active_litellm_provider",
        new=AsyncMock(return_value=provider),
    ):
        return await completion_service.resolve_model_route(model)


def _make_response_with_text(
    text: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
                finish_reason="stop",
            )
        ],
    )
    if prompt_tokens is not None:
        response.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    return response


def test_forced_tool_choice_builds_provider_shape_once() -> None:
    assert forced_tool_choice(PROPOSE_FLOW_TOOL_NAME) == {
        "type": "function",
        "function": {"name": PROPOSE_FLOW_TOOL_NAME},
    }


@pytest.mark.asyncio
async def test_proposal_omits_temperature_without_persisted_route_capability() -> None:
    route = await _resolved_route(None)
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=route,
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-test"
    assert call_kwargs["api_key"] == "test-only"
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_proposal_passes_supported_temperature_unchanged() -> None:
    route = await _resolved_route(
        {
            "temperature": {
                "supported": True,
                "control": "slider",
                "minimum": 0,
                "maximum": 2,
                "step": 0.01,
            }
        }
    )
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=route,
            max_output_tokens=1024,
            temperature=0.27,
        ),
    )

    assert litellm_client.acompletion.await_count == 1
    assert litellm_client.acompletion.await_args.kwargs["temperature"] == 0.27


@pytest.mark.asyncio
async def test_call_proposal_completion_strips_planner_response_format_kwargs() -> None:
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    result = await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(
                kwargs={
                    "response_format": {"type": "json_object"},
                    "drop_params": False,
                    "api_base": "http://provider.example",
                }
            ),
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    assert result.choices[0].message.content == "ok"
    assert result.choices[0].message.tool_calls == ()
    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["api_base"] == "http://provider.example"
    assert "response_format" not in call_kwargs


@pytest.mark.asyncio
async def test_call_proposal_completion_forces_drop_params_true_on_provider_call() -> (
    None
):
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(kwargs={"drop_params": False}),
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["drop_params"] is True


@pytest.mark.asyncio
async def test_call_proposal_completion_passes_string_tool_choice() -> None:
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
            tool_choice="auto",
        ),
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_call_proposal_completion_passes_forced_tool_choice() -> None:
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))
    tool_choice = forced_tool_choice(PROPOSE_FLOW_TOOL_NAME)

    await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
            tool_choice=tool_choice,
        ),
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["tool_choice"] == tool_choice


@pytest.mark.parametrize(
    (
        "error",
        "expected_kind",
        "expected_exception_class",
        "expected_exception",
        "expected_code",
    ),
    [
        (
            BadRequestError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            "bad_request",
            AIBuilderKnownProviderRejectionException,
            AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        ),
        (
            RateLimitError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rate_limited",
            "rate_limit",
            AIBuilderKnownProviderRejectionException,
            AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        ),
        (
            _unprocessable_entity_error(),
            "rejected",
            "unprocessable_entity",
            AIBuilderKnownProviderRejectionException,
            AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        ),
        (
            Timeout(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "timeout",
            "timeout",
            AIBuilderProviderOutcomeUnknownException,
            AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN,
        ),
        (
            APIConnectionError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            "api_connection",
            AIBuilderProviderOutcomeUnknownException,
            AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN,
        ),
        (
            APIError(
                503,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            "api_error",
            AIBuilderProviderOutcomeUnknownException,
            AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN,
        ),
        (
            RuntimeError("sensitive-provider-material"),
            "unknown",
            "unknown",
            AIBuilderProviderOutcomeUnknownException,
            AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN,
        ),
    ],
)
@pytest.mark.asyncio
async def test_proposal_provider_failure_uses_typed_disposition(
    error: Exception,
    expected_kind: str,
    expected_exception_class: str,
    expected_exception: type[Exception],
    expected_code: AIBuilderErrorCode,
) -> None:
    litellm_client = SimpleNamespace(acompletion=AsyncMock(side_effect=error))
    before_provider_call = AsyncMock()
    tracker = ProposalTurnTelemetry(
        request_id="req-provider-failure",
        model="private-model",
        target_kind=TargetKind.CREATE,
    )

    with patch.object(error_contract_module.logger, "info") as event_log:
        with pytest.raises(AIBuilderBadRequestException) as exc_info:
            await call_proposal_completion(
                litellm_client=litellm_client,
                request=_completion_request(
                    messages=[{"role": "user", "content": "private-user-content"}],
                    tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
                    route=_route(),
                    max_output_tokens=1024,
                    temperature=0.2,
                ),
                usage_tracker=tracker,
                before_provider_call=before_provider_call,
            )

    assert isinstance(exc_info.value, expected_exception)
    assert exc_info.value.code == expected_code
    assert isinstance(
        exc_info.value,
        (
            AIBuilderKnownProviderRejectionException,
            AIBuilderProviderOutcomeUnknownException,
        ),
    )
    assert exc_info.value.public_error is not None
    assert exc_info.value.public_error.details == {
        "another_call_permitted": False,
        "provider_disposition": (
            "known_rejection"
            if expected_exception is AIBuilderKnownProviderRejectionException
            else "provider_outcome_unknown"
        ),
        "provider_exception_class": expected_exception_class,
        "retry_scope": (
            "new_turn"
            if expected_exception is AIBuilderKnownProviderRejectionException
            else "acknowledged_same_turn"
        ),
    }
    before_provider_call.assert_awaited_once_with()
    assert litellm_client.acompletion.await_count == 1
    failure_calls = [
        call for call in event_log.call_args_list if call.args == ("failure_event",)
    ]
    assert len(failure_calls) == 1
    evidence_calls = [
        call
        for call in event_log.call_args_list
        if call.args == ("ai_builder_provider_incident_evidence",)
    ]
    assert len(evidence_calls) == 1
    payload = failure_calls[0].kwargs["extra"]
    assert payload["event"] == "ai_builder.provider.failure"
    assert payload["operation"] == "proposal_completion"
    assert payload["failure_kind"] == expected_kind
    assert len(payload["failure_fingerprint"]) == 12
    encoded = str(payload)
    assert "sensitive-provider-material" not in encoded
    assert "private-user-content" not in encoded
    assert "private-model" not in encoded
    assert "private-provider" not in encoded
    attempts = tracker.build_planner_telemetry()["proposal_attempts"]
    assert len(attempts) == 1
    assert attempts[0]["failure_kind"] == "provider_error"


@pytest.mark.asyncio
async def test_proposal_failure_emits_one_allowlisted_incident_evidence() -> None:
    route = await _resolved_route(
        {
            "temperature": {
                "supported": True,
                "control": "slider",
                "minimum": 0,
                "maximum": 2,
                "step": 0.01,
            }
        }
    )
    litellm_client = SimpleNamespace(
        acompletion=AsyncMock(
            side_effect=BadRequestError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
                body={
                    "code": "sk_live_CREDENTIAL_LEAK_9F2A",
                    "param": "temperature",
                    "type": "invalid_request_error",
                },
            )
        )
    )

    with patch.object(error_contract_module.logger, "info") as event_log:
        with pytest.raises(AIBuilderKnownProviderRejectionException):
            await call_proposal_completion(
                litellm_client=litellm_client,
                request=_completion_request(
                    messages=[{"role": "user", "content": "private-user-content"}],
                    tool_schemas=[
                        {
                            "function": {
                                "name": PROPOSE_FLOW_TOOL_NAME,
                                "description": "private-tool-schema-content",
                            }
                        }
                    ],
                    route=route,
                    max_output_tokens=1024,
                    temperature=0.27,
                ),
            )

    evidence_calls = [
        call
        for call in event_log.call_args_list
        if call.args == ("ai_builder_provider_incident_evidence",)
    ]
    assert len(evidence_calls) == 1
    assert set(evidence_calls[0].kwargs["extra"]) == {
        "ai_builder_provider_incident_evidence"
    }
    evidence = evidence_calls[0].kwargs["extra"][
        "ai_builder_provider_incident_evidence"
    ]
    assert set(evidence) == {
        "schema_version",
        "route",
        "outgoing_fields",
        "unclassified_outgoing_field_count",
        "failure",
        "provider_expectation",
    }
    assert evidence["schema_version"] == "ai-builder-provider-incident-evidence.v1"
    assert evidence["route"]["source"] == "resolved_completion_model_route"
    assert evidence["route"]["capability_posture"] == "trusted_effective"
    assert evidence["route"]["unclassified_configuration_field_count"] == 0
    assert evidence["route"]["configuration_fields"] == [
        {"name": "api_key", "json_type": "string", "domain": "credential"}
    ]
    capability_by_name = {
        capability["name"]: capability
        for capability in evidence["route"]["model_kwargs_capabilities"]
    }
    assert capability_by_name["temperature"] == {
        "name": "temperature",
        "supported": True,
        "json_type": "number",
        "constraint": "range",
    }
    outgoing_by_name = {field["name"]: field for field in evidence["outgoing_fields"]}
    assert outgoing_by_name["temperature"] == {
        "name": "temperature",
        "json_type": "number",
        "domain": "model_control",
    }
    assert outgoing_by_name["messages"]["json_type"] == "array"
    assert outgoing_by_name["tools"]["json_type"] == "array"
    assert outgoing_by_name["api_key"] == {
        "name": "api_key",
        "json_type": "string",
        "domain": "credential",
    }
    assert evidence["unclassified_outgoing_field_count"] == 0
    assert evidence["failure"] == {
        "kind": "rejected",
        "stage": "proposal_completion",
        "exception_class": "bad_request",
        "status_code": 400,
        "status_class": "4xx",
        "parameter": "temperature",
        "rejection_class": "outgoing_parameter",
    }
    assert evidence["provider_expectation"] == {"source": "unavailable"}
    encoded = json.dumps(evidence)
    for forbidden in (
        "test-only",
        "sensitive-provider-material",
        "private-model",
        "private-provider",
        "private-user-content",
        "private-tool-schema-content",
        "sk_live_CREDENTIAL_LEAK_9F2A",
        "request_id",
        "session_id",
        "tenant_id",
    ):
        assert forbidden not in encoded


@pytest.mark.asyncio
async def test_call_proposal_completion_ignores_malformed_usage_shape() -> None:
    response = _make_response_with_text("ok")
    response.usage = SimpleNamespace(prompt_tokens="5")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    result = await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    assert result.usage is None


@pytest.mark.asyncio
async def test_call_proposal_completion_normalizes_mapping_tool_calls() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_outline",
                            "function": {
                                "name": PROPOSE_FLOW_TOOL_NAME,
                                "arguments": '{"flow_name":"Test"}',
                            },
                        }
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    result = await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    tool_call = result.choices[0].message.tool_calls[0]
    assert tool_call.id == "call_outline"
    assert tool_call.function.name == PROPOSE_FLOW_TOOL_NAME
    assert tool_call.function.arguments == '{"flow_name":"Test"}'


@pytest.mark.asyncio
async def test_call_proposal_completion_normalizes_object_tool_calls() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_object",
                            function=SimpleNamespace(
                                name=PROPOSE_FLOW_TOOL_NAME,
                                arguments='{"flow_name":"Object"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    result = await call_proposal_completion(
        litellm_client=litellm_client,
        request=_completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )

    tool_call = result.choices[0].message.tool_calls[0]
    assert tool_call.id == "call_object"
    assert tool_call.function.name == PROPOSE_FLOW_TOOL_NAME
    assert tool_call.function.arguments == '{"flow_name":"Object"}'


@pytest.mark.asyncio
async def test_usage_tracked_completion_records_non_repair_usage() -> None:
    response = _make_response_with_text(
        "ok",
        prompt_tokens=5,
        completion_tokens=3,
        total_tokens=8,
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))
    tracker = ProposalTurnTelemetry(
        request_id="req-non-repair",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    completion = make_usage_tracked_proposal_completion(
        litellm_client=litellm_client,
        usage_tracker=tracker,
    )

    result = await completion(
        _completion_request(
            messages=[{"role": "user", "content": "Build a flow"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
            counts_as_repair=False,
        )
    )

    assert result.usage is not None
    assert result.usage.total_tokens == 8
    telemetry = tracker.build_planner_telemetry(tool_call_count=0)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["finish_reason"] == "stop"
    assert telemetry["total_tokens"] == 8
    assert telemetry["repair_attempts"] == 0


@pytest.mark.asyncio
async def test_usage_tracked_completion_counts_repair_usage() -> None:
    response = _make_response_with_text(
        "ok",
        prompt_tokens=6,
        completion_tokens=4,
        total_tokens=10,
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))
    tracker = ProposalTurnTelemetry(
        request_id="req-repair",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    completion = make_usage_tracked_proposal_completion(
        litellm_client=litellm_client,
        usage_tracker=tracker,
    )

    result = await completion(
        _completion_request(
            messages=[{"role": "user", "content": "Repair the proposal"}],
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            route=_route(),
            max_output_tokens=1024,
            temperature=0.2,
            counts_as_repair=True,
        )
    )

    assert result.usage is not None
    assert result.usage.total_tokens == 10
    telemetry = tracker.build_planner_telemetry(tool_call_count=0)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 10
    assert telemetry["repair_attempts"] == 1


@pytest.mark.asyncio
async def test_protected_only_overflow_rejects_before_provider_work_or_call_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_message = {"role": "system", "content": "protected system"}
    current_turn = {"role": "user", "content": "protected current turn"}
    call_budget = ProposalCallBudget()
    request_budget = ProposalRequestBudget(
        context_window_tokens=20,
        output_reserve_tokens=10,
        safety_buffer_tokens=0,
        request_id="req-budget-overflow",
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_message_tokens",
        lambda messages, _model: 11,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_tool_tokens",
        lambda _tools, _model: 0,
    )
    before_provider_call = AsyncMock()
    litellm_client = SimpleNamespace(acompletion=AsyncMock())

    with pytest.raises(AIBuilderKnownProviderRejectionException) as exc_info:
        await call_proposal_completion(
            litellm_client=litellm_client,
            request=ProposalCompletionRequestContract(
                message_groups=(
                    ProposalMessageGroup(
                        messages=(system_message,),  # type: ignore[arg-type]
                        kind="system",
                        protected=True,
                    ),
                    ProposalMessageGroup(
                        messages=(current_turn,),  # type: ignore[arg-type]
                        kind="current_turn",
                        protected=True,
                    ),
                ),
                tool_schemas=[],
                route=_route(),
                max_output_tokens=10,
                temperature=0.2,
                request_budget=request_budget,
                call_budget=call_budget,
            ),
            before_provider_call=before_provider_call,
        )

    assert (
        exc_info.value.public_error.code
        is AIBuilderErrorCode.PLANNER_CONTEXT_LIMIT_EXCEEDED
    )
    assert exc_info.value.public_error.details == {
        "another_call_permitted": False,
        "retry_scope": "new_turn",
    }
    assert call_budget.calls_started == 0
    before_provider_call.assert_not_awaited()
    litellm_client.acompletion.assert_not_awaited()


def test_request_budget_evicts_oldest_optional_groups_and_preserves_repair_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_message = {"role": "system", "content": "system"}
    oldest_turn = {"role": "user", "content": "oldest optional"}
    newer_turn = {"role": "user", "content": "newer optional"}
    current_turn = {"role": "user", "content": "current accepted turn"}
    failed_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-failed",
                "type": "function",
                "function": {"name": "propose_flow", "arguments": "bad"},
            }
        ],
    }
    tool_feedback = {
        "role": "tool",
        "tool_call_id": "call-failed",
        "content": "latest failure",
    }
    groups = (
        ProposalMessageGroup(
            messages=(system_message,),  # type: ignore[arg-type]
            kind="system",
            protected=True,
        ),
        ProposalMessageGroup(
            messages=(oldest_turn,),  # type: ignore[arg-type]
            kind="history",
            protected=False,
        ),
        ProposalMessageGroup(
            messages=(newer_turn,),  # type: ignore[arg-type]
            kind="history",
            protected=False,
        ),
        ProposalMessageGroup(
            messages=(current_turn,),  # type: ignore[arg-type]
            kind="current_turn",
            protected=True,
        ),
        ProposalMessageGroup(
            messages=(failed_call, tool_feedback),  # type: ignore[arg-type]
            kind="repair",
            protected=True,
        ),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_message_tokens",
        lambda candidate, _model: len(candidate) * 10,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_tool_tokens",
        lambda _tools, _model: 0,
    )
    budget = ProposalRequestBudget(
        context_window_tokens=45,
        output_reserve_tokens=0,
        safety_buffer_tokens=0,
        request_id="req-repair-budget",
    )

    fitted = budget.fit(message_groups=groups, tool_schemas=[], model_name="test")

    assert flatten_proposal_message_groups(fitted) == [
        system_message,
        current_turn,
        failed_call,
        tool_feedback,
    ]


@pytest.mark.asyncio
async def test_repair_time_overflow_uses_same_completion_boundary_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_message = {"role": "system", "content": "system"}
    current_turn = {"role": "user", "content": "current accepted turn"}
    repair_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-repair",
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "arguments": "x" * 1000,
                },
            }
        ],
    }
    repair_feedback = {
        "role": "tool",
        "tool_call_id": "call-repair",
        "content": "repair feedback",
    }
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_message_tokens",
        lambda messages, _model: len(messages) * 20,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_tool_tokens",
        lambda _tools, _model: 0,
    )
    call_budget = ProposalCallBudget(call_limit=4, calls_started=1)
    before_provider_call = AsyncMock()
    litellm_client = SimpleNamespace(acompletion=AsyncMock())

    with pytest.raises(AIBuilderKnownProviderRejectionException):
        await call_proposal_completion(
            litellm_client=litellm_client,
            request=ProposalCompletionRequestContract(
                message_groups=(
                    ProposalMessageGroup(
                        messages=(system_message,),  # type: ignore[arg-type]
                        kind="system",
                        protected=True,
                    ),
                    ProposalMessageGroup(
                        messages=(current_turn,),  # type: ignore[arg-type]
                        kind="current_turn",
                        protected=True,
                    ),
                    ProposalMessageGroup(
                        messages=(repair_call, repair_feedback),  # type: ignore[arg-type]
                        kind="repair",
                        protected=True,
                    ),
                ),
                tool_schemas=[],
                route=_route(),
                max_output_tokens=0,
                temperature=0.2,
                counts_as_repair=True,
                request_budget=ProposalRequestBudget(
                    context_window_tokens=70,
                    output_reserve_tokens=0,
                    safety_buffer_tokens=0,
                    request_id="req-repair-overflow",
                ),
                call_budget=call_budget,
            ),
            before_provider_call=before_provider_call,
        )

    assert call_budget.calls_started == 1
    before_provider_call.assert_not_awaited()
    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_repair_overflow_rechecks_the_shared_completion_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_group = ProposalMessageGroup(
        messages=({"role": "system", "content": "system"},),
        kind="system",
        protected=True,
    )
    current_turn_group = ProposalMessageGroup(
        messages=({"role": "user", "content": "current turn"},),
        kind="current_turn",
        protected=True,
    )
    initial_groups = (system_group, current_turn_group)
    first_repair_groups = append_protected_repair_group(
        initial_groups,
        (
            {"role": "assistant", "content": "first invalid repair"},
            {"role": "user", "content": "first feedback"},
        ),
    )
    second_repair_groups = append_protected_repair_group(
        first_repair_groups,
        (
            {"role": "assistant", "content": "oversized second invalid repair"},
            {"role": "user", "content": "oversized second feedback"},
        ),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_message_tokens",
        lambda messages, _model: (
            80 if "oversized" in json.dumps(messages) else len(messages) * 10
        ),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_tool_tokens",
        lambda _tools, _model: 0,
    )
    call_budget = ProposalCallBudget()
    request_budget = ProposalRequestBudget(
        context_window_tokens=50,
        output_reserve_tokens=0,
        safety_buffer_tokens=0,
        request_id="req-second-repair-overflow",
    )
    before_provider_call = AsyncMock()
    litellm_client = SimpleNamespace(
        acompletion=AsyncMock(return_value=_make_response_with_text("repair"))
    )

    for message_groups, counts_as_repair in (
        (initial_groups, False),
        (first_repair_groups, True),
    ):
        await call_proposal_completion(
            litellm_client=litellm_client,
            request=ProposalCompletionRequestContract(
                message_groups=message_groups,
                tool_schemas=[],
                route=_route(),
                max_output_tokens=0,
                temperature=0.2,
                counts_as_repair=counts_as_repair,
                request_budget=request_budget,
                call_budget=call_budget,
            ),
            before_provider_call=before_provider_call,
        )

    with pytest.raises(AIBuilderKnownProviderRejectionException) as exc_info:
        await call_proposal_completion(
            litellm_client=litellm_client,
            request=ProposalCompletionRequestContract(
                message_groups=second_repair_groups,
                tool_schemas=[],
                route=_route(),
                max_output_tokens=0,
                temperature=0.2,
                counts_as_repair=True,
                request_budget=request_budget,
                call_budget=call_budget,
            ),
            before_provider_call=before_provider_call,
        )

    assert (
        exc_info.value.public_error.code
        is AIBuilderErrorCode.PLANNER_CONTEXT_LIMIT_EXCEEDED
    )
    assert call_budget.calls_started == 2
    assert before_provider_call.await_count == 2
    assert litellm_client.acompletion.await_count == 2


@pytest.mark.asyncio
async def test_turn_usage_aggregates_real_auxiliary_initial_and_repair_calls() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-turn-usage",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    auxiliary_response = _make_response_with_text(
        json.dumps(
            {
                "selected_option_id": "pdf_document",
                "reason": "mentions PDF",
            }
        ),
        prompt_tokens=2,
        completion_tokens=1,
        total_tokens=3,
    )
    client = SimpleNamespace(
        acompletion=AsyncMock(
            side_effect=[
                auxiliary_response,
                _make_response_with_text(
                    "initial",
                    prompt_tokens=5,
                    completion_tokens=3,
                    total_tokens=8,
                ),
                _make_response_with_text(
                    "repair",
                    prompt_tokens=7,
                    completion_tokens=4,
                    total_tokens=11,
                ),
            ]
        )
    )
    conversation = [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "terminal_output",
                        "question": "Output?",
                        "options": [
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            }
                        ],
                    },
                }
            ],
        )
    ]

    await adjudicate_pending_question_answer(
        litellm_client=client,
        completion_model_route=_route(),
        conversation=conversation,
        user_message="PDF",
        usage_tracker=tracker,
    )
    call_budget = ProposalCallBudget(call_limit=2)
    calls: tuple[tuple[ProposalCallKind, bool], ...] = (
        ("proposal_initial", False),
        ("proposal_repair", True),
    )
    for call_kind, counts_as_repair in calls:
        await call_proposal_completion(
            litellm_client=client,
            usage_tracker=tracker,
            call_kind=call_kind,
            request=_completion_request(
                messages=[{"role": "user", "content": "Build a flow"}],
                tool_schemas=[],
                route=_route(),
                max_output_tokens=100,
                temperature=0.0,
                counts_as_repair=counts_as_repair,
                call_budget=call_budget,
            ),
        )

    metadata = assistant_metadata_with_usage(
        conversation=[],
        base_metadata=None,
        usage_tracker=tracker,
    )

    assert client.acompletion.await_count == 3
    assert metadata is not None
    planner = metadata["planner_telemetry"]
    assert [record["call_kind"] for record in planner["call_records"]] == [
        "semantic_adjudication",
        "proposal_initial",
        "proposal_repair",
    ]
    assert [record["attempt"] for record in planner["call_records"]] == [1, 2, 3]
    assert {record["request_id"] for record in planner["call_records"]} == {
        "req-turn-usage"
    }
    assert planner["prompt_tokens"] == 2 + 5 + 7
    assert planner["completion_tokens"] == 1 + 3 + 4
    assert planner["total_tokens"] == 3 + 8 + 11
    assert planner["llm_calls_made"] == 3
    assert planner["auxiliary_llm_call_count"] == 1
    summary = metadata["session_telemetry"]
    assert summary["prompt_tokens_total"] == 2 + 5 + 7
    assert summary["completion_tokens_total"] == 1 + 3 + 4
    assert summary["total_tokens_total"] == 3 + 8 + 11
    assert summary["llm_calls_made_total"] == 3
    assert summary["auxiliary_llm_call_count"] == 1
