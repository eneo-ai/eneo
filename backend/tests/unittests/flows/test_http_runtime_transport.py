from __future__ import annotations

import ipaddress

import httpx
import pytest

from eneo.flows.runtime import http_runtime as http_runtime_module
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.main.exceptions import TypedIOValidationException


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
    consumed_chunks: list[bytes] = []
    close_state = {"closed": False}

    class _FakeStreamResponse:
        status_code = 200
        headers = {}

        async def aiter_raw(self):
            for chunk in (b"1234", b"56789", b"unread"):
                consumed_chunks.append(chunk)
                yield chunk

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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
    assert consumed_chunks == [b"1234", b"56789"]
    assert close_state["closed"] is True
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", original_max)


@pytest.mark.asyncio
async def test_send_request_skips_body_read_for_webhook(monkeypatch) -> None:
    helper = _build_helper()

    class _FakeStreamResponse:
        status_code = 204
        headers = {"X-Test": "1"}

        async def aiter_raw(self):
            raise AssertionError(
                "aiter_raw should not be called when read_response_body=False"
            )

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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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
async def test_send_request_closes_stream_when_peer_assertion_fails(
    monkeypatch,
) -> None:
    helper = _build_helper()
    close_state = {"closed": False}

    class _FakeStreamResponse:
        status_code = 200
        headers = {}

        async def aiter_raw(self):
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
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

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


@pytest.mark.asyncio
async def test_send_request_validates_peer_while_stream_is_open(monkeypatch) -> None:
    """The DNS-rebinding defence only means something while the connection is
    alive: the peer assertion must run on the streamed response BEFORE any
    body byte is consumed and BEFORE the response closes."""
    helper = _build_helper()
    events: list[str] = []

    class _FakeStreamResponse:
        status_code = 200
        headers = {}

        def __init__(self) -> None:
            self.closed = False

        async def aiter_raw(self):
            events.append("body_read")
            yield b"ok"

        async def aclose(self) -> None:
            self.closed = True
            events.append("closed")

    fake_response = _FakeStreamResponse()

    client_state = {"open": False}

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            client_state["open"] = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            client_state["open"] = False
            events.append("client_closed")
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

        async def send(self, request, stream=True):
            return fake_response

    def _peer_spy(*, response, preflight_resolved_ips):
        # The original defect: the peer re-check ran after the client context
        # had closed. The connection must still be alive here.
        assert client_state["open"] is True
        assert response is fake_response
        assert response.closed is False
        events.append("peer_checked")

    monkeypatch.setattr(http_runtime_module.httpx, "AsyncClient", _FakeClient)
    result = await helper.send_request(
        method="GET",
        url="https://example.org/data",
        headers={},
        timeout_seconds=5,
        preflight_resolved_ips={ipaddress.ip_address("93.184.216.34")},
        assert_connected_peer_allowed=_peer_spy,
    )

    assert result.status_code == 200
    assert events == ["peer_checked", "body_read", "closed", "client_closed"]


@pytest.mark.asyncio
async def test_send_request_refuses_compressed_responses(monkeypatch) -> None:
    """The cap bounds raw response-body bytes: a gzip body can expand orders of magnitude
    in one decode call, so compressed replies are refused outright and the
    request advertises identity encoding."""
    helper = _build_helper()
    seen_request_headers: dict[str, list[str]] = {}

    class _FakeStreamResponse:
        status_code = 200
        headers = {"content-encoding": "gzip"}

        def __init__(self) -> None:
            self.closed = False

        async def aiter_raw(self):
            raise AssertionError("body must not be read for compressed replies")
            yield b""  # pragma: no cover

        async def aclose(self) -> None:
            self.closed = True

    fake_response = _FakeStreamResponse()

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def build_request(self, method, url, headers=None, content=None, json=None):
            normalized = httpx.Headers(headers)
            for key in {k.lower() for k, _ in normalized.multi_items()}:
                seen_request_headers[key] = normalized.get_list(key)
            return httpx.Request(
                method, url, headers=headers, content=content, json=json
            )

        async def send(self, request, stream=True):
            return fake_response

    monkeypatch.setattr(http_runtime_module.httpx, "AsyncClient", _FakeClient)
    with pytest.raises(TypedIOValidationException) as exc:
        await helper.send_request(
            method="GET",
            url="https://example.org/data",
            # A case-variant authored value must be REPLACED, not duplicated:
            # httpx would otherwise serialize "gzip, identity" and let the
            # server pick gzip.
            headers={"accept-encoding": "gzip"},
            timeout_seconds=5,
            preflight_resolved_ips={ipaddress.ip_address("93.184.216.34")},
            assert_connected_peer_allowed=lambda **_: None,
        )

    assert exc.value.code == "typed_io_http_response_too_large"
    assert seen_request_headers.get("accept-encoding") == ["identity"]
    assert fake_response.closed is True
