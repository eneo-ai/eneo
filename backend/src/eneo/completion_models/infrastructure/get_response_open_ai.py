from __future__ import annotations

from typing import Any

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.completion_models.infrastructure.provider_response_ids import (
    extract_provider_response_id,
)


async def get_response(
    *,
    client: Any,
    model_name: str,
    messages: list[Any],
    model_kwargs: dict[str, Any],
) -> Completion:
    response = await client.chat.completions.create(
        model=model_name,
        messages=messages,
        **model_kwargs,
    )
    completion = Completion()
    completion.provider_response_id = extract_provider_response_id(response)

    choices = getattr(response, "choices", [])
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            completion.text = content

    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", None)
    if isinstance(reasoning_tokens, int):
        completion.reasoning_token_count = reasoning_tokens

    return completion
