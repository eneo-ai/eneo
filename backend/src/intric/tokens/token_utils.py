"""
Token counting utilities using litellm for accurate per-model tokenization.

Uses litellm.token_counter() which automatically selects the correct
tokenizer for each model (Anthropic, OpenAI, HuggingFace, etc.).

Counting should mirror the payload actually sent to the provider: prefer
count_message_tokens()/count_tool_tokens() over count_tokens() for anything
that is sent as chat messages, since the messages= form includes per-message
scaffolding overhead and image_url content (litellm applies the provider
image-token formulas).
"""

import logging
from typing import Any, Optional, cast

import litellm

logger = logging.getLogger(__name__)

# Fallback estimates when litellm cannot tokenize (unknown model AND
# unexpected tokenizer failure). ~4 chars/token for text, the OpenAI
# high-detail cost of a 2048×1024 image (uploads are stored downscaled to
# at most 2048px) for an image, and the message-wrapper scaffolding.
_FALLBACK_IMAGE_TOKENS = 1105
_FALLBACK_MESSAGE_OVERHEAD_TOKENS = 4


def count_tokens(text: str, model_name: str = "") -> int:
    """Count tokens for raw text using litellm's model-aware tokenizer."""
    if not text:
        return 0

    try:
        return litellm.token_counter(model=model_name, text=text)  # type: ignore[reportPrivateImportUsage]
    except Exception as e:
        logger.error(
            f"Token counting failed for model '{model_name}' "
            f"(text length {len(text)}), falling back to len//4: {e}"
        )
        return len(text) // 4


def _fallback_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += _FALLBACK_MESSAGE_OVERHEAD_TOKENS
        content = message.get("content")
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            for block in cast("list[dict[str, Any]]", content):
                if block.get("type") == "image_url":
                    total += _FALLBACK_IMAGE_TOKENS
                else:
                    total += len(str(block.get("text") or "")) // 4
    return total


def count_message_tokens(messages: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens for OpenAI-format chat messages.

    Includes per-message scaffolding overhead and image_url content blocks,
    so the input must have the same shape as the payload sent to the provider.
    """
    if not messages:
        return 0

    try:
        return litellm.token_counter(model=model_name, messages=messages)  # type: ignore[reportPrivateImportUsage]
    except Exception as e:
        logger.error(
            f"Message token counting failed for model '{model_name}' "
            f"({len(messages)} messages), using fallback estimate: {e}"
        )
        return _fallback_message_tokens(messages)


def count_tool_tokens(tools: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens consumed by tool/function definitions sent with a request."""
    if not tools:
        return 0

    try:
        with_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name,
            messages=[{"role": "user", "content": ""}],
            tools=tools,  # pyright: ignore[reportArgumentType]  # litellm accepts plain dicts
        )
        without_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name, messages=[{"role": "user", "content": ""}]
        )
        return max(with_tools - without_tools, 0)
    except Exception as e:
        import json

        serialized = json.dumps(tools)
        logger.error(
            f"Tool token counting failed for model '{model_name}' "
            f"({len(tools)} tools), falling back to len//4: {e}"
        )
        return len(serialized) // 4


def count_assistant_prompt_tokens(prompt: Optional[str], model_name: str) -> int:
    """Count tokens in an assistant's prompt."""
    if not prompt:
        return 0

    return count_tokens(prompt, model_name)
