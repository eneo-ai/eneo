"""The rerank transport call delegates to LiteLLM with the caller's kwargs."""

from unittest.mock import AsyncMock

import litellm

from eneo.model_providers.infrastructure import litellm_transport


async def test_arerank_delegates_to_litellm(monkeypatch):
    call = AsyncMock(return_value="response")
    monkeypatch.setattr(litellm, "arerank", call)

    result = await litellm_transport.arerank(
        model="cohere/rerank-v3.5", query="q", documents=["a", "b"], top_n=1
    )

    assert result == "response"
    call.assert_awaited_once_with(
        model="cohere/rerank-v3.5", query="q", documents=["a", "b"], top_n=1
    )
