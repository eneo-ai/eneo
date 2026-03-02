from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from intric.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)


class _FakeMCPProxy:
    def get_allowed_tool_names(self):
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str):
        return ("Server", "tool")

    async def call_tools_parallel(self, proxy_calls):
        return [{"content": [{"type": "text", "text": "ok"}], "is_error": False}]


def _make_adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.model = SimpleNamespace(name="test-model")
    adapter.provider_type = "openai"

    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: {}
    adapter._create_messages_from_context = lambda context: []
    adapter._build_tools_from_context = lambda context: []
    adapter._merge_mcp_tools = lambda intric_tools, mcp_proxy: [{"type": "function"}]
    adapter._get_dropped_params = lambda litellm_kwargs: set()
    adapter._get_effective_params = lambda litellm_kwargs, dropped: {}
    adapter._strip_thinking_content = lambda text: text
    return adapter


@pytest.mark.asyncio
async def test_get_response_populates_tool_calls_metadata_for_non_streaming():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()

    first_message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="server__tool",
                    arguments='{"q":"hello"}',
                ),
            )
        ],
    )
    first_choice = SimpleNamespace(message=first_message, finish_reason="tool_calls")
    first_response = SimpleNamespace(choices=[first_choice])

    follow_up_message = SimpleNamespace(content="final answer", tool_calls=None)
    follow_up_choice = SimpleNamespace(message=follow_up_message, finish_reason="stop")
    follow_up_response = SimpleNamespace(choices=[follow_up_choice])

    mocked_acompletion = AsyncMock(side_effect=[first_response, follow_up_response])

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
        mocked_acompletion,
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.text == "final answer"
    assert completion.tool_calls_metadata is not None
    assert len(completion.tool_calls_metadata) == 1
    assert completion.tool_calls_metadata[0].server_name == "Server"
    assert completion.tool_calls_metadata[0].tool_name == "tool"
    assert completion.tool_calls_metadata[0].result_status == "succeeded"
