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
import logging
import math
from typing import Any, Optional, cast

import litellm
from PIL import Image

logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE_OVERHEAD_TOKENS = 4

# Anthropic bills one token per 28×28 pixel patch after resizing the image to
# fit both a long-edge limit and a per-image token budget (1568px/1568 tokens
# on most models; 2576px/4784 tokens on the high-resolution Opus 4.7+ family).
# OpenAI bills a base cost plus a per-512px-tile cost at detail "high", after
# fitting the image in 2048² and scaling the short side to 768px. Both
# formulas are documented; the drift alarm below catches them going stale.
_ANTHROPIC_PATCH_PX = 28
_ANTHROPIC_IMAGE_MAX_EDGE = 1568
_ANTHROPIC_IMAGE_MAX_TOKENS = 1568
_ANTHROPIC_HIGH_RES_MAX_EDGE = 2576
_ANTHROPIC_HIGH_RES_MAX_TOKENS = 4784
# Models with high-resolution image support (larger native limits). Future
# model families are unknowable here — they fall back to the standard limits
# and the drift alarm surfaces the mismatch.
_ANTHROPIC_HIGH_RES_MARKERS = ("opus-4-7", "opus-4-8", "fable", "mythos")
_OPENAI_IMAGE_FIT_EDGE = 2048
_OPENAI_IMAGE_SHORT_EDGE = 768
_OPENAI_IMAGE_TILE_PX = 512
_OPENAI_IMAGE_TILE_TOKENS = 170
_OPENAI_IMAGE_BASE_TOKENS = 85


def _is_anthropic_model(model_name: str) -> bool:
    # TenantModelAdapter / preflight pass "<provider_type>/<name>". Claude can
    # also be served through openai-compatible or bedrock-style providers, so
    # match the name segment too — "claude" in the model name means Anthropic
    # image pricing regardless of the route.
    head, _, tail = model_name.partition("/")
    if head.lower() == "anthropic":
        return True
    return "claude" in (tail or head).lower()


def _anthropic_patch_tokens(width: int, height: int) -> int:
    return math.ceil(width / _ANTHROPIC_PATCH_PX) * math.ceil(
        height / _ANTHROPIC_PATCH_PX
    )


def _anthropic_resized_size(
    width: int, height: int, max_edge: int, max_tokens: int
) -> tuple[int, int]:
    """The size Anthropic resizes an image to before pricing.

    Mirrors the reference implementation in Anthropic's vision docs: the
    largest aspect-preserving size whose padded edges stay within max_edge
    AND whose patch cost stays within max_tokens.
    """

    def fits(w: int, h: int) -> bool:
        return (
            math.ceil(w / _ANTHROPIC_PATCH_PX) * _ANTHROPIC_PATCH_PX <= max_edge
            and math.ceil(h / _ANTHROPIC_PATCH_PX) * _ANTHROPIC_PATCH_PX <= max_edge
            and _anthropic_patch_tokens(w, h) <= max_tokens
        )

    if fits(width, height):
        return (width, height)
    if height > width:
        resized_h, resized_w = _anthropic_resized_size(
            height, width, max_edge, max_tokens
        )
        return (resized_w, resized_h)

    aspect_ratio = width / height
    lo, hi = 1, width  # lo always fits; hi never fits
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect_ratio), 1)):
            lo = mid
        else:
            hi = mid
    return (lo, max(round(lo / aspect_ratio), 1))


def _anthropic_image_tokens(width: int, height: int, model_name: str = "") -> int:
    """Anthropic's documented image cost: one token per 28×28 pixel patch,
    after resizing to fit the model's edge and per-image token limits."""
    name = model_name.lower()
    if any(marker in name for marker in _ANTHROPIC_HIGH_RES_MARKERS):
        max_edge, max_tokens = (
            _ANTHROPIC_HIGH_RES_MAX_EDGE,
            _ANTHROPIC_HIGH_RES_MAX_TOKENS,
        )
    else:
        max_edge, max_tokens = _ANTHROPIC_IMAGE_MAX_EDGE, _ANTHROPIC_IMAGE_MAX_TOKENS
    return _anthropic_patch_tokens(
        *_anthropic_resized_size(width, height, max_edge, max_tokens)
    )


def _openai_image_tokens(width: int, height: int) -> int:
    """OpenAI's documented high-detail cost: fit in 2048², short side to 768px, then 85 + 170 per tile."""
    scale = min(1.0, _OPENAI_IMAGE_FIT_EDGE / max(width, height))
    scaled_w, scaled_h = width * scale, height * scale
    scale = min(1.0, _OPENAI_IMAGE_SHORT_EDGE / min(scaled_w, scaled_h))
    scaled_w, scaled_h = scaled_w * scale, scaled_h * scale
    tiles = math.ceil(scaled_w / _OPENAI_IMAGE_TILE_PX) * math.ceil(
        scaled_h / _OPENAI_IMAGE_TILE_PX
    )
    return _OPENAI_IMAGE_BASE_TOKENS + _OPENAI_IMAGE_TILE_TOKENS * tiles


# Fallback when an image's dimensions cannot be read: the cost of a 2048×1024
# upload (files are stored downscaled to at most 2048px on the long edge).
_FALLBACK_IMAGE_TOKENS = _openai_image_tokens(2048, 1024)


def count_image_tokens(width: int, height: int, model_name: str = "") -> int:
    """Tokens an image of the given pixel dimensions costs at detail "high"."""
    if _is_anthropic_model(model_name):
        return _anthropic_image_tokens(width, height, model_name)
    return _openai_image_tokens(width, height)


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


def count_message_tokens(messages: list[dict[str, Any]], model_name: str = "") -> int:
    """Count tokens for OpenAI-format chat messages.

    Includes per-message scaffolding overhead and image_url content blocks,
    so the input must have the same shape as the payload sent to the provider.
    """
    if not messages:
        return 0

    try:
        stripped, image_tokens = _split_image_blocks(messages, model_name)
        text_tokens = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name, messages=stripped
        )
        return text_tokens + image_tokens
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
