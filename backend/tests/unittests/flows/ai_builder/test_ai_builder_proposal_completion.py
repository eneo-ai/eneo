from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
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
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
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
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionRequest,
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
    tracker.start_attempt(counts_as_repair=False)

    with patch.object(error_contract_module.logger, "info") as event_log:
        with pytest.raises(AIBuilderBadRequestException) as exc_info:
            await call_proposal_completion(
                litellm_client=litellm_client,
                request=ProposalCompletionRequest(
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
                request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        request=ProposalCompletionRequest(
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
        ProposalCompletionRequest(
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
        ProposalCompletionRequest(
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
