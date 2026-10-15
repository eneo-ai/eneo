"""How real LiteLLM failures against a provider are classified.

LiteLLM's exception mapping shifts between releases (an unknown model arrives
as BadRequestError, a refused connection as InternalServerError, a dropped
stream as a ServiceUnavailableError subclass), so these run the real client
against a local stub provider instead of constructing exceptions by hand.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from eneo.main.exceptions import OpenAIException, ProviderRejectedRequestException
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_transport import (
    classify_provider_failure,
    classify_stream_failure,
)

_HANG_SECONDS = 5


class _StubProvider(BaseHTTPRequestHandler):
    """Answers /<mode>/v1/chat/completions according to <mode>."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        mode = self.path.strip("/").split("/")[0]
        if mode == "hang":
            time.sleep(_HANG_SECONDS)
            return
        if mode in {"drop", "stream-hang"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = {
                "id": "x",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "delta": {"content": "Hej"}}],
            }
            data = f"data: {json.dumps(chunk)}\n\n".encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()
            if mode == "stream-hang":
                time.sleep(_HANG_SECONDS)
                self.close_connection = True
                return
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        status = int(mode)
        if status == 502:
            self._reply(status, b"<html>502 Bad Gateway</html>", "text/html")
            return
        body = json.dumps({"error": {"message": "stub", "type": "stub"}})
        self._reply(status, body.encode(), "application/json")


@pytest.fixture(scope="module")
def provider_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubProvider)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join()


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


async def _fail(
    api_base: str, *, stream: bool, received_text: list[str] | None = None
) -> BaseException:
    try:
        response = await litellm_transport.acompletion(
            model="openai/m",
            api_base=api_base,
            api_key="test-key",
            messages=[{"role": "user", "content": "hi"}],
            stream=stream,
            max_retries=0,
            timeout=httpx.Timeout(0.5, connect=0.5),
        )
        if stream:
            async for chunk in response:
                if received_text is not None:
                    received_text.append(chunk.choices[0].delta.content or "")
    except Exception as exc:
        return exc
    pytest.fail("the stub provider call succeeded")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("500", "provider_unavailable"),
        ("502", "provider_unavailable"),
        ("503", "provider_unavailable"),
        ("529", "provider_unavailable"),
        ("504", "provider_timeout"),
        ("429", "provider_rate_limited"),
        ("404", "provider_model_not_found"),
        ("400", "provider_rejected_request"),
        ("hang", "provider_timeout"),
    ],
)
async def test_provider_answers_are_classified_by_what_the_provider_did(
    provider_url, mode, code, stream
):
    exc = await _fail(f"{provider_url}/{mode}/v1", stream=stream)

    assert classify_provider_failure(exc).code == code


@pytest.mark.asyncio
async def test_a_refused_connection_is_unreachable_not_a_server_error():
    exc = await _fail(f"{_closed_port_url()}/v1", stream=True)

    failure = classify_provider_failure(exc)
    assert failure.code == "provider_unreachable"
    assert failure.unavailable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "code"),
    [("drop", "provider_connection_lost"), ("stream-hang", "provider_timeout")],
)
async def test_a_failed_stream_keeps_the_cause_after_receiving_text(
    provider_url, mode, code
):
    received_text: list[str] = []
    exc = await _fail(
        f"{provider_url}/{mode}/v1", stream=True, received_text=received_text
    )

    failure = classify_stream_failure(exc)
    assert "".join(received_text) == "Hej"
    assert failure is not None
    assert failure.code == code


@pytest.mark.parametrize(
    "exc",
    [ValueError("tool arguments did not parse"), KeyError("choices")],
)
def test_a_stream_failure_raised_by_eneo_is_not_blamed_on_the_provider(exc):
    assert classify_stream_failure(exc) is None


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("Connection refused by upstream", "provider_unreachable"),
        ("Temporary failure in name resolution", "provider_unreachable"),
        ("Connection reset by peer", "provider_connection_lost"),
        ("Read timed out", "provider_timeout"),
        ("503 Service Unavailable", "provider_unavailable"),
        ("provider timeout budget exceeded", "provider_error"),
    ],
)
def test_wrapped_failures_fall_back_to_the_message(message, code):
    assert classify_provider_failure(RuntimeError(message)).code == code


def test_an_already_classified_failure_keeps_its_reason():
    exc = OpenAIException("x", code="provider_timeout")

    assert classify_provider_failure(exc).code == "provider_timeout"


def test_public_errors_carry_the_reason_and_whether_a_retry_can_help():
    rejected = litellm_transport.PROVIDER_REJECTED_REQUEST.to_exception()
    missing = litellm_transport.PROVIDER_MODEL_NOT_FOUND.to_exception()
    down = litellm_transport.PROVIDER_UNAVAILABLE.to_exception()

    assert isinstance(rejected, ProviderRejectedRequestException)
    assert missing.details == {
        "reason": "provider_model_not_found",
        "retryable": False,
    }
    assert down.code == "provider_unavailable"
    assert down.details == {"reason": "provider_unavailable", "retryable": True}
