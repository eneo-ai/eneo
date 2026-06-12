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

import base64
import io
import logging
import math
from typing import Any, Optional, cast

import litellm
from PIL import Image

logger = logging.getLogger(__name__)

# Fallback estimates when litellm cannot tokenize (unknown model AND
# unexpected tokenizer failure). ~4 chars/token for text, the OpenAI
# high-detail cost of a 2048×1024 image (uploads are stored downscaled to
# at most 2048px) for an image, and the message-wrapper scaffolding.
_FALLBACK_IMAGE_TOKENS = 1105
_FALLBACK_MESSAGE_OVERHEAD_TOKENS = 4

# litellm.token_counter prices every image with OpenAI's fixed tile formula,
# even for Anthropic models — so Claude image costs come out ~30% too low.
# Anthropic instead bills (width × height) / 750 after downscaling the long
# edge to 1568px, so we count Claude images ourselves from their dimensions.
_ANTHROPIC_IMAGE_MAX_EDGE = 1568
_ANTHROPIC_IMAGE_TOKEN_DIVISOR = 750


def _is_anthropic_model(model_name: str) -> bool:
    # TenantModelAdapter / preflight pass "<provider_type>/<name>", so the
    # provider is the part before the first slash; tolerate a bare "claude-*"
    # name for callers that don't prefix.
    head, _, _ = model_name.partition("/")
    if head.lower() == "anthropic":
        return True
    return "/" not in model_name and model_name.lower().startswith("claude")


def _anthropic_image_tokens(width: int, height: int) -> int:
    """Anthropic's documented image cost: (w × h) / 750, long edge capped 1568px."""
    long_edge = max(width, height)
    if long_edge > _ANTHROPIC_IMAGE_MAX_EDGE:
        scale = _ANTHROPIC_IMAGE_MAX_EDGE / long_edge
        width = round(width * scale)
        height = round(height * scale)
    return math.ceil(width * height / _ANTHROPIC_IMAGE_TOKEN_DIVISOR)


def _image_size_from_data_url(url: str) -> tuple[int, int] | None:
    """Read pixel dimensions from a base64 data URL without decoding the pixels."""
    try:
        _, _, encoded = url.partition(",")
        if not encoded:
            return None
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as img:
            return img.size
    except Exception:
        return None


def _split_anthropic_images(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Strip image_url blocks out for litellm and price them via Anthropic's formula.

    Returns the messages with images removed (so litellm counts only text +
    scaffolding) and the total Anthropic image-token cost. Per-image failures
    fall back to the flat estimate rather than dropping the image.
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
                _anthropic_image_tokens(*size) if size else _FALLBACK_IMAGE_TOKENS
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


def count_message_tokens(messages: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens for OpenAI-format chat messages.

    Includes per-message scaffolding overhead and image_url content blocks,
    so the input must have the same shape as the payload sent to the provider.
    """
    if not messages:
        return 0

    try:
        if _is_anthropic_model(model_name):
            # litellm misprices images for Anthropic; count them ourselves and
            # let litellm handle only the text + message scaffolding.
            stripped, image_tokens = _split_anthropic_images(messages)
            if image_tokens:
                text_tokens = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
                    model=model_name, messages=stripped
                )
                return text_tokens + image_tokens
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
