from __future__ import annotations

from typing import Any

from intric.ai_models.completion_models.completion_model import Completion
from intric.completion_models.infrastructure.provider_response_ids import (
    extract_provider_response_id,
)


async def get_response(
    *,
    client: Any,
    model_name: str,
    prompt: str,
    messages: list[Any],
    model_kwargs: dict[str, Any],
    max_tokens: int,
) -> Completion:
    response = await client.messages.create(
        model=model_name,
        system=prompt,
        messages=messages,
        max_tokens=max_tokens,
        **model_kwargs,
    )
    completion = Completion()
    completion.provider_response_id = extract_provider_response_id(response)

    text_parts: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    completion.text = "".join(text_parts)

    return completion
