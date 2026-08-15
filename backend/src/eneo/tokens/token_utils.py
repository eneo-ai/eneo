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

Two questions are answered here and they must not be confused:

* a **reserve** — how much room a budget must keep free — may exceed what the
  provider charges but must never fall short, because falling short admits a
  request the provider then refuses. `measure_tool_tokens` and
  `measure_provider_input_reserve` answer it, and their fallbacks bound the
  payload rather than estimate it.
* a **report** — what the provider will say it charged — stands in for a
  missing `prompt_tokens` and is what drift logging compares against, so it
  aims at that number rather than above it. `measure_provider_input_tokens`
  answers it.
"""

import base64
import io
import json
import logging
from collections.abc import Callable
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


def _fallback_message_tokens(
    messages: list[dict[str, Any]], model_name: str = ""
) -> int:
    """Estimate messages when tokenizing failed, for reporting only.

    A character heuristic is roughly right for prose and roughly wrong for
    everything else, so a reserve must not use it — see
    `_fallback_message_reserve_tokens`.
    """
    del model_name
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
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            total += (
                len(json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":")))
                // 4
            )
        tool_call_id = message.get("tool_call_id")
        if isinstance(tool_call_id, str):
            total += len(tool_call_id) // 4
    return total


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _utf8_upper_bound_tokens(text: str) -> int:
    """Tokens `text` cannot exceed.

    Every token of the byte-pair encodings behind the supported providers
    covers at least one UTF-8 byte, so the byte length bounds the count for any
    script. It needs no tokenizer, which is what makes it usable when
    tokenizing has failed, and it stays an upper bound where a character
    heuristic does not: `len // 4` under-counts CJK, emoji, and
    punctuation-dense identifiers several-fold.
    """
    return len(text.encode())


# A provider prices a tool from its expanded schema, so a `$defs` entry reached
# through `$ref` costs its whole definition at every use site. Only the material
# a reference introduces is bounded: the catalog a caller passed in already has
# its own limits, while expansion is what multiplies it, and a definition can be
# large as well as often-referenced (`mcp_server.py` permits a 1 MiB
# definition). Charging characters rather than nodes is what makes the ceiling a
# memory bound instead of a shape bound.
_MAX_TOOL_SCHEMA_EXPANSION_CHARS = 4 * 1024 * 1024
_DEFINITIONS_POINTER_PREFIX = "#/$defs/"

# What an unbounded schema reserves. This is a refusal, not a measurement: no
# context window admits it, so every budget that subtracts it declines the
# request whether or not the caller inspects `TokenCount.source`. Deriving the
# number from the partial expansion instead would let many small references
# exhaust the ceiling while still reporting a cost a caller would accept.
_UNBOUNDED_TOOL_SCHEMA_TOKENS = 1 << 40


@dataclass(frozen=True)
class _ToolReservePayload:
    """The serialized tool schemas a reserve is measured from.

    `bounded` is false when a reference stopped being written out part way, and
    then `text` is missing cost that must never be priced as if it were whole.
    """

    text: str
    bounded: bool


class _ExpansionBudget:
    """Bounds the characters reference expansion may introduce."""

    def __init__(self, limit: int) -> None:
        self._remaining = limit
        self.exhausted = False

    def spend(self, characters: int) -> bool:
        if self._remaining < characters:
            self.exhausted = True
            return False
        self._remaining -= characters
        return True


def _resolve_definition(pointer: str, roots: tuple[object, ...]) -> object | None:
    """Resolve a `#/$defs/<name>` pointer against the documents it may name.

    Providers read a tool's pointers against its parameter object, which is the
    document they validate arguments with. A schema that hoists `$defs` above
    that object still has to be priced, so the tool itself is tried next rather
    than leaving the reference unexpanded and under-reserved.
    """
    name = pointer[len(_DEFINITIONS_POINTER_PREFIX) :].replace("~1", "/")
    name = name.replace("~0", "~")
    for root in roots:
        if not isinstance(root, dict):
            continue
        definitions = cast("dict[str, Any]", root).get("$defs")
        if isinstance(definitions, dict):
            target = cast("dict[str, Any]", definitions).get(name)
            if target is not None:
                return target
    return None


def _expand_schema_references(
    node: object,
    *,
    roots: tuple[object, ...],
    active: frozenset[str],
    budget: _ExpansionBudget,
    inside_reference: bool,
) -> object:
    """Write every `$defs` reference out where it is used, keeping `$defs` too.

    A reference already being expanded on this path is left exactly as written,
    so a recursive schema terminates. `$defs` is kept rather than dropped for
    the same reason: the provider is sent those bytes too, and a definition an
    unresolved reference still points at must keep costing something.

    The result is an accounting representation, not a schema. A resolved target
    is stored under the reference's own key so that a `description` on the
    reference and a `description` on its target both survive; merging them into
    one object silently dropped whichever lost the collision.
    """
    if inside_reference and isinstance(node, str) and not budget.spend(len(node)):
        return node
    if isinstance(node, list):
        return [
            _expand_schema_references(
                item,
                roots=roots,
                active=active,
                budget=budget,
                inside_reference=inside_reference,
            )
            for item in cast("list[Any]", node)
        ]
    if not isinstance(node, dict):
        return node
    typed = cast("dict[str, Any]", node)
    expanded: dict[str, Any] = {}
    for key, value in typed.items():
        if (
            key == "$ref"
            and isinstance(value, str)
            and value.startswith(_DEFINITIONS_POINTER_PREFIX)
            and value not in active
        ):
            target = _resolve_definition(value, roots)
            if target is not None and budget.spend(len(_serialized(target))):
                expanded[key] = _expand_schema_references(
                    target,
                    roots=roots,
                    active=active | {value},
                    budget=budget,
                    inside_reference=True,
                )
                continue
        expanded[key] = _expand_schema_references(
            value,
            roots=roots,
            active=active,
            budget=budget,
            inside_reference=inside_reference,
        )
    return expanded


def _tool_reserve_payload(tools: list[dict[str, Any]]) -> _ToolReservePayload:
    budget = _ExpansionBudget(_MAX_TOOL_SCHEMA_EXPANSION_CHARS)
    expanded: list[object] = []
    for tool in tools:
        function = tool.get("function")
        parameters = (
            cast("dict[str, Any]", function).get("parameters")
            if isinstance(function, dict)
            else None
        )
        expanded.append(
            _expand_schema_references(
                tool,
                roots=(parameters, tool),
                active=frozenset(),
                budget=budget,
                inside_reference=False,
            )
        )
    return _ToolReservePayload(
        text=_serialized(expanded),
        bounded=not budget.exhausted,
    )


def _fallback_tool_reserve_tokens(tools: list[dict[str, Any]]) -> int:
    """Upper-bound tool schemas when tokenizing failed, for a reserve."""
    payload = _tool_reserve_payload(tools)
    if not payload.bounded:
        return _UNBOUNDED_TOOL_SCHEMA_TOKENS
    return _utf8_upper_bound_tokens(payload.text)


def _fallback_tool_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate tool schemas when tokenizing failed, for reporting only.

    Deliberately measures the tools as the caller wrote them. Pricing the
    expanded form here would inflate the usage a provider is reported to have
    charged whenever it omits its own count.
    """
    return len(_serialized(tools)) // 4


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


def _fallback_message_reserve_tokens(
    messages: list[dict[str, Any]], model_name: str = ""
) -> int:
    """Upper-bound messages when tokenizing failed, for a reserve.

    Images keep their provider formula, which prices them from pixel
    dimensions rather than text; everything else is bounded by its bytes.
    """
    stripped, image_tokens = _split_image_blocks(messages, model_name)
    serialized = json.dumps(stripped, ensure_ascii=False, separators=(",", ":"))
    return _utf8_upper_bound_tokens(serialized) + image_tokens


def _measure_messages(
    messages: list[dict[str, Any]],
    model_name: str,
    *,
    fallback: Callable[[list[dict[str, Any]], str], int],
) -> TokenCount:
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
            tokens=fallback(messages, model_name),
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )


def measure_message_tokens(
    messages: list[dict[str, Any]], model_name: str = ""
) -> TokenCount:
    """Measure OpenAI-format chat messages and identify the counter used.

    Includes per-message scaffolding overhead and image_url content blocks,
    so the input must have the same shape as the payload sent to the provider.
    """
    return _measure_messages(messages, model_name, fallback=_fallback_message_tokens)


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
        base_tokens = _fallback_message_tokens(base_messages, model_name)
        composed_tokens = _fallback_message_tokens(composed_messages, model_name)
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
    """Reserve context for tool definitions, and identify the counter used.

    This is the reserve contract: it answers "how much room must I keep free",
    so it may exceed what the provider charges but must never fall short.
    Neither available reading is safe alone, and each covers the other's blind
    spot, so the reserve is the larger of the two:

    * litellm's function estimator adds per-tool and per-property scaffolding,
      which is the higher reading for a flat tool carrying a long description;
    * it walks neither nested properties nor `$defs`, so a deep schema is
      measured instead from its expanded serialization. Against the Flow
      Builder's create schema the estimator charged 279 tokens where the
      provider billed roughly 2,823, and a container enum behind one `$ref`
      cost 4,420 tokens it did not see at all.

    Taking the larger also means no caller reserves less than it did before.
    """
    if not tools:
        return TokenCount(tokens=0, source=TokenCountSource.LITELLM)

    payload = _tool_reserve_payload(tools)
    if not payload.bounded:
        logger.error(
            "Tool schema expansion for model '%s' (%d tools) exceeded its node "
            "bound; reserving an unbounded cost so the request is declined",
            model_name,
            len(tools),
        )
        return TokenCount(
            tokens=_UNBOUNDED_TOOL_SCHEMA_TOKENS,
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )
    try:
        with_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name,
            messages=[{"role": "user", "content": ""}],
            tools=tools,  # pyright: ignore[reportArgumentType]  # litellm accepts plain dicts
        )
        without_tools = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name, messages=[{"role": "user", "content": ""}]
        )
        expanded = litellm.token_counter(  # type: ignore[reportPrivateImportUsage]
            model=model_name, text=payload.text
        )
        return TokenCount(
            tokens=max(with_tools - without_tools, expanded, 0),
            source=TokenCountSource.LITELLM,
        )
    except Exception as e:
        logger.error(
            f"Tool token counting failed for model '{model_name}' "
            f"({len(tools)} tools), falling back to the byte bound: {e}"
        )
        return TokenCount(
            tokens=_fallback_tool_reserve_tokens(tools),
            source=TokenCountSource.FALLBACK_ESTIMATE,
        )


def measure_provider_input_reserve(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model_name: str = "",
) -> TokenCount:
    """Reserve context for one provider call's messages and tools.

    The admission counterpart of `measure_provider_input_tokens`: a gate that
    under-reserves admits a request the provider then refuses, so both halves
    use the reserve contract and neither falls back to a character heuristic.
    Use this wherever the number decides whether a request may proceed, and the
    reporting function wherever it stands in for what the provider billed.
    """

    message_reserve = _measure_messages(
        messages, model_name, fallback=_fallback_message_reserve_tokens
    )
    tool_reserve = measure_tool_tokens(tools, model_name)
    estimated = TokenCountSource.FALLBACK_ESTIMATE in (
        message_reserve.source,
        tool_reserve.source,
    )
    return TokenCount(
        tokens=message_reserve.tokens + tool_reserve.tokens,
        source=(
            TokenCountSource.FALLBACK_ESTIMATE
            if estimated
            else TokenCountSource.LITELLM
        ),
    )


def measure_provider_input_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model_name: str = "",
) -> TokenCount:
    """Predict what the provider will report for one call's messages and tools.

    This is the reporting contract: it stands in for `prompt_tokens` when a
    response omits usage, and it is what drift logging compares against, so it
    aims at the provider's own number rather than above it. Deciding whether a
    request fits is `measure_provider_input_reserve`.
    """

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
