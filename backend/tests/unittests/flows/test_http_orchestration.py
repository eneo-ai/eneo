from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from intric.flows.runtime.http_orchestration import (
    deliver_webhook,
    resolve_http_input_source_text,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException


@dataclass
class _Step:
    step_order: int
    step_id: str
    input_type: str
    input_source: str
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    user_description: str | None = None


@dataclass
class _Run:
    id: str
    flow_id: str
    tenant_id: str


@dataclass
class _Deps:
    encryption_service: Any
    variable_resolver: Any
    resolve_timeout_seconds: Any
    build_headers: Any
    resolve_request_body: Any
    read_response_text: Any
    send_http_request: Any
    audit_http_outbound: Any


def _make_deps(
    *,
    send_http_request: Any,
    read_response_text: Any | None = None,
) -> _Deps:
    resolver = SimpleNamespace(interpolate=lambda value, context: value)
    return _Deps(
        encryption_service=object(),
        variable_resolver=resolver,
        resolve_timeout_seconds=lambda value, **_: 5.0,
        build_headers=lambda value, **_: {"X-Test": "1"},
        resolve_request_body=lambda **_: (None, None),
        read_response_text=read_response_text or (lambda **_: "ok"),
        send_http_request=send_http_request,
        audit_http_outbound=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_json_success_audits_success() -> None:
    step = _Step(
        step_order=1,
        step_id="s1",
        input_type="json",
        input_source="http_get",
        input_config={"url": "https://example.org/data"},
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, json={"a": 1}),
    )
    deps = _make_deps(send_http_request=send_http_request, read_response_text=lambda **_: '{"a":1}')

    text, structured = await resolve_http_input_source_text(
        step=step,
        run=run,
        context={},
        deps=deps,
    )

    assert text == '{"a": 1}'
    assert structured == {"a": 1}
    deps.audit_http_outbound.assert_awaited()
    assert deps.audit_http_outbound.await_args.kwargs["call_type"] == "http_input"


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_timeout_maps_to_typed_code() -> None:
    step = _Step(
        step_order=2,
        step_id="s2",
        input_type="text",
        input_source="http_get",
        input_config={"url": "https://example.org/data"},
    )
    run = _Run(id="run-2", flow_id="flow-1", tenant_id="tenant-1")
    send_http_request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_http_input_source_text(step=step, run=run, context={}, deps=deps)

    assert exc.value.code == "typed_io_http_timeout"
    deps.audit_http_outbound.assert_awaited()


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_non_success_maps_to_typed_code() -> None:
    step = _Step(
        step_order=3,
        step_id="s3",
        input_type="text",
        input_source="http_get",
        input_config={"url": "https://example.org/data"},
    )
    run = _Run(id="run-3", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(return_value=httpx.Response(503, request=request, text="unavailable"))
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_http_input_source_text(step=step, run=run, context={}, deps=deps)

    assert exc.value.code == "typed_io_http_non_success"


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_malformed_json_maps_to_typed_code() -> None:
    step = _Step(
        step_order=31,
        step_id="s31",
        input_type="json",
        input_source="http_get",
        input_config={"url": "https://example.org/data"},
    )
    run = _Run(id="run-31", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(return_value=httpx.Response(200, request=request, text="not-json"))
    deps = _make_deps(send_http_request=send_http_request, read_response_text=lambda **_: "not-json")

    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_http_input_source_text(step=step, run=run, context={}, deps=deps)

    assert exc.value.code == "typed_io_http_malformed_response"
    deps.audit_http_outbound.assert_awaited()
    audit_kwargs = deps.audit_http_outbound.await_args.kwargs
    assert audit_kwargs["outcome"].name == "FAILURE"
    assert audit_kwargs["status_code"] == 200


@pytest.mark.asyncio
async def test_deliver_webhook_timeout_maps_to_bad_request_and_audits() -> None:
    step = _Step(
        step_order=4,
        step_id="step-4",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "https://example.org/webhook"},
    )
    run = _Run(id="run-4", flow_id="flow-1", tenant_id="tenant-1")
    send_http_request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(BadRequestException) as exc:
        await deliver_webhook(
            step=step,
            text_payload="payload",
            run=run,
            context={},
            deps=deps,
        )

    assert "timed out" in str(exc.value)
    deps.audit_http_outbound.assert_awaited()
    assert deps.audit_http_outbound.await_args.kwargs["call_type"] == "webhook_delivery"


@pytest.mark.asyncio
async def test_deliver_webhook_requires_url_in_output_config() -> None:
    step = _Step(
        step_order=41,
        step_id="step-41",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "   "},
    )
    run = _Run(id="run-41", flow_id="flow-1", tenant_id="tenant-1")
    deps = _make_deps(send_http_request=AsyncMock())

    with pytest.raises(BadRequestException, match="output_config.url"):
        await deliver_webhook(
            step=step,
            text_payload="payload",
            run=run,
            context={},
            deps=deps,
        )

    deps.audit_http_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_webhook_maps_typed_transport_error_to_bad_request() -> None:
    step = _Step(
        step_order=42,
        step_id="step-42",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "https://example.org/webhook"},
    )
    run = _Run(id="run-42", flow_id="flow-1", tenant_id="tenant-1")
    send_http_request = AsyncMock(
        side_effect=TypedIOValidationException(
            "HTTP URL blocked by SSRF policy.",
            code="typed_io_http_ssrf_blocked",
        )
    )
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(BadRequestException, match="SSRF policy"):
        await deliver_webhook(
            step=step,
            text_payload="payload",
            run=run,
            context={},
            deps=deps,
        )

    deps.audit_http_outbound.assert_awaited_once()
    audit_kwargs = deps.audit_http_outbound.await_args.kwargs
    assert audit_kwargs["call_type"] == "webhook_delivery"
    assert audit_kwargs["outcome"].name == "FAILURE"


@pytest.mark.asyncio
async def test_deliver_webhook_sets_idempotency_key() -> None:
    step = _Step(
        step_order=5,
        step_id="step-5",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "https://example.org/webhook"},
    )
    run = _Run(id="run-5", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("POST", "https://example.org/webhook")
    send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))
    deps = _make_deps(send_http_request=send_http_request)

    await deliver_webhook(
        step=step,
        text_payload="payload",
        run=run,
        context={},
        deps=deps,
    )

    kwargs = send_http_request.await_args.kwargs
    assert kwargs["headers"]["Idempotency-Key"]
    assert len(kwargs["headers"]["Idempotency-Key"]) == 64


@pytest.mark.asyncio
async def test_deliver_webhook_retry_keeps_same_idempotency_key_after_partial_failure() -> None:
    step = _Step(
        step_order=6,
        step_id="step-6",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "https://example.org/webhook"},
    )
    run = _Run(id="run-6", flow_id="flow-1", tenant_id="tenant-1")
    keys: list[str] = []

    async def _send_http_request(**kwargs):
        keys.append(kwargs["headers"]["Idempotency-Key"])
        if len(keys) == 1:
            raise httpx.TimeoutException("timeout")
        request = httpx.Request("POST", "https://example.org/webhook")
        return httpx.Response(200, request=request)

    deps = _make_deps(send_http_request=_send_http_request)

    with pytest.raises(BadRequestException, match="timed out"):
        await deliver_webhook(
            step=step,
            text_payload="payload",
            run=run,
            context={},
            deps=deps,
        )

    await deliver_webhook(
        step=step,
        text_payload="payload",
        run=run,
        context={},
        deps=deps,
    )

    assert len(keys) == 2
    assert keys[0] == keys[1]
    assert deps.audit_http_outbound.await_count == 2
    first_outcome = deps.audit_http_outbound.await_args_list[0].kwargs["outcome"]
    second_outcome = deps.audit_http_outbound.await_args_list[1].kwargs["outcome"]
    assert first_outcome.name == "FAILURE"
    assert second_outcome.name == "SUCCESS"
