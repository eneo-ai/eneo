"""
Token counting utilities using litellm for accurate per-model tokenization.

Uses litellm.token_counter() which automatically selects the correct
tokenizer for each model (Anthropic, OpenAI, HuggingFace, etc.).

Counting should mirror the payload actually sent to the provider: prefer
count_message_tokens()/count_tool_tokens() over count_tokens() for anything
that is sent as chat messages, since the messages= form includes per-message
scaffolding overhead. Images are priced from their pixel dimensions with the
provider's documented formula — litellm's own image handling misprices
Anthropic models (~30% too low) and requires the full base64 payload, which
is expensive to build just for counting.
"""

import base64
import io
import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional, cast

import litellm
from PIL import Image

from eneo.tokens.anthropic_image_pricing import (
    anthropic_image_tokens,
    is_anthropic_model,
)
from eneo.tokens.openai_image_pricing import openai_image_tokens

logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE_OVERHEAD_TOKENS = 4

# Fallback when an image's dimensions cannot be read: the cost of a 2048×1024
# upload (files are stored downscaled to at most 2048px on the long edge).
_FALLBACK_IMAGE_TOKENS = openai_image_tokens(2048, 1024)


class TokenCountSource(StrEnum):
    LITELLM = "litellm"
    FALLBACK_ESTIMATE = "fallback_estimate"


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    source: TokenCountSource


def count_image_tokens(width: int, height: int, model_name: str = "") -> int:
    """Tokens an image of the given pixel dimensions costs at detail "high".

    Provider pricing lives in the *_image_pricing modules — this is the only
    dispatch point into them.
    """
    if is_anthropic_model(model_name):
        return anthropic_image_tokens(width, height, model_name)
    return openai_image_tokens(width, height, model_name)


def _image_size_from_blob(blob: Optional[bytes]) -> tuple[int, int] | None:
    """Read pixel dimensions from image bytes without decoding the pixels."""
    if not blob:
        return None
    try:
        with Image.open(io.BytesIO(blob)) as img:
            return img.size
    except Exception:
        return None


def count_image_tokens_from_blob(blob: Optional[bytes], model_name: str = "") -> int:
    """Price a stored image straight from its blob — no base64 round-trip."""
    size = _image_size_from_blob(blob)
    if size is None:
        return _FALLBACK_IMAGE_TOKENS
    return count_image_tokens(*size, model_name=model_name)


def _image_size_from_data_url(url: str) -> tuple[int, int] | None:
    try:
        _, _, encoded = url.partition(",")
        if not encoded:
            return None
        return _image_size_from_blob(base64.b64decode(encoded))
    except Exception:
        return None


def _split_image_blocks(
    messages: list[dict[str, Any]], model_name: str
) -> tuple[list[dict[str, Any]], int]:
    """Strip image_url blocks out for litellm and price them from dimensions.

    Returns the messages with images removed (so litellm counts only text +
    scaffolding) and the total image-token cost. Per-image failures fall back
    to the flat estimate rather than dropping the image.
    """
    image_tokens = 0
    stripped: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            stripped.append(message)
            continue
        kept: list[Any] = []
        for block in cast("list[dict[str, Any]]", content):
            if block.get("type") != "image_url":
                kept.append(block)
                continue
            image_url = block.get("image_url")
            url = ""
            if isinstance(image_url, dict):
                candidate = cast("dict[str, Any]", image_url).get("url")
                if isinstance(candidate, str):
                    url = candidate
            size = _image_size_from_data_url(url)
            image_tokens += (
                count_image_tokens(*size, model_name=model_name)
                if size
                else _FALLBACK_IMAGE_TOKENS
            )
        stripped.append({**message, "content": kept if kept else ""})
    return stripped, image_tokens


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


def _fallback_tool_tokens(tools: list[dict[str, Any]]) -> int:
    return len(json.dumps(tools)) // 4


def _measure_messages_with_litellm(
    messages: list[dict[str, Any]],
    model_name: str,
) -> int:
    stripped, image_tokens = _split_image_blocks(messages, model_name)
    text_tokens = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
        model=model_name,
        messages=stripped,
    )
    return text_tokens + image_tokens


def measure_message_tokens(
    messages: list[dict[str, Any]], model_name: str = ""
) -> TokenCount:
    """Measure OpenAI-format chat messages and identify the counter used.

    Includes per-message scaffolding overhead and image_url content blocks,
    so the input must have the same shape as the payload sent to the provider.
    """
    if not messages:
        return TokenCount(tokens=0, source=TokenCountSource.LITELLM)

    try:
        return TokenCount(
            tokens=_measure_messages_with_litellm(messages, model_name),
            source=TokenCountSource.LITELLM,
        )
    except Exception as e:
        logger.error(
            f"Message token counting failed for model '{model_name}' "
            f"({len(messages)} messages), using fallback estimate: {e}"
        )
        return TokenCount(
            tokens=_fallback_message_tokens(messages),
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )


def measure_message_token_delta(
    base_messages: list[dict[str, Any]],
    composed_messages: list[dict[str, Any]],
    model_name: str = "",
) -> TokenCount:
    """Measure a message delta without mixing tokenization strategies."""
    if base_messages == composed_messages:
        return TokenCount(tokens=0, source=TokenCountSource.LITELLM)

    try:
        base_tokens = _measure_messages_with_litellm(base_messages, model_name)
        composed_tokens = _measure_messages_with_litellm(
            composed_messages,
            model_name,
        )
        source = TokenCountSource.LITELLM
    except Exception as error:
        logger.error(
            "Message token delta failed for model '%s'; recomputing both "
            "messages with the fallback estimate: %s",
            model_name,
            error,
        )
        base_tokens = _fallback_message_tokens(base_messages)
        composed_tokens = _fallback_message_tokens(composed_messages)
        source = TokenCountSource.FALLBACK_ESTIMATE

    return TokenCount(
        tokens=max(composed_tokens - base_tokens, 0),
        source=source,
    )


def count_message_tokens(messages: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens for OpenAI-format chat messages."""
    return measure_message_tokens(messages, model_name).tokens


def measure_tool_tokens(
    tools: list[dict[str, Any]], model_name: str = ""
) -> TokenCount:
    """Measure tool definitions and identify the counter used."""
    if not tools:
        return TokenCount(tokens=0, source=TokenCountSource.LITELLM)

    try:
        with_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name,
            messages=[{"role": "user", "content": ""}],
            tools=tools,  # pyright: ignore[reportArgumentType]  # litellm accepts plain dicts
        )
        without_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name, messages=[{"role": "user", "content": ""}]
        )
        return TokenCount(
            tokens=max(with_tools - without_tools, 0),
            source=TokenCountSource.LITELLM,
        )
    except Exception as e:
        logger.error(
            f"Tool token counting failed for model '{model_name}' "
            f"({len(tools)} tools), falling back to len//4: {e}"
        )
        return TokenCount(
            tokens=_fallback_tool_tokens(tools),
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )


def measure_provider_input_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model_name: str = "",
) -> TokenCount:
    """Measure the exact chat messages and tools proposed for one provider call."""

    stripped_messages, image_tokens = _split_image_blocks(messages, model_name)
    try:
        payload_tokens = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name,
            messages=stripped_messages,
            tools=tools,  # pyright: ignore[reportArgumentType]  # litellm accepts plain dicts
        )
        return TokenCount(
            tokens=payload_tokens + image_tokens,
            source=TokenCountSource.LITELLM,
        )
    except Exception as error:
        logger.error(
            "Provider input token counting failed for model '%s' "
            "(%d messages, %d tools), using one fallback estimate: %s",
            model_name,
            len(messages),
            len(tools),
            error,
        )
        return TokenCount(
            tokens=_fallback_message_tokens(messages) + _fallback_tool_tokens(tools),
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )


def count_tool_tokens(tools: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens consumed by tool/function definitions sent with a request."""
    return measure_tool_tokens(tools, model_name).tokens


def count_assistant_prompt_tokens(prompt: Optional[str], model_name: str) -> int:
    """Count tokens in an assistant's prompt."""
    if not prompt:
        return 0

    return count_tokens(prompt, model_name)


# Providers report the authoritative prompt token count in every response.
# Comparing it against our estimate turns silent formula staleness (provider
# pricing changes, tokenizer swaps, payload-shape drift) into a logged signal.
_DRIFT_WARN_RATIO = 0.2


def log_token_count_drift(
    model_name: str, predicted: Optional[int], actual: Optional[int]
) -> None:
    """Warn when the local estimate drifts from the provider-reported count."""
    if not predicted or not actual or predicted <= 0 or actual <= 0:
        return
    drift = abs(predicted - actual) / actual
    if drift > _DRIFT_WARN_RATIO:
        logger.warning(
            "Token count drift for model '%s': predicted %d vs provider-reported "
            "%d (%.0f%%) — counting formulas may be stale",
            model_name,
            predicted,
            actual,
            drift * 100,
        )
