from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import BadRequestError

from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.main.exceptions import ProviderCapabilityRejectedException


class _FakeMCPProxy:
    def __init__(self):
        self.call_count = 0

    def get_allowed_tool_names(self):
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str):
        return ("Server", "tool")

    async def call_tools_parallel(self, proxy_calls):
        self.call_count += 1
        return [{"content": [{"type": "text", "text": "ok"}], "is_error": False}]


def _make_adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.model = SimpleNamespace(name="test-model")
    adapter.provider_type = "openai"

    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: {}
    adapter._create_messages_from_context = lambda context: []
    adapter._build_tools_from_context = lambda context: []
    adapter._merge_mcp_tools = lambda eneo_tools, mcp_proxy: [{"type": "function"}]
    adapter._get_dropped_params = lambda litellm_kwargs: set()
    adapter._get_effective_params = lambda litellm_kwargs, dropped: {}
    adapter._strip_thinking_content = lambda text: text
    return adapter


@pytest.mark.asyncio
async def test_get_response_executes_non_streaming_tool_round():
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
    first_response = SimpleNamespace(choices=[first_choice], id="resp-initial")

    follow_up_message = SimpleNamespace(content="final answer", tool_calls=None)
    follow_up_choice = SimpleNamespace(message=follow_up_message, finish_reason="stop")
    follow_up_response = SimpleNamespace(choices=[follow_up_choice], id="resp-final")

    mocked_acompletion = AsyncMock(side_effect=[first_response, follow_up_response])

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.text == "final answer"
    assert completion.provider_response_id == "resp-final"
    assert mocked_acompletion.await_count == 2
    assert mcp_proxy.call_count == 1


@pytest.mark.asyncio
async def test_late_capability_rejection_is_not_safe_to_repeat_without_capability():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    tool_call_message = SimpleNamespace(
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
    first_response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=tool_call_message, finish_reason="tool_calls")
        ],
        id="resp-initial",
    )
    late_rejection = BadRequestError(
        message="unsupported request parameter",
        model="test-model",
        llm_provider="openai",
        body={
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
            }
        },
    )
    mocked_acompletion = AsyncMock(side_effect=[first_response, late_rejection])

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            mocked_acompletion,
        ),
        pytest.raises(ProviderCapabilityRejectedException) as exc_info,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert exc_info.value.retry_without_capability_safe is False
    assert mocked_acompletion.await_count == 2
    assert mcp_proxy.call_count == 1
