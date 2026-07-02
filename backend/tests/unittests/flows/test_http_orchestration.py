from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from eneo.flows.runtime.http_orchestration import (
    deliver_webhook,
    resolve_http_input_source_text,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import BadRequestException, TypedIOValidationException


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
    read_response_text: Any
    send_http_request: Any
    audit_http_outbound: Any


class _EncryptionService:
    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith("enc:")

    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


def _make_deps(
    *,
    send_http_request: Any,
    read_response_text: Any | None = None,
    encryption_service: object | None = None,
    variable_resolver: object | None = None,
    resolve_timeout_seconds: object | None = None,
) -> _Deps:
    resolver = SimpleNamespace(interpolate=lambda value, context: value)
    return _Deps(
        encryption_service=encryption_service or object(),
        variable_resolver=variable_resolver or resolver,
        resolve_timeout_seconds=resolve_timeout_seconds or (lambda value, **_: 5.0),
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
        input_config={"url": "https://example.org/data", "auth": {"mode": "none"}},
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, json={"a": 1}),
    )
    deps = _make_deps(
        send_http_request=send_http_request, read_response_text=lambda **_: '{"a":1}'
    )

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
async def test_resolve_http_input_source_text_authored_config_compiles_request() -> (
    None
):
    runtime_http = FlowHttpRuntimeHelper(
        variable_resolver=FlowVariableResolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=10,
        allow_private_networks=True,
    )
    step = _Step(
        step_order=2,
        step_id="s2",
        input_type="json",
        input_source="http_post",
        input_config={
            "url": "https://api.example.test/items/{{ flow_input.request_id }}",
            "auth": {
                "mode": "bearer_token",
                "token": "enc:{{ step_1.output.token }}",
            },
            "timeout_seconds": 9,
            "body": {
                "mode": "json_template",
                "template": (
                    '{"request_id": {{ flow_input.request_id }}, '
                    '"token": "{{ step_1.output.token }}"}'
                ),
            },
            "custom_headers": [
                {
                    "name": "X-Trace",
                    "value": "{{ step_1.output.trace_id }}",
                    "secret": False,
                }
            ],
            "response_format": "json",
        },
    )
    run = _Run(id="run-2", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("POST", "https://api.example.test/items/42")
    send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, json={"ok": True}),
    )
    deps = _make_deps(
        send_http_request=send_http_request,
        encryption_service=_EncryptionService(),
        variable_resolver=runtime_http.variable_resolver,
        resolve_timeout_seconds=runtime_http.resolve_timeout_seconds,
        read_response_text=lambda **_: '{"ok": true}',
    )

    text, structured = await resolve_http_input_source_text(
        step=step,
        run=run,
        context={
            "flow_input": {"request_id": 42},
            "step_1": {"output": {"token": "runtime-token", "trace_id": "trace-42"}},
        },
        deps=deps,
    )

    kwargs = send_http_request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://api.example.test/items/42"
    assert kwargs["headers"]["Authorization"] == "Bearer runtime-token"
    assert kwargs["headers"]["X-Trace"] == "trace-42"
    assert kwargs["timeout_seconds"] == 9.0
    assert kwargs["body_bytes"] is None
    assert kwargs["json_body"] == {"request_id": 42, "token": "runtime-token"}
    assert text == '{"ok": true}'
    assert structured == {"ok": True}


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_rejects_flat_config_before_send() -> None:
    step = _Step(
        step_order=12,
        step_id="s12",
        input_type="text",
        input_source="http_get",
        input_config={"url": "https://example.org/data"},
    )
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="ok")
    )
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(TypedIOValidationException, match="authored HTTP config") as exc:
        await resolve_http_input_source_text(
            step=step,
            run=_Run(id="run-12", flow_id="flow-1", tenant_id="tenant-1"),
            context={},
            deps=deps,
        )

    assert exc.value.code == "typed_io_http_invalid_config"
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_authored_timeout_uses_runtime_cap() -> (
    None
):
    runtime_http = FlowHttpRuntimeHelper(
        variable_resolver=FlowVariableResolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=10,
        allow_private_networks=True,
    )
    step = _Step(
        step_order=21,
        step_id="s21",
        input_type="text",
        input_source="http_get",
        input_config={
            "url": "https://api.example.test/items",
            "auth": {"mode": "none"},
            "timeout_seconds": 11,
        },
    )
    deps = _make_deps(
        send_http_request=AsyncMock(),
        variable_resolver=runtime_http.variable_resolver,
        resolve_timeout_seconds=runtime_http.resolve_timeout_seconds,
    )

    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_http_input_source_text(
            step=step,
            run=_Run(id="run-21", flow_id="flow-1", tenant_id="tenant-1"),
            context={},
            deps=deps,
        )

    assert exc.value.code == "typed_io_http_invalid_config"


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_timeout_maps_to_typed_code() -> None:
    step = _Step(
        step_order=2,
        step_id="s2",
        input_type="text",
        input_source="http_get",
        input_config={"url": "https://example.org/data", "auth": {"mode": "none"}},
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
        input_config={"url": "https://example.org/data", "auth": {"mode": "none"}},
    )
    run = _Run(id="run-3", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(
        return_value=httpx.Response(503, request=request, text="unavailable")
    )
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_http_input_source_text(step=step, run=run, context={}, deps=deps)

    assert exc.value.code == "typed_io_http_non_success"


@pytest.mark.asyncio
async def test_resolve_http_input_source_text_malformed_json_maps_to_typed_code() -> (
    None
):
    step = _Step(
        step_order=31,
        step_id="s31",
        input_type="json",
        input_source="http_get",
        input_config={"url": "https://example.org/data", "auth": {"mode": "none"}},
    )
    run = _Run(id="run-31", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("GET", "https://example.org/data")
    send_http_request = AsyncMock(
        return_value=httpx.Response(200, request=request, text="not-json")
    )
    deps = _make_deps(
        send_http_request=send_http_request, read_response_text=lambda **_: "not-json"
    )

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
        output_config={
            "url": "https://example.org/webhook",
            "auth": {"mode": "none"},
        },
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
            idempotency_key="run-4:step-4:1:webhook",
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
        output_config={"url": "   ", "auth": {"mode": "none"}},
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
            idempotency_key="run-41:step-41:1:webhook",
        )

    deps.audit_http_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_webhook_maps_typed_transport_error_to_bad_request() -> None:
    step = _Step(
        step_order=42,
        step_id="step-42",
        input_type="text",
        input_source="flow_input",
        output_config={
            "url": "https://example.org/webhook",
            "auth": {"mode": "none"},
        },
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
            idempotency_key="run-42:step-42:1:webhook",
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
        output_config={
            "url": "https://example.org/webhook",
            "auth": {"mode": "none"},
        },
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
        idempotency_key="run-5:step-5:3:webhook",
    )

    kwargs = send_http_request.await_args.kwargs
    assert (
        kwargs["headers"]["Idempotency-Key"]
        == hashlib.sha256(b"run-5:step-5:3:webhook").hexdigest()
    )


@pytest.mark.asyncio
async def test_deliver_webhook_authored_config_compiles_request() -> None:
    runtime_http = FlowHttpRuntimeHelper(
        variable_resolver=FlowVariableResolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=10,
        allow_private_networks=True,
    )
    step = _Step(
        step_order=51,
        step_id="step-51",
        input_type="text",
        input_source="flow_input",
        output_config={
            "url": "https://hooks.example.test/{{ step_1.output.endpoint }}",
            "auth": {"mode": "none"},
            "timeout_seconds": 7,
            "body": {
                "mode": "text_template",
                "template": "done={{ step_1.output.token }}",
            },
            "custom_headers": [
                {
                    "name": "X-Trace",
                    "value": "{{ step_1.output.trace_id }}",
                    "secret": False,
                }
            ],
        },
    )
    run = _Run(id="run-51", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("POST", "https://hooks.example.test/complete")
    send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))
    deps = _make_deps(
        send_http_request=send_http_request,
        variable_resolver=runtime_http.variable_resolver,
        resolve_timeout_seconds=runtime_http.resolve_timeout_seconds,
    )

    await deliver_webhook(
        step=step,
        text_payload="fallback",
        run=run,
        context={
            "step_1": {
                "output": {
                    "endpoint": "complete",
                    "token": "runtime-token",
                    "trace_id": "trace-42",
                }
            }
        },
        deps=deps,
        idempotency_key="run-51:step-51:1:webhook",
    )

    kwargs = send_http_request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://hooks.example.test/complete"
    assert kwargs["headers"]["X-Trace"] == "trace-42"
    assert (
        kwargs["headers"]["Idempotency-Key"]
        == hashlib.sha256(b"run-51:step-51:1:webhook").hexdigest()
    )
    assert kwargs["timeout_seconds"] == 7.0
    assert kwargs["body_bytes"] == b"done=runtime-token"
    assert kwargs["json_body"] is None
    assert kwargs["read_response_body"] is False


@pytest.mark.asyncio
async def test_deliver_webhook_authored_auto_body_uses_text_payload() -> None:
    runtime_http = FlowHttpRuntimeHelper(
        variable_resolver=FlowVariableResolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=10,
        allow_private_networks=True,
    )
    step = _Step(
        step_order=52,
        step_id="step-52",
        input_type="text",
        input_source="flow_input",
        output_config={
            "url": "https://hooks.example.test/auto",
            "auth": {"mode": "none"},
            "timeout_seconds": 6,
            "body": {"mode": "auto"},
            "custom_headers": [
                {
                    "name": "X-Trace",
                    "value": "{{ step_1.output.trace_id }}",
                    "secret": False,
                }
            ],
        },
    )
    run = _Run(id="run-52", flow_id="flow-1", tenant_id="tenant-1")
    request = httpx.Request("POST", "https://hooks.example.test/auto")
    send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))
    deps = _make_deps(
        send_http_request=send_http_request,
        variable_resolver=runtime_http.variable_resolver,
        resolve_timeout_seconds=runtime_http.resolve_timeout_seconds,
    )

    await deliver_webhook(
        step=step,
        text_payload="payload",
        run=run,
        context={"step_1": {"output": {"trace_id": "trace-52"}}},
        deps=deps,
        idempotency_key="run-52:step-52:1:webhook",
    )

    kwargs = send_http_request.await_args.kwargs
    assert kwargs["headers"]["X-Trace"] == "trace-52"
    assert kwargs["body_bytes"] == b"payload"
    assert kwargs["json_body"] is None


@pytest.mark.asyncio
async def test_deliver_webhook_rejects_flat_config_before_send() -> None:
    step = _Step(
        step_order=53,
        step_id="step-53",
        input_type="text",
        input_source="flow_input",
        output_config={"url": "https://example.org/webhook"},
    )
    request = httpx.Request("POST", "https://example.org/webhook")
    send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))
    deps = _make_deps(send_http_request=send_http_request)

    with pytest.raises(BadRequestException, match="authored HTTP config"):
        await deliver_webhook(
            step=step,
            text_payload="payload",
            run=_Run(id="run-53", flow_id="flow-1", tenant_id="tenant-1"),
            context={},
            deps=deps,
            idempotency_key="run-53:step-53:1:webhook",
        )

    send_http_request.assert_not_awaited()
    deps.audit_http_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_webhook_retry_keeps_same_idempotency_key_after_partial_failure() -> (
    None
):
    step = _Step(
        step_order=6,
        step_id="step-6",
        input_type="text",
        input_source="flow_input",
        output_config={
            "url": "https://example.org/webhook",
            "auth": {"mode": "none"},
        },
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
            idempotency_key="run-6:step-6:4:webhook",
        )

    await deliver_webhook(
        step=step,
        text_payload="payload",
        run=run,
        context={},
        deps=deps,
        idempotency_key="run-6:step-6:4:webhook",
    )

    assert len(keys) == 2
    assert keys[0] == keys[1]
    assert deps.audit_http_outbound.await_count == 2
    first_outcome = deps.audit_http_outbound.await_args_list[0].kwargs["outcome"]
    second_outcome = deps.audit_http_outbound.await_args_list[1].kwargs["outcome"]
    assert first_outcome.name == "FAILURE"
    assert second_outcome.name == "SUCCESS"
