"""Transport capture: configured outbound headers reach the wire, byte-identical.

The permanent form of the spike in temp/prd.md Appendix B. Everything runs
through the real Eneo adapters and real LiteLLM against a loopback HTTP server
that records what arrives at the socket. Patching litellm_transport would only
prove Eneo passes a kwarg; a LiteLLM bump that stops putting ``extra_headers``
on the wire (or starts following redirects) must fail here.

Route: hosted_vllm, the only one v1 allows headers on.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import litellm
import pytest
from cryptography.fernet import Fernet

from eneo.completion_models.infrastructure.adapters import tenant_model_adapter
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.embedding_models.infrastructure.adapters import litellm_embeddings
from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.internal_mcp import image_generation
from eneo.main.config import get_settings
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.model_providers.domain.outbound_headers import OutboundHeader
from eneo.model_providers.infrastructure import outbound_headers_runtime
from eneo.model_providers.infrastructure.outbound_headers_runtime import (
    ProviderOutboundHeaders,
    apply_outbound_headers,
)
from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)
from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN
from eneo.settings.encryption_service import EncryptionService
from eneo.transcription_models.infrastructure.adapters import litellm_transcription
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
)

DEPARTMENT = "Miljö och hälsa"
CREDENTIAL = "sk-bf-aGVsbG8="
EXPECTED_ON_WIRE = {
    "x-org-unit": "Milj%C3%B6 och h%C3%A4lsa",
    "x-credential": CREDENTIAL,
    "region": "eu-north",
}
# What LiteLLM's HTTP client sends on its own for hosted_vllm (names only; the
# accept-encoding value depends on installed codecs). If a LiteLLM bump changes
# this set, review the reserved-name list in outbound_headers.py.
ADAPTER_HEADERS = {
    "host",
    "accept",
    "accept-encoding",
    "connection",
    "user-agent",
    "authorization",
    "content-type",
    "content-length",
}
# Added below LiteLLM when OpenTelemetry's HTTP client instrumentation is active
# (main/observability.py) — which is why they are reserved header names.
OTEL_PROPAGATION_HEADERS = {"traceparent", "tracestate", "baggage"}


# --- loopback provider -------------------------------------------------------


@dataclass
class Captured:
    path: str
    headers: list[tuple[str, str]]
    body: bytes

    def values(self, name: str) -> list[str]:
        return [v for k, v in self.headers if k.lower() == name.lower()]

    def names(self) -> set[str]:
        return {k.lower() for k, _ in self.headers}


def _chunk(delta: dict[str, Any], finish: str | None = None) -> str:
    choice = {"index": 0, "delta": delta, "finish_reason": finish}
    return "data: " + json.dumps(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [choice],
        }
    )


def _completion_body(request: dict[str, Any]) -> tuple[str, bytes]:
    wants_tool = bool(request.get("tools")) and not any(
        message.get("role") == "tool" for message in request.get("messages", [])
    )
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "server__tool", "arguments": "{}"},
    }
    if request.get("stream"):
        if wants_tool:
            chunks = [
                _chunk(
                    {"role": "assistant", "tool_calls": [{"index": 0, **tool_call}]}
                ),
                _chunk({}, "tool_calls"),
            ]
        else:
            chunks = [
                _chunk({"role": "assistant", "content": "streamed answer"}),
                _chunk({}, "stop"),
            ]
        return "text/event-stream", (
            "\n\n".join([*chunks, "data: [DONE]"]) + "\n\n"
        ).encode()
    message: dict[str, Any] = {"role": "assistant", "content": "plain answer"}
    finish = "stop"
    if wants_tool:
        message, finish = (
            {"role": "assistant", "content": None, "tool_calls": [tool_call]},
            "tool_calls",
        )
    body = {
        "id": "c",
        "object": "chat.completion",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return "application/json", json.dumps(body).encode()


@dataclass
class LoopbackProvider:
    server: ThreadingHTTPServer
    captured: list[Captured] = field(default_factory=list)
    redirect_to: str | None = None
    fail_with: int | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"


def _serve() -> LoopbackProvider:
    provider: LoopbackProvider

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server API
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            provider.captured.append(
                Captured(self.path, list(self.headers.items()), body)
            )
            if provider.redirect_to is not None:
                self.send_response(302)
                self.send_header("Location", provider.redirect_to + self.path)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if provider.fail_with is not None:
                payload = json.dumps(
                    {"error": {"message": "upstream failure", "type": "server_error"}}
                ).encode()
                self.send_response(provider.fail_with)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.endswith("/chat/completions"):
                content_type, payload = _completion_body(json.loads(body))
            elif self.path.endswith("/embeddings"):
                content_type, payload = (
                    "application/json",
                    json.dumps(
                        {
                            "object": "list",
                            "model": "m",
                            "data": [
                                {
                                    "object": "embedding",
                                    "index": 0,
                                    "embedding": [0.1, 0.2],
                                }
                            ],
                            "usage": {"prompt_tokens": 1, "total_tokens": 1},
                        }
                    ).encode(),
                )
            else:
                content_type, payload = (
                    "application/json",
                    json.dumps({"text": "hej"}).encode(),
                )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    provider = LoopbackProvider(server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return provider


@pytest.fixture
def loopback() -> Iterator[LoopbackProvider]:
    provider = _serve()
    yield provider
    provider.server.shutdown()


@pytest.fixture
def second_loopback() -> Iterator[LoopbackProvider]:
    provider = _serve()
    yield provider
    provider.server.shutdown()


# --- fixtures: provider, user, headers ---------------------------------------


def _resolver(endpoint: str | None) -> TenantModelCredentialResolver:
    return TenantModelCredentialResolver(
        provider_id=uuid4(),
        provider_type="hosted_vllm",
        credentials={},
        config={"endpoint": endpoint} if endpoint else {},
        encryption_service=EncryptionService(None),
    )


def _user() -> Any:
    return SimpleNamespace(
        id=uuid4(),
        external_id="ext-1",
        scim_extensions={SCIM_ENTERPRISE_USER_URN: {"department": DEPARTMENT}},
    )


def _headers(user: Any = None) -> ProviderOutboundHeaders:
    return ProviderOutboundHeaders(
        provider_id=uuid4(),
        provider_type="hosted_vllm",
        headers=(
            OutboundHeader(id="1", name="X-Org-Unit", value="{{user.department}}"),
            OutboundHeader(
                id="2",
                name="X-Credential",
                value=CREDENTIAL,
                encoding="none",
                secret=True,
            ),
            OutboundHeader(id="3", name="Region", value="eu-north"),
        ),
        user=user if user is not None else _user(),
    )


def _completion_adapter(
    endpoint: str | None,
    outbound: ProviderOutboundHeaders | None,
    *,
    with_tools: bool = False,
) -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = _resolver(endpoint)
    adapter.litellm_model = "hosted_vllm/spike-model"
    adapter.provider_type = "hosted_vllm"
    adapter.outbound_headers = outbound
    adapter.model = SimpleNamespace(
        name="spike-model",
        token_limit=8000,
        max_output_tokens=64,
        supports_tool_calling=True,
    )
    adapter._create_messages_from_context = Mock(  # type: ignore[method-assign]
        return_value=[{"role": "user", "content": "hello"}]
    )
    adapter._build_tools_from_context = Mock(return_value=[])  # type: ignore[method-assign]
    tools = (
        [
            {
                "type": "function",
                "function": {
                    "name": "server__tool",
                    "description": "t",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        if with_tools
        else []
    )
    adapter._merge_mcp_tools = Mock(return_value=tools)  # type: ignore[method-assign]
    return adapter


class _FakeMCPProxy:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def get_allowed_tool_names(self) -> set[str]:
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str) -> tuple[str, str, str]:
        return ("Server", "tool", "Tool title")

    def get_tool_purpose(self, prefixed_tool_name: str) -> str | None:
        return None

    def is_internal_tool(self, prefixed_tool_name: str) -> bool:
        return False

    def is_bundled_tool(self, prefixed_tool_name: str) -> bool:
        return False

    def model_result_text(self, text: str) -> str:
        return text

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return []

    async def refresh_tools(self, touched_tool_names: list[str]) -> bool:
        return False

    async def call_tools_parallel(self, proxy_calls: list[Any]) -> list[dict[str, Any]]:
        self.calls.append(proxy_calls)
        return [
            {"content": [{"type": "text", "text": "tool-ok"}], "is_error": False}
            for _ in proxy_calls
        ]


def _assert_headers_on_wire(request: Captured) -> None:
    for name, expected in EXPECTED_ON_WIRE.items():
        assert request.values(name) == [expected], name


# --- completion --------------------------------------------------------------


class TestCompletion:
    async def test_no_configuration_adds_no_kwarg_and_nothing_on_the_wire(
        self, loopback: LoopbackProvider
    ):
        adapter = _completion_adapter(loopback.base_url, None)
        assert "extra_headers" not in adapter._prepare_kwargs(model_kwargs={})

        await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

        [request] = loopback.captured
        assert request.names() - OTEL_PROPAGATION_HEADERS == ADAPTER_HEADERS

    async def test_non_streaming(self, loopback: LoopbackProvider):
        adapter = _completion_adapter(loopback.base_url, _headers())

        completion = await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}
        )

        assert completion.text == "plain answer"
        [request] = loopback.captured
        _assert_headers_on_wire(request)
        # The adapter's own headers are unaffected.
        assert request.names() - OTEL_PROPAGATION_HEADERS == ADAPTER_HEADERS | set(
            EXPECTED_ON_WIRE
        )
        assert request.values("content-type") == ["application/json"]

    async def test_streaming(self, loopback: LoopbackProvider):
        adapter = _completion_adapter(loopback.base_url, _headers())

        prepared = await adapter.prepare_streaming(
            context=SimpleNamespace(), model_kwargs={}
        )
        text = "".join(
            [
                chunk.text or ""
                async for chunk in adapter.iterate_stream(stream=prepared)
            ]
        )

        assert "streamed answer" in text
        [request] = loopback.captured
        assert json.loads(request.body)["stream"] is True
        _assert_headers_on_wire(request)

    async def test_tool_round_follow_up_non_streaming(self, loopback: LoopbackProvider):
        adapter = _completion_adapter(loopback.base_url, _headers(), with_tools=True)
        proxy = _FakeMCPProxy()

        completion = await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}, mcp_proxy=proxy
        )

        assert completion.text == "plain answer"
        assert len(proxy.calls) == 1
        first, follow_up = loopback.captured
        assert json.loads(follow_up.body)["messages"][-1]["role"] == "tool"
        _assert_headers_on_wire(first)
        _assert_headers_on_wire(follow_up)

    async def test_tool_round_follow_up_streaming(self, loopback: LoopbackProvider):
        adapter = _completion_adapter(loopback.base_url, _headers(), with_tools=True)
        proxy = _FakeMCPProxy()

        prepared = await adapter.prepare_streaming(
            context=SimpleNamespace(), model_kwargs={}, mcp_proxy=proxy
        )
        text = "".join(
            [
                chunk.text or ""
                async for chunk in adapter.iterate_stream(stream=prepared)
            ]
        )

        assert "streamed answer" in text
        assert len(proxy.calls) == 1
        first, follow_up = loopback.captured
        assert json.loads(follow_up.body)["messages"][-1]["role"] == "tool"
        _assert_headers_on_wire(first)
        _assert_headers_on_wire(follow_up)

    async def test_redirects_are_not_followed(
        self, loopback: LoopbackProvider, second_loopback: LoopbackProvider
    ):
        loopback.redirect_to = f"http://127.0.0.1:{second_loopback.server.server_port}"
        adapter = _completion_adapter(loopback.base_url, _headers())

        with pytest.raises(Exception):
            await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

        assert len(loopback.captured) == 1
        assert second_loopback.captured == []

    async def test_disallowed_destination_blocks_before_any_network_call(
        self, loopback: LoopbackProvider, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            get_settings(),
            "outbound_headers_allowed_destinations",
            ["https://gateway.internal/v1"],
        )
        adapter = _completion_adapter(loopback.base_url, _headers())

        with pytest.raises(ProviderRejectedRequestException) as exc_info:
            await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

        assert exc_info.value.code == "outbound_headers_blocked"
        assert exc_info.value.details == {
            "reason": "destination_not_allowed",
            "retryable": False,
        }
        assert loopback.captured == []

    async def test_allowed_destination_is_sent(
        self, loopback: LoopbackProvider, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            get_settings(), "outbound_headers_allowed_destinations", [loopback.base_url]
        )
        adapter = _completion_adapter(loopback.base_url, _headers())

        await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

        [request] = loopback.captured
        _assert_headers_on_wire(request)

    async def test_invalid_value_blocks_before_any_network_call(
        self, loopback: LoopbackProvider
    ):
        user = _user()
        user.scim_extensions[SCIM_ENTERPRISE_USER_URN]["department"] = (
            "a\r\nX-Injected: 1"
        )
        adapter = _completion_adapter(loopback.base_url, _headers(user))

        with pytest.raises(ProviderRejectedRequestException) as exc_info:
            await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

        assert exc_info.value.details is not None
        assert exc_info.value.details["reason"] == "control_character"
        assert loopback.captured == []


# --- embeddings and transcription ---------------------------------------------


def _embedding_adapter(
    endpoint: str, outbound: ProviderOutboundHeaders | None
) -> LiteLLMEmbeddingAdapter:
    model = SimpleNamespace(
        id=uuid4(),
        name="spike-embed",
        family=None,
        max_input=512,
        max_batch_size=None,
        dimensions=None,
        open_source=False,
        litellm_model_name="hosted_vllm/spike-embed",
    )
    return LiteLLMEmbeddingAdapter(
        model,  # type: ignore[arg-type]
        credential_resolver=_resolver(endpoint),
        litellm_model_name="hosted_vllm/spike-embed",
        outbound_headers=outbound,
    )


class TestEmbedding:
    async def test_embedding(self, loopback: LoopbackProvider):
        vector = await _embedding_adapter(
            loopback.base_url, _headers()
        ).get_embedding_for_query("q")

        assert vector == [0.1, 0.2]
        [request] = loopback.captured
        assert request.path.endswith("/embeddings")
        _assert_headers_on_wire(request)

    async def test_no_configuration(self, loopback: LoopbackProvider):
        await _embedding_adapter(loopback.base_url, None).get_embedding_for_query("q")

        [request] = loopback.captured
        assert not request.names() & set(EXPECTED_ON_WIRE)

    async def test_redirects_are_not_followed(
        self,
        loopback: LoopbackProvider,
        second_loopback: LoopbackProvider,
        monkeypatch: pytest.MonkeyPatch,
    ):
        loopback.redirect_to = f"http://127.0.0.1:{second_loopback.server.server_port}"
        adapter = _embedding_adapter(loopback.base_url, _headers())
        # The retry policy is shared by every adapter, so it must be restored.
        monkeypatch.setattr(
            adapter._get_embeddings.retry,  # type: ignore[attr-defined]
            "stop",
            lambda _: True,
        )

        with pytest.raises(Exception):
            await adapter.get_embedding_for_query("q")

        assert second_loopback.captured == []


def _transcription_adapter(
    endpoint: str, outbound: ProviderOutboundHeaders | None
) -> LiteLLMTranscriptionAdapter:
    return LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="spike-whisper", model_name="whisper"),  # type: ignore[arg-type]
        credential_resolver=_resolver(endpoint),
        provider_type="hosted_vllm",
        outbound_headers=outbound,
    )


def _audio(tmp_path: Path) -> Path:
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")
    return audio


class TestTranscription:
    """Register entry: transcription on hosted_vllm is an unsupported combination."""

    async def test_litellm_still_drops_extra_headers_on_this_route(
        self, loopback: LoopbackProvider, tmp_path: Path
    ):
        # If this starts failing, LiteLLM now forwards the headers here: lift
        # the block in LiteLLMTranscriptionAdapter and flip the test below.
        with _audio(tmp_path).open("rb") as file:
            await litellm.atranscription(
                model="hosted_vllm/whisper",
                file=file,
                api_base=loopback.base_url,
                extra_headers={"X-Probe": "1"},
            )

        [request] = loopback.captured
        assert request.values("x-probe") == []

    async def test_configured_headers_block_the_request_before_it_is_sent(
        self, loopback: LoopbackProvider, tmp_path: Path
    ):
        adapter = _transcription_adapter(loopback.base_url, _headers())

        with pytest.raises(ProviderRejectedRequestException) as exc_info:
            await adapter._transcribe_chunk(_audio(tmp_path))

        assert exc_info.value.details is not None
        assert exc_info.value.details["reason"] == "transcription_unsupported"
        assert loopback.captured == []

    async def test_without_configuration_transcription_is_unchanged(
        self, loopback: LoopbackProvider, tmp_path: Path
    ):
        adapter = _transcription_adapter(loopback.base_url, None)

        assert await adapter._transcribe_chunk(_audio(tmp_path)) == "hej"
        [request] = loopback.captured
        # This route goes through the OpenAI SDK (x-stainless-* headers), so its
        # baseline differs from completion's; only assert nothing was added.
        assert not request.names() & set(EXPECTED_ON_WIRE)


# --- logs --------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        # The formatted traceback too: an error log carries the exception text.
        traceback = (
            logging.Formatter().formatException(record.exc_info)
            if record.exc_info
            else ""
        )
        self.lines.append(f"{record.getMessage()} {record.__dict__} {traceback}")


@pytest.fixture
def eneo_logs() -> Iterator[_Capture]:
    """Eneo's loggers at DEBUG; LiteLLM's left at its production default."""
    capture = _Capture()
    loggers = [
        tenant_model_adapter.logger,
        litellm_embeddings.logger,
        litellm_transcription.logger,
        outbound_headers_runtime.logger,
        image_generation.logger,
    ]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(capture)
        logger.setLevel(logging.DEBUG)
    litellm_logger = logging.getLogger("LiteLLM")
    litellm_logger.addHandler(capture)
    yield capture
    litellm_logger.removeHandler(capture)
    for logger, level in zip(loggers, levels):
        logger.removeHandler(capture)
        logger.setLevel(level)


async def test_no_header_value_reaches_any_log(
    loopback: LoopbackProvider, eneo_logs: _Capture
):
    adapter = _completion_adapter(loopback.base_url, _headers())
    await adapter.get_response(context=SimpleNamespace(), model_kwargs={})
    await _embedding_adapter(loopback.base_url, _headers()).get_embedding_for_query("q")
    # A provider error goes through logger.exception and the public error mapping.
    loopback.fail_with = 500
    with pytest.raises(Exception):
        await _completion_adapter(loopback.base_url, _headers()).get_response(
            context=SimpleNamespace(), model_kwargs={}
        )
    loopback.fail_with = None
    blocked_user = _user()
    blocked_user.scim_extensions[SCIM_ENTERPRISE_USER_URN]["department"] = "LEAK\nvalue"
    with pytest.raises(ProviderRejectedRequestException):
        await _completion_adapter(
            loopback.base_url, _headers(blocked_user)
        ).get_response(context=SimpleNamespace(), model_kwargs={})

    text = "\n".join(eneo_logs.lines)
    assert "outbound_headers.request_blocked" in text  # the failure is observable
    assert "Unexpected error" in text  # the provider error was logged
    for leaked in (CREDENTIAL, "Milj%C3%B6", DEPARTMENT, "LEAK"):
        assert leaked not in text


async def test_warns_once_when_litellm_debug_logging_is_on(
    loopback: LoopbackProvider, eneo_logs: _Capture, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(outbound_headers_runtime, "_litellm_debug_warned", False)
    litellm_logger = logging.getLogger("LiteLLM")
    monkeypatch.setattr(litellm_logger, "level", logging.DEBUG)

    for _ in range(2):
        await _completion_adapter(loopback.base_url, _headers()).get_response(
            context=SimpleNamespace(), model_kwargs={}
        )

    warnings = [
        line
        for line in eneo_logs.lines
        if line.startswith("outbound_headers.litellm_debug_logging_enabled")
    ]
    assert len(warnings) == 1


def test_unresolved_token_is_logged_at_debug_without_a_value(eneo_logs: _Capture):
    user = _user()
    user.scim_extensions[SCIM_ENTERPRISE_USER_URN] = {}

    headers = _headers(user).resolve("https://gateway.internal/v1")

    assert "X-Org-Unit" not in headers  # omitted by the default policy
    [record] = [
        r for r in eneo_logs.records if r.getMessage() == "outbound_headers.unresolved"
    ]
    assert record.levelno == logging.DEBUG
    fields = record.__dict__
    assert fields["header"] == "X-Org-Unit"
    assert fields["tokens"] == ["user.department"]
    assert fields["policy"] == "omit"
    assert fields["user_id"] == str(user.id)
    assert CREDENTIAL not in "\n".join(eneo_logs.lines)


# --- runtime guards ------------------------------------------------------------


class TestAdapterHeaderCollision:
    def test_a_configured_header_never_overrides_one_already_set(self):
        # Case-insensitive, like HTTP: neither side may silently win.
        kwargs: dict[str, Any] = {
            "api_base": "https://gateway.internal/v1",
            "extra_headers": {"x-org-unit": "set-by-the-adapter"},
        }

        with pytest.raises(ProviderRejectedRequestException) as exc_info:
            apply_outbound_headers(kwargs, _headers())

        assert exc_info.value.details == {
            "reason": "adapter_header_collision",
            "retryable": False,
            "header": "X-Org-Unit",
        }
        assert kwargs["extra_headers"] == {"x-org-unit": "set-by-the-adapter"}

    def test_other_existing_headers_are_kept(self):
        kwargs: dict[str, Any] = {
            "api_base": "https://gateway.internal/v1",
            "extra_headers": {"X-Other": "1"},
        }

        apply_outbound_headers(kwargs, _headers())

        assert kwargs["extra_headers"]["X-Other"] == "1"
        assert kwargs["extra_headers"]["Region"] == "eu-north"


class TestUndecryptableHeaders:
    """A rotated or missing key blocks the request instead of a 500."""

    @pytest.mark.parametrize(
        "encryption",
        [
            EncryptionService(Fernet.generate_key().decode()),  # wrong key
            EncryptionService(None),  # no key at all
        ],
        ids=["wrong_key", "no_key"],
    )
    def test_blocks_without_logging_the_ciphertext(
        self, encryption: EncryptionService, eneo_logs: _Capture
    ):
        ciphertext = "enc:fernet:v1:not-a-token-for-this-key"

        with pytest.raises(ProviderRejectedRequestException) as exc_info:
            ProviderOutboundHeaders.load(
                provider_id=uuid4(),
                provider_type="hosted_vllm",
                stored=[
                    {"id": "1", "name": "X-Key", "value": ciphertext, "secret": True}
                ],
                encryption=encryption,
                user=_user(),
            )

        assert exc_info.value.details == {
            "reason": "decryption_failed",
            "retryable": False,
        }
        assert exc_info.value.__cause__ is None
        text = "\n".join(eneo_logs.lines)
        assert "decryption_failed" in text
        assert "not-a-token" not in text


# --- masking regression guards (B8) ---------------------------------------------


class TestMasking:
    PARAMS: dict[str, Any] = {
        "api_key": "sk-provider-key-1234",
        "extra_headers": {"X-Credential": CREDENTIAL, "X-Org-Unit": "Milj%C3%B6"},
        "temperature": 0.2,
    }

    def test_completion_log_params_mask_header_values(self):
        adapter = _completion_adapter("https://gateway.internal/v1", None)

        safe = adapter._mask_sensitive_params(dict(self.PARAMS))

        assert safe["extra_headers"] == {"X-Credential": "***", "X-Org-Unit": "***"}
        assert safe["api_key"] == "...1234"
        assert self.PARAMS["extra_headers"]["X-Credential"] == CREDENTIAL  # a copy

    def test_extra_headers_are_never_a_dropped_model_param(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # A "dropped" param leaves the logged kwargs; extra_headers must never
        # be judged against the model's supported params at all.
        monkeypatch.setattr(
            tenant_model_adapter,
            "_get_supported_openai_params",
            lambda _model: ["temperature"],
        )
        adapter = _completion_adapter("https://gateway.internal/v1", None)

        assert adapter._get_dropped_params(dict(self.PARAMS)) == set()

    def test_embedding_log_params_mask_header_values(self):
        adapter = _embedding_adapter("https://gateway.internal/v1", None)

        safe = adapter._mask_sensitive_params(dict(self.PARAMS))

        assert safe["extra_headers"] == {"X-Credential": "***", "X-Org-Unit": "***"}
        assert "api_key" not in safe
