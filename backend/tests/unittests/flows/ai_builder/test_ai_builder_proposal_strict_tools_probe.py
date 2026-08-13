from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import httpx
import litellm
import pytest
from litellm.caching.llm_caching_handler import LLMClientCache
from litellm.exceptions import BadRequestError
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    CompletionTokenUsage,
    LLMCompletionChoice,
    LLMCompletionMessage,
    LLMCompletionResponse,
    LLMCompletionToolCall,
    LLMCompletionToolCallFunction,
)

VALID_ARGUMENTS: dict[str, object] = {
    "rapportnamn": "åtgärder",
    "kommentar": None,
    "avsnitt": [
        {
            "rubrik": "öppna frågor",
            "punkter": [
                {
                    "typ": "åtgärd",
                    "namn": "åtgärder",
                    "prioritet": "hög",
                    "ansvarig": None,
                },
                {"typ": "fråga", "fråga": "öppna frågor", "svar": None},
            ],
        }
    ],
}


def _probe() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_proposal_strict_tools_probe.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ai_builder_proposal_strict_tools_probe", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _route(*, kwargs: dict[str, object] | None = None) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-5.6-luna",
        provider_type="openai",
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(),
    )


def _response(
    arguments: dict[str, object] | str,
    *,
    finish_reason: str = "tool_calls",
) -> LLMCompletionResponse:
    return LLMCompletionResponse(
        choices=(
            LLMCompletionChoice(
                message=LLMCompletionMessage(
                    content=None,
                    tool_calls=(
                        LLMCompletionToolCall(
                            id="call-1",
                            function=LLMCompletionToolCallFunction(
                                name="propose_flow",
                                arguments=(
                                    arguments
                                    if isinstance(arguments, str)
                                    else json.dumps(arguments, ensure_ascii=False)
                                ),
                            ),
                        ),
                    ),
                ),
                finish_reason=finish_reason,
            ),
        ),
        usage=CompletionTokenUsage(
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
            source="provider",
        ),
    )


def _raw_response(arguments: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="propose_flow",
                                arguments=json.dumps(arguments, ensure_ascii=False),
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
        ),
    )


def _native_responses_success(probe: ModuleType) -> dict[str, object]:
    return {
        "id": "resp-probe",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": 256,
        "model": "gpt-5.6-luna",
        "output": [
            {
                "type": "function_call",
                "id": "fc-probe",
                "call_id": "call-probe",
                "name": "propose_flow",
                "arguments": json.dumps(
                    VALID_ARGUMENTS,
                    ensure_ascii=False,
                ),
                "status": "completed",
            }
        ],
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "reasoning": {"effort": "none", "summary": None},
        "store": False,
        "temperature": None,
        "text": {"format": {"type": "text"}},
        "tool_choice": {"type": "function", "name": "propose_flow"},
        "tools": [],
        "top_p": None,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
        "user": None,
        "metadata": {},
    }


def _native_responses_incomplete(probe: ModuleType) -> dict[str, object]:
    response = _native_responses_success(probe)
    response["status"] = "incomplete"
    response["incomplete_details"] = {"reason": "max_output_tokens"}
    output = cast(list[dict[str, object]], response["output"])
    output[0]["status"] = "incomplete"
    output[0]["arguments"] = "{"
    return response


def _source(probe: ModuleType, *, clean: bool = True) -> object:
    return probe.SourceIdentity(
        revision="0" * 40,
        source_clean=clean,
        runner_sha256="1" * 64,
        lockfile_sha256="2" * 64,
        litellm_version="1.95.0",
    )


def _runtime(
    probe: ModuleType,
    *,
    route: ResolvedCompletionModelRoute | None = None,
) -> object:
    selected_route = route or _route()
    projection = probe.proposal_route_identity(selected_route)
    return probe.RuntimeIdentity(
        requested_model_id=probe.PROBE_MODEL_ID,
        resolved_model_id=probe.PROBE_MODEL_ID,
        resolved_model_name="gpt-5.6-luna",
        litellm_model=selected_route.litellm_model,
        provider_type=selected_route.provider_type,
        enabled=True,
        deprecated=False,
        migrated=False,
        supports_tool_calling=True,
        provider_active=True,
        sanitized_route_kwargs=projection.sanitized_route_kwargs,
        proposal_route_identity_sha256=(projection.proposal_route_identity_sha256),
    )


def _empty_effective_identity(probe: ModuleType) -> object:
    return probe._effective_values_identity(
        content_free_shape={},
        effective_values={},
    )


def _passing_outcome(probe: ModuleType) -> object:
    safe_kwargs = _empty_effective_identity(probe)
    return probe.ProbeCallOutcome(
        call_count=1,
        request=probe.RequestObservation(
            controls_valid=True,
            effective_request=safe_kwargs,
            expected_prepared_request_sha256=(safe_kwargs.effective_values_sha256),
        ),
        response=probe.evaluate_response(_response(VALID_ARGUMENTS)),
        failure=None,
    )


def test_capability_contract_is_one_closed_strict_localized_tool() -> None:
    probe = _probe()
    tool_schema = probe.synthetic_tool_schema()

    assert tool_schema["function"]["name"] == "propose_flow"
    assert tool_schema["function"]["strict"] is True
    assert probe.PARALLEL_TOOL_CALLS is False
    assert VALID_ARGUMENTS["rapportnamn"] == "åtgärder"

    def assert_closed(schema: dict[str, object]) -> None:
        assert "const" not in schema
        if "anyOf" in schema:
            branches = schema["anyOf"]
            assert isinstance(branches, list)
            assert len(branches) == 2
            for branch in branches:
                assert isinstance(branch, dict)
                assert_closed(branch)
            return
        if schema.get("type") == "object":
            properties = schema["properties"]
            assert isinstance(properties, dict)
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(properties)
            for child in properties.values():
                assert isinstance(child, dict)
                assert_closed(child)
        elif schema.get("type") == "array":
            items = schema["items"]
            assert isinstance(items, dict)
            assert_closed(items)

    parameters = tool_schema["function"]["parameters"]
    assert isinstance(parameters, dict)
    assert_closed(parameters)
    assert set(parameters["required"]) == {"rapportnamn", "kommentar", "avsnitt"}
    assert parameters["properties"]["kommentar"]["type"] == ["string", "null"]
    point_branches = parameters["properties"]["avsnitt"]["items"]["properties"][
        "punkter"
    ]["items"]["anyOf"]
    assert point_branches[0]["properties"]["typ"]["enum"] == ["åtgärd"]
    assert point_branches[1]["properties"]["typ"]["enum"] == ["fråga"]
    assert "ansvarig" in point_branches[0]["required"]
    assert "svar" in point_branches[1]["required"]


def test_capability_request_has_no_production_or_temperature_claim() -> None:
    probe = _probe()

    request = probe._capability_request_value()

    assert "temperature" not in request
    assert "production_schema_diagnostic" not in request
    assert "proves_production_builder_schema_ready" not in (
        probe.CapabilityProtocol.model_fields
    )


def test_response_evaluation_accepts_every_schema_valid_branch_order() -> None:
    probe = _probe()

    passed = probe.evaluate_response(_response(VALID_ARGUMENTS))
    reversed_arguments = {
        **VALID_ARGUMENTS,
        "avsnitt": [
            {
                "rubrik": "öppna frågor",
                "punkter": [
                    {"typ": "fråga", "fråga": "öppna frågor", "svar": None},
                    {
                        "typ": "åtgärd",
                        "namn": "åtgärder",
                        "prioritet": "hög",
                        "ansvarig": None,
                    },
                ],
            }
        ],
    }
    reversed_valid = probe.evaluate_response(_response(reversed_arguments))
    missing_nullable = probe.evaluate_response(
        _response(
            {
                "rapportnamn": "åtgärder",
                "avsnitt": [
                    {
                        "rubrik": "öppna frågor",
                        "punkter": [
                            {
                                "typ": "åtgärd",
                                "namn": "åtgärder",
                                "prioritet": "hög",
                            },
                            {"typ": "fråga", "fråga": "öppna frågor"},
                        ],
                    }
                ],
            }
        )
    )
    mixed_branches = probe.evaluate_response(
        _response(
            {
                **VALID_ARGUMENTS,
                "avsnitt": [
                    {
                        "rubrik": "öppna frågor",
                        "punkter": [
                            {
                                "typ": "åtgärd",
                                "namn": "åtgärder",
                                "prioritet": "hög",
                                "ansvarig": None,
                                "fråga": "öppna frågor",
                            },
                            {
                                "typ": "fråga",
                                "fråga": "öppna frågor",
                                "svar": None,
                                "prioritet": "hög",
                            },
                        ],
                    }
                ],
            }
        )
    )

    assert passed.checks.all_pass is True
    assert passed.arguments == VALID_ARGUMENTS
    assert reversed_valid.checks.all_pass is True
    assert reversed_valid.arguments == reversed_arguments
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=probe.ProbeCallOutcome(
            call_count=1,
            request=_passing_outcome(probe).request,
            response=reversed_valid,
            failure=None,
        ),
    )
    assert receipt.verdict == "pass"
    assert missing_nullable.checks.same_schema_validation is False
    assert mixed_branches.checks.same_schema_validation is False
    assert missing_nullable.arguments is mixed_branches.arguments is None


@pytest.mark.parametrize("arguments", [VALID_ARGUMENTS, "{"])
def test_length_completion_is_inconclusive_before_schema_validation(
    arguments: dict[str, object] | str,
) -> None:
    probe = _probe()
    response = probe.evaluate_response(_response(arguments, finish_reason="length"))
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=probe.ProbeCallOutcome(
            call_count=1,
            request=_passing_outcome(probe).request,
            response=response,
            failure=None,
        ),
    )

    assert response.finish_reason == "length"
    assert response.checks.same_schema_validation is False
    assert response.arguments is None
    assert receipt.verdict == "inconclusive"
    assert receipt.reason_codes == ("provider_completion_truncated",)


def test_proposal_route_identity_changes_without_retaining_provider_values() -> None:
    probe = _probe()
    first = probe.proposal_route_identity(
        _route(
            kwargs={
                "api_base": "https://deployment.invalid",
                "api_key": "one",
                "organization": "organization-a",
            }
        )
    )
    second = probe.proposal_route_identity(
        _route(
            kwargs={
                "api_base": "https://deployment.invalid",
                "api_key": "one",
                "organization": "organization-b",
            }
        )
    )

    assert first.proposal_route_identity_sha256 != (
        second.proposal_route_identity_sha256
    )
    encoded = first.model_dump_json()
    assert "deployment.invalid" not in encoded
    assert '"one"' not in encoded
    assert "organization-a" not in encoded
    assert "effective_values_sha256" in encoded
    assert "content_free_shape_sha256" in encoded


@pytest.mark.asyncio
async def test_probe_litellm_call_records_exact_effective_request_identity() -> None:
    probe = _probe()
    requests: list[dict[str, object]] = []

    async def provider_completion(**kwargs: object) -> object:
        requests.append(kwargs)
        return _raw_response(VALID_ARGUMENTS)

    first = await probe.run_probe_call(
        route=_route(
            kwargs={
                "api_base": "https://deployment-a.invalid",
                "tools": [{"unsafe": True}],
                "tool_choice": "auto",
                "function_call": "auto",
                "parallel_tool_calls": True,
            }
        ),
        provider_completion=provider_completion,
    )
    second = await probe.run_probe_call(
        route=_route(kwargs={"api_base": "https://deployment-b.invalid"}),
        provider_completion=provider_completion,
    )

    assert first.call_count == second.call_count == 1
    assert first.request is not None and first.request.controls_valid is True
    assert second.request is not None
    assert (
        first.request.effective_request.content_free_shape_sha256
        == second.request.effective_request.content_free_shape_sha256
    )
    assert (
        first.request.effective_request.effective_values_sha256
        != second.request.effective_request.effective_values_sha256
    )
    assert len(requests) == 2
    assert requests[0]["tools"] == [probe.synthetic_tool_schema()]
    assert requests[0]["parallel_tool_calls"] is False
    assert requests[0]["num_retries"] == 0
    assert requests[0]["drop_params"] is False
    assert requests[0]["tool_choice"] == probe.forced_tool_choice("propose_flow")
    assert "temperature" not in requests[0]
    assert "function_call" not in requests[0]
    assert "deployment-a.invalid" not in first.request.model_dump_json()


def test_observed_request_must_match_the_prepared_request_digest() -> None:
    probe = _probe()
    observed = _empty_effective_identity(probe)

    with pytest.raises(ValueError, match="observed request"):
        probe.RequestObservation(
            controls_valid=True,
            effective_request=observed,
            expected_prepared_request_sha256="f" * 64,
        )


@pytest.mark.asyncio
async def test_only_canonical_provider_errors_become_probe_outcomes() -> None:
    probe = _probe()

    async def provider_failure(**_kwargs: object) -> object:
        raise BadRequestError(
            "sensitive-provider-error",
            model="private-model",
            llm_provider="private-provider",
            response=None,
            body={"param": "tools", "secret": "sk-sensitive"},
        )

    outcome = await probe.run_probe_call(
        route=_route(), provider_completion=provider_failure
    )

    assert outcome.failure is not None
    assert outcome.failure.model_dump() == {
        "kind": "rejected",
        "exception_class": "bad_request",
        "status_code": 400,
        "status_class": "4xx",
        "parameter": "tools",
        "remote_response_observed": False,
    }
    encoded = outcome.model_dump_json()
    assert "sensitive-provider-error" not in encoded
    assert "private-model" not in encoded
    assert "sk-sensitive" not in encoded
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )
    assert receipt.verdict == "inconclusive"
    assert receipt.reason_codes == ("request_rejection_without_remote_provenance",)


@pytest.mark.asyncio
async def test_local_provider_adapter_defect_aborts_without_sealing_outcome() -> None:
    probe = _probe()

    async def local_defect(**_kwargs: object) -> object:
        raise ValueError("local normalization defect")

    with pytest.raises(ValueError, match="local normalization defect"):
        await probe.run_probe_call(route=_route(), provider_completion=local_defect)


@pytest.mark.parametrize(
    ("status_code", "provider_parameter"),
    [
        (400, "tools"),
        (422, "tools"),
        (400, "model"),
        (422, "max_output_tokens"),
        (400, None),
        (422, "unsafe parameter"),
    ],
)
@pytest.mark.asyncio
async def test_transport_rejection_without_canonical_attribution_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    provider_parameter: str | None,
) -> None:
    probe = _probe()
    request_count = 0
    provider_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        assert request.url.path == "/v1/responses"
        request_count += 1
        provider_payloads.append(cast(dict[str, object], json.loads(request.content)))
        if request_count == 1:
            return httpx.Response(
                status_code,
                request=request,
                json={
                    "error": {
                        "message": "strict request rejected",
                        "type": "invalid_request_error",
                        "param": provider_parameter,
                        "code": "invalid_schema",
                    }
                },
            )
        return httpx.Response(
            200,
            request=request,
            json=_native_responses_success(probe),
        )

    monkeypatch.setattr(
        AsyncHTTPHandler,
        "_create_async_transport",
        staticmethod(lambda **_kwargs: httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(litellm, "in_memory_llm_clients_cache", LLMClientCache())
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    outcome = await probe.run_probe_call(
        route=_route(
            kwargs={
                "api_key": "test-key",
                "api_base": "https://one-shot.invalid/v1",
            }
        ),
        provider_completion=probe._litellm_provider_completion,
    )

    assert request_count == 1
    provider_payload = provider_payloads[0]
    function = cast(dict[str, object], probe.synthetic_tool_schema()["function"])
    assert provider_payload["tools"] == [
        {
            "name": "propose_flow",
            "parameters": function["parameters"],
            "strict": True,
            "type": "function",
            "description": None,
        }
    ]
    assert provider_payload["tool_choice"] == {
        "type": "function",
        "name": "propose_flow",
    }
    assert provider_payload["parallel_tool_calls"] is False
    assert provider_payload["max_output_tokens"] == 256
    assert "temperature" not in provider_payload
    assert outcome.response is None
    assert outcome.failure is not None
    assert outcome.failure.kind == "rejected"
    assert outcome.failure.exception_class in {
        "bad_request",
        "unprocessable_entity",
    }
    assert outcome.failure.status_code == status_code
    assert outcome.failure.remote_response_observed is True
    assert outcome.failure.parameter is None
    source = _source(probe)
    runtime = _runtime(
        probe,
        route=_route(
            kwargs={
                "api_key": "test-key",
                "api_base": "https://one-shot.invalid/v1",
            }
        ),
    )
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )
    assert receipt.verdict == "inconclusive"
    assert receipt.reason_codes == ("provider_result_inconclusive",)


@pytest.mark.parametrize(
    ("exception_class", "status_code"),
    [("bad_request", 400), ("unprocessable_entity", 422)],
)
def test_canonical_tool_schema_attribution_is_fail(
    exception_class: str,
    status_code: int,
) -> None:
    probe = _probe()
    request_identity = _empty_effective_identity(probe)
    outcome = probe.ProbeCallOutcome(
        call_count=1,
        request=probe.RequestObservation(
            controls_valid=True,
            effective_request=request_identity,
            expected_prepared_request_sha256=(request_identity.effective_values_sha256),
        ),
        response=None,
        failure=probe.SafeProviderFailure(
            kind="rejected",
            exception_class=exception_class,
            status_code=status_code,
            status_class="4xx",
            parameter="tools",
            remote_response_observed=True,
        ),
    )

    assert outcome.failure is not None
    assert outcome.failure.parameter == "tools"
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )
    assert receipt.verdict == "fail"
    assert receipt.reason_codes == ("configured_route_rejected_strict_request",)


@pytest.mark.asyncio
async def test_native_litellm_responses_success_is_one_request_and_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _probe()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        assert request.url.path == "/v1/responses"
        request_count += 1
        return httpx.Response(
            200,
            request=request,
            json=_native_responses_success(probe),
        )

    monkeypatch.setattr(
        AsyncHTTPHandler,
        "_create_async_transport",
        staticmethod(lambda **_kwargs: httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(litellm, "in_memory_llm_clients_cache", LLMClientCache())
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    route = _route(
        kwargs={
            "api_key": "test-key",
            "api_base": "https://one-shot-success.invalid/v1",
        }
    )
    outcome = await probe.run_probe_call(
        route=route,
        provider_completion=probe._litellm_provider_completion,
    )

    assert request_count == 1
    assert outcome.response is not None
    assert outcome.response.checks.all_pass is True
    source = _source(probe)
    runtime = _runtime(probe, route=route)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )
    assert receipt.verdict == "pass"
    assert receipt.reason_codes == ("strict_request_accepted_with_conformant_response",)


@pytest.mark.asyncio
async def test_native_incomplete_response_is_one_request_and_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _probe()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        assert request.url.path == "/v1/responses"
        request_count += 1
        return httpx.Response(
            200,
            request=request,
            json=_native_responses_incomplete(probe),
        )

    monkeypatch.setattr(
        AsyncHTTPHandler,
        "_create_async_transport",
        staticmethod(lambda **_kwargs: httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(litellm, "in_memory_llm_clients_cache", LLMClientCache())
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    route = _route(
        kwargs={
            "api_key": "test-key",
            "api_base": "https://one-shot-incomplete.invalid/v1",
        }
    )
    outcome = await probe.run_probe_call(
        route=route,
        provider_completion=probe._litellm_provider_completion,
    )

    assert request_count == 1
    assert outcome.response is not None
    assert outcome.response.finish_reason == "tool_calls"
    assert outcome.response.checks.all_pass is False
    source = _source(probe)
    runtime = _runtime(probe, route=route)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )
    assert receipt.verdict == "inconclusive"
    assert receipt.reason_codes == ("provider_response_nonconformant",)


def test_sealed_receipt_round_trips_offline_at_mode_0600(tmp_path: Path) -> None:
    probe = _probe()
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=_passing_outcome(probe),
    )

    path = probe.write_receipt(tmp_path / "probe", receipt)
    verified = probe.verify_receipt(path)

    assert os.stat(path).st_mode & 0o777 == 0o600
    assert verified.verdict == "pass"
    assert verified.reason_codes == (
        "strict_request_accepted_with_conformant_response",
    )


def test_offline_verifier_rejects_extra_fields_hash_and_verdict_tampering(
    tmp_path: Path,
) -> None:
    probe = _probe()
    source = _source(probe)
    runtime = _runtime(probe)
    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=_passing_outcome(probe),
    )
    payload = json.loads(receipt.model_dump_json())

    extra = {**payload, "raw_provider_error": "must never be accepted"}
    extra_path = tmp_path / "extra.json"
    extra_path.write_text(json.dumps(extra), encoding="utf-8")
    extra_path.chmod(0o600)
    with pytest.raises(probe.ReceiptVerificationError, match="strict contract"):
        probe.verify_receipt(extra_path)

    secret_arguments = json.loads(receipt.model_dump_json())
    secret_arguments["outcome"]["response"]["arguments"]["raw_secret"] = "nope"
    arguments_path = tmp_path / "arguments.json"
    arguments_path.write_text(json.dumps(secret_arguments), encoding="utf-8")
    arguments_path.chmod(0o600)
    with pytest.raises(probe.ReceiptVerificationError, match="strict contract"):
        probe.verify_receipt(arguments_path)

    payload["verdict"] = "fail"
    payload["receipt_sha256"] = probe.canonical_sha256(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    )
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(json.dumps(payload), encoding="utf-8")
    verdict_path.chmod(0o600)
    with pytest.raises(probe.ReceiptVerificationError, match="verdict"):
        probe.verify_receipt(verdict_path)


@pytest.mark.parametrize(
    ("kind", "exception_class", "status_code", "remote_response_observed"),
    [
        ("rejected", "authentication", 401, True),
        ("rejected", "permission_denied", 403, True),
        ("rate_limited", "rate_limit", 429, True),
        ("timeout", "timeout", None, False),
        ("transport_ambiguous", "service_unavailable", 503, True),
        ("transport_ambiguous", "api_connection", None, False),
        ("rejected", "bad_request", 400, False),
    ],
)
def test_non_capability_provider_failures_are_inconclusive(
    kind: str,
    exception_class: str,
    status_code: int | None,
    remote_response_observed: bool,
) -> None:
    probe = _probe()
    source = _source(probe)
    runtime = _runtime(probe)
    safe_kwargs = _empty_effective_identity(probe)
    request = probe.RequestObservation(
        controls_valid=True,
        effective_request=safe_kwargs,
        expected_prepared_request_sha256=safe_kwargs.effective_values_sha256,
    )
    outcome = probe.ProbeCallOutcome(
        call_count=1,
        request=request,
        response=None,
        failure=probe.SafeProviderFailure(
            kind=kind,
            exception_class=exception_class,
            status_code=status_code,
            status_class=f"{status_code // 100}xx" if status_code else None,
            parameter=(
                "tools"
                if exception_class in {"bad_request", "unprocessable_entity"}
                else None
            ),
            remote_response_observed=remote_response_observed,
        ),
    )

    receipt = probe.build_receipt(
        source_before=source,
        source_after=source,
        runtime_before=runtime,
        runtime_after=runtime,
        outcome=outcome,
    )

    assert receipt.verdict == "inconclusive"


def test_full_git_status_observation_marks_untracked_source_dirty() -> None:
    probe = _probe()

    identity = probe.source_identity_from_observations(
        revision="0" * 40,
        status="?? backend/scripts/untracked_probe.py\n",
    )

    assert identity.source_clean is False


@pytest.mark.asyncio
async def test_dirty_source_prevents_route_and_provider_calls(tmp_path: Path) -> None:
    probe = _probe()
    route_calls = 0
    provider_calls = 0

    async def resolve_runtime(_tenant_id: str) -> object:
        nonlocal route_calls
        route_calls += 1
        return _runtime(probe), _route()

    async def provider_completion(**_kwargs: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        return _raw_response(VALID_ARGUMENTS)

    path = await probe.run_live_probe(
        output_dir=tmp_path / "dirty",
        tenant_id="tenant",
        source_reader=lambda: _source(probe, clean=False),
        runtime_resolver=resolve_runtime,
        provider_completion=provider_completion,
    )
    verified = probe.verify_receipt(path)

    assert verified.verdict == "inconclusive"
    assert "source_not_clean" in verified.reason_codes
    assert route_calls == provider_calls == 0


@pytest.mark.asyncio
async def test_live_receipt_cannot_make_the_source_dirty() -> None:
    probe = _probe()

    with pytest.raises(ValueError, match="outside the source checkout"):
        await probe.run_live_probe(
            output_dir=probe.backend_dir / "probe-output",
            tenant_id="tenant",
        )


@pytest.mark.asyncio
async def test_live_probe_resolves_same_route_before_and_after_one_call(
    tmp_path: Path,
) -> None:
    probe = _probe()
    route_calls = 0
    provider_calls = 0

    async def resolve_runtime(_tenant_id: str) -> object:
        nonlocal route_calls
        route_calls += 1
        return _runtime(probe), _route()

    async def provider_completion(**_kwargs: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        return _raw_response(VALID_ARGUMENTS)

    path = await probe.run_live_probe(
        output_dir=tmp_path / "clean",
        tenant_id="tenant",
        source_reader=lambda: _source(probe),
        runtime_resolver=resolve_runtime,
        provider_completion=provider_completion,
    )

    assert probe.verify_receipt(path).verdict == "pass"
    assert route_calls == 2
    assert provider_calls == 1


def test_cli_has_no_model_override() -> None:
    probe = _probe()
    with pytest.raises(SystemExit):
        probe.parse_args(["--model-id", "another-model"])
