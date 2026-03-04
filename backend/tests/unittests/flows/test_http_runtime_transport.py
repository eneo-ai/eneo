from __future__ import annotations

import ipaddress

import httpx
import pytest

from intric.flows.runtime import http_runtime as http_runtime_module
from intric.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from intric.main.exceptions import TypedIOValidationException


class _Resolver:
    def interpolate(self, value: str, context: dict) -> str:
        return value


def _build_helper() -> FlowHttpRuntimeHelper:
    return FlowHttpRuntimeHelper(
        variable_resolver=_Resolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=30,
        allow_private_networks=False,
    )


@pytest.mark.asyncio
async def test_send_request_enforces_stream_cap(monkeypatch) -> None:
    helper = _build_helper()

    class _FakeStreamResponse:
        status_code = 200
        headers = {}

        async def aiter_bytes(self):
            yield b"1234"
            yield b"56789"

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    settings = http_runtime_module.get_settings()
    original_max = settings.flow_max_inline_text_bytes
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", 8)
    monkeypatch.setattr(http_runtime_module.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(TypedIOValidationException) as exc:
        await helper.send_request(
            method="GET",
            url="https://example.org/capped",
            headers={},
            timeout_seconds=5,
            preflight_resolved_ips={ipaddress.ip_address("93.184.216.34")},
            assert_connected_peer_allowed=lambda **_: None,
        )

    assert exc.value.code == "typed_io_http_response_too_large"
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", original_max)


@pytest.mark.asyncio
async def test_send_request_skips_body_read_for_webhook(monkeypatch) -> None:
    helper = _build_helper()

    class _FakeStreamResponse:
        status_code = 204
        headers = {"X-Test": "1"}

        async def aiter_bytes(self):
            raise AssertionError("aiter_bytes should not be called when read_response_body=False")

        async def aclose(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    monkeypatch.setattr(http_runtime_module.httpx, "AsyncClient", _FakeClient)
    response = await helper.send_request(
        method="POST",
        url="https://example.org/webhook",
        headers={},
        timeout_seconds=5,
        read_response_body=False,
        preflight_resolved_ips={ipaddress.ip_address("93.184.216.34")},
        assert_connected_peer_allowed=lambda **_: None,
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_send_request_closes_stream_when_peer_assertion_fails(monkeypatch) -> None:
    helper = _build_helper()
    close_state = {"closed": False}

    class _FakeStreamResponse:
        status_code = 200
        headers = {}

        async def aiter_bytes(self):
            yield b"ok"

        async def aclose(self) -> None:
            close_state["closed"] = True

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(method, url, headers=headers, content=content, json=json)

        async def send(self, request, stream=True):
            return _FakeStreamResponse()

    monkeypatch.setattr(http_runtime_module.httpx, "AsyncClient", _FakeClient)

    def _raise_peer_assertion(**_: object) -> None:
        raise TypedIOValidationException(
            "Unable to verify HTTP peer address.",
            code="typed_io_http_connection_error",
        )

    with pytest.raises(TypedIOValidationException, match="peer address"):
        await helper.send_request(
            method="GET",
            url="https://example.org/fail-peer",
            headers={},
            timeout_seconds=5,
            preflight_resolved_ips={ipaddress.ip_address("93.184.216.34")},
            assert_connected_peer_allowed=_raise_peer_assertion,
        )

    assert close_state["closed"] is True
