from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from intric.completion_models.infrastructure.get_response_claude import (
    get_response as get_claude_response,
)
from intric.completion_models.infrastructure.get_response_open_ai import (
    get_response as get_openai_response,
)
from intric.completion_models.infrastructure.provider_response_ids import (
    extract_provider_response_id,
)


def test_extract_provider_response_id_reads_string_ids_from_objects_and_mappings() -> None:
    assert extract_provider_response_id(SimpleNamespace(id="resp-object")) == "resp-object"
    assert extract_provider_response_id({"id": "resp-mapping"}) == "resp-mapping"
    assert extract_provider_response_id(SimpleNamespace(id="  ")) is None
    assert extract_provider_response_id({"id": None}) is None


@pytest.mark.asyncio
async def test_openai_get_response_populates_provider_response_id() -> None:
    response = SimpleNamespace(
        id="chatcmpl-123",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello world"),
            )
        ],
        usage=SimpleNamespace(
            completion_tokens_details=SimpleNamespace(reasoning_tokens=17)
        ),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )

    completion = await get_openai_response(
        client=client,
        model_name="gpt-test",
        messages=[],
        model_kwargs={},
    )

    assert completion.text == "hello world"
    assert completion.reasoning_token_count == 17
    assert completion.provider_response_id == "chatcmpl-123"


@pytest.mark.asyncio
async def test_claude_get_response_populates_provider_response_id() -> None:
    message = SimpleNamespace(
        id="msg_123",
        content=[SimpleNamespace(text="claude says hi")],
    )
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    completion = await get_claude_response(
        client=client,
        model_name="claude-test",
        prompt="system",
        messages=[],
        model_kwargs={},
        max_tokens=256,
    )

    assert completion.text == "claude says hi"
    assert completion.provider_response_id == "msg_123"
