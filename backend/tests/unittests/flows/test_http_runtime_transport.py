from __future__ import annotations

import httpx
import pytest

from eneo.flows.runtime import http_runtime as http_runtime_module
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.main.exceptions import TypedIOValidationException


class _Resolver:
    def interpolate(self, value: str, context: dict) -> str:
        return value


def _build_helper(client_factory) -> FlowHttpRuntimeHelper:
    return FlowHttpRuntimeHelper(
        variable_resolver=_Resolver(),
        request_timeout_seconds=5,
        max_timeout_seconds=30,
        allow_private_networks=False,
        client_factory=client_factory,
    )


@pytest.mark.asyncio
async def test_send_request_enforces_stream_cap(monkeypatch) -> None:
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
    helper = _build_helper(_FakeClient)

    with pytest.raises(TypedIOValidationException) as exc:
        await helper.send_request(
            method="GET",
            url="https://example.org/capped",
            headers={},
            timeout_seconds=5,
        )

    assert exc.value.code == "typed_io_http_response_too_large"
    assert consumed_chunks == [b"1234", b"56789"]
    assert close_state["closed"] is True
    monkeypatch.setattr(settings, "flow_max_inline_text_bytes", original_max)


@pytest.mark.asyncio
async def test_send_request_skips_body_read_for_webhook() -> None:
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

    helper = _build_helper(_FakeClient)
    response = await helper.send_request(
        method="POST",
        url="https://example.org/webhook",
        headers={},
        timeout_seconds=5,
        read_response_body=False,
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_send_request_refuses_compressed_responses() -> None:
    """The cap bounds raw response-body bytes: a gzip body can expand orders of magnitude
    in one decode call, so compressed replies are refused outright and the
    request advertises identity encoding."""
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

    helper = _build_helper(_FakeClient)
    with pytest.raises(TypedIOValidationException) as exc:
        await helper.send_request(
            method="GET",
            url="https://example.org/data",
            # A case-variant authored value must be REPLACED, not duplicated:
            # httpx would otherwise serialize "gzip, identity" and let the
            # server pick gzip.
            headers={"accept-encoding": "gzip"},
            timeout_seconds=5,
        )

    assert exc.value.code == "typed_io_http_response_too_large"
    assert seen_request_headers.get("accept-encoding") == ["identity"]
    assert fake_response.closed is True
