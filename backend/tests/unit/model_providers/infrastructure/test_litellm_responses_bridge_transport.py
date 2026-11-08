"""Transport capture: a gpt-5.4+ tool call survives LiteLLM's Responses bridge.

LiteLLM serves an OpenAI/Azure chat call that has function tools with reasoning
on through ``/v1/responses`` and maps the reply back to chat choices. The
non-streaming adapter reads ``choices[0]``. On litellm 1.104.2 a reply where
the model writes text before the tool call came back as one choice per output
item, so ``choices[0]`` held only that text: the MCP tool never ran and the
preamble was returned as the answer (fixed upstream in BerriAI/litellm#46099).

Runs the real adapter and real LiteLLM against a loopback server, so a LiteLLM
bump that brings the split back fails here.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)

TOOL = {
    "type": "function",
    "function": {
        "name": "server__lookup",
        "description": "Look up a case",
        "parameters": {"type": "object", "properties": {"case": {"type": "string"}}},
    },
}


def _message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _responses_body(output: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        {
            "id": "resp_1",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "gpt-5.4",
            "output": output,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 5,
                "total_tokens": 10,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "text": {"format": {"type": "text"}},
        }
    ).encode()


# First turn: a preamble, then the tool call. Second turn: the answer.
REPLIES = [
    [
        _message("Let me check the case system."),
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "server__lookup",
            "arguments": '{"case": "123"}',
            "status": "completed",
        },
    ],
    [_message("Case 123 is approved.")],
]


@dataclass
class LoopbackResponsesProvider:
    server: ThreadingHTTPServer
    paths: list[str] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"


@pytest.fixture
def loopback() -> Iterator[LoopbackResponsesProvider]:
    provider: LoopbackResponsesProvider

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server API
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            provider.paths.append(self.path)
            turn = len(provider.paths) - 1
            if not self.path.endswith("/responses") or turn >= len(REPLIES):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            payload = _responses_body(REPLIES[turn])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    provider = LoopbackResponsesProvider(server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield provider
    server.shutdown()


class _FakeMCPProxy:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def get_allowed_tool_names(self) -> set[str]:
        return {"server__lookup"}

    def get_tool_info(self, prefixed_tool_name: str) -> tuple[str, str, str]:
        return ("Server", "lookup", "Lookup")

    def get_tool_purpose(self, prefixed_tool_name: str) -> str | None:
        return None

    def is_internal_tool(self, prefixed_tool_name: str) -> bool:
        return False

    def is_bundled_tool(self, prefixed_tool_name: str) -> bool:
        return False

    def model_result_text(self, text: str) -> str:
        return text

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return [TOOL]

    async def refresh_tools(self, touched_tool_names: list[str]) -> bool:
        return False

    async def call_tools_parallel(self, proxy_calls: list[Any]) -> list[dict[str, Any]]:
        self.calls.append(proxy_calls)
        return [
            {"content": [{"type": "text", "text": "approved"}], "is_error": False}
            for _ in proxy_calls
        ]


def _adapter(base_url: str) -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/gpt-5.4"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(
        name="gpt-5.4", supports_tool_calling=True, token_limit=128000
    )
    adapter._prepare_kwargs = Mock(  # type: ignore[method-assign]
        return_value={
            "api_base": base_url,
            "api_key": "sk-test",
            "reasoning_effort": "low",
        }
    )
    adapter._create_messages_from_context = Mock(  # type: ignore[method-assign]
        return_value=[{"role": "user", "content": "Is case 123 approved?"}]
    )
    adapter._build_tools_from_context = Mock(return_value=[])  # type: ignore[method-assign]
    adapter._merge_mcp_tools = Mock(return_value=[TOOL])  # type: ignore[method-assign]
    adapter._get_dropped_params = Mock(return_value=set())  # type: ignore[method-assign]
    adapter._get_effective_params = Mock(return_value={})  # type: ignore[method-assign]
    return adapter


async def test_non_streaming_runs_a_tool_called_after_a_preamble(
    loopback: LoopbackResponsesProvider,
) -> None:
    proxy = _FakeMCPProxy()

    completion = await _adapter(loopback.base_url).get_response(
        context=SimpleNamespace(), model_kwargs={}, mcp_proxy=proxy
    )

    assert [[name for name, _ in calls] for calls in proxy.calls] == [
        ["server__lookup"]
    ], f"the tool never ran; the answer was {completion.text!r}"
    assert loopback.paths == ["/v1/responses", "/v1/responses"]
    assert completion.text is not None
    assert completion.text.endswith("Case 123 is approved.")
