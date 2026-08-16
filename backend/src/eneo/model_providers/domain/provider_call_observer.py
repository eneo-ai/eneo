from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence, cast
from uuid import UUID

ProviderCallRequestedCapability = Literal[
    "image_input", "reasoning", "structured_output", "tool_calling"
]
ProviderCallResponseFormat = Literal["none", "json_object", "json_schema", "other"]
ProviderCallReason = Literal["initial", "capability_fallback", "tool_round"]
ProviderCallRejectionReason = Literal["response_format_rejected", "provider_rejected"]
ProviderCallUnknownReason = Literal["provider_error", "request_cancelled"]

_REQUEST_CONTROL_ALLOWLIST = frozenset(
    {
        "frequency_penalty",
        "max_completion_tokens",
        "max_tokens",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "stop",
        "temperature",
        "tool_choice",
        "tools",
        "top_k",
        "top_p",
        "verbosity",
    }
)


@dataclass(frozen=True, slots=True)
class CompletionCallRequestFacts:
    request_schema_version: Literal[2]
    provider_request_hash: str
    requested_model: str
    provider: str | None
    response_format: ProviderCallResponseFormat
    requested_capabilities: tuple[ProviderCallRequestedCapability, ...]
    reason: ProviderCallReason


@dataclass(frozen=True, slots=True)
class TranscriptionCallRequestFacts:
    """One transcription request and the audio it is about to send.

    The length is known before the request leaves, so it is recorded when the
    call starts. An attempt whose outcome is never learned therefore still says
    how much audio it may have been charged for.
    """

    request_schema_version: Literal[2]
    provider_request_hash: str
    requested_model: str
    provider: str | None
    audio_seconds: float


ProviderCallRequestFacts = CompletionCallRequestFacts | TranscriptionCallRequestFacts


@dataclass(frozen=True, slots=True)
class CompletionCallResultFacts:
    response_model: str | None
    provider_response_id: str | None
    num_tokens_input: int | None
    num_tokens_output: int | None


@dataclass(frozen=True, slots=True)
class TranscriptionCallResultFacts:
    response_model: str | None
    provider_response_id: str | None


ProviderCallResultFacts = CompletionCallResultFacts | TranscriptionCallResultFacts


class ProviderCallObserverError(RuntimeError):
    """Plain pre-I/O observer failure; typed subclasses carry other phases."""


class ProviderCallObserver(Protocol):
    async def started(self, request: ProviderCallRequestFacts) -> UUID: ...

    async def completed(
        self, call_id: UUID, result: ProviderCallResultFacts
    ) -> None: ...

    async def rejected(
        self, call_id: UUID, reason: ProviderCallRejectionReason
    ) -> None: ...

    async def outcome_unknown(
        self, call_id: UUID, reason: ProviderCallUnknownReason
    ) -> None: ...


def build_transcription_call_request_facts(
    *,
    requested_model: str,
    provider: str | None,
    language: str | None,
    audio_digest: str,
    audio_seconds: float,
) -> TranscriptionCallRequestFacts:
    """Identify one transcription request by what it sends, not where it came from.

    A retry of the same audio under the same routing is the same request, so it
    hashes the same. Two chunks of one recording differ because their bytes do.
    """
    if not requested_model or provider == "":
        raise ProviderCallObserverError(
            "Provider request evidence requires non-empty model identifiers."
        )
    if audio_seconds < 0:
        raise ProviderCallObserverError(
            "Provider request evidence requires a non-negative audio length."
        )
    serialized = json.dumps(
        {
            "request_schema_version": 2,
            "requested_model": requested_model,
            "provider": provider,
            "language": language,
            "audio_digest": audio_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return TranscriptionCallRequestFacts(
        request_schema_version=2,
        provider_request_hash=hashlib.sha256(serialized).hexdigest(),
        requested_model=requested_model,
        provider=provider,
        audio_seconds=audio_seconds,
    )


def build_provider_call_request_facts(
    *,
    requested_model: str,
    provider: str | None,
    messages: Sequence[Mapping[str, object]],
    request_kwargs: Mapping[str, object],
    reason: ProviderCallReason,
) -> CompletionCallRequestFacts:
    if not requested_model or provider == "":
        raise ProviderCallObserverError(
            "Provider request evidence requires non-empty model identifiers."
        )
    controls = {
        key: request_kwargs[key]
        for key in sorted(request_kwargs)
        if key in _REQUEST_CONTROL_ALLOWLIST
    }
    response_format = _response_format_kind(controls.get("response_format"))
    requested_capabilities = _requested_capabilities(
        messages=messages,
        controls=controls,
        response_format=response_format,
    )
    try:
        serialized = json.dumps(
            {
                "request_schema_version": 2,
                "requested_model": requested_model,
                "provider": provider,
                "messages": list(messages),
                "controls": controls,
                "stream": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProviderCallObserverError(
            "Provider request evidence could not be serialized safely."
        ) from exc
    return CompletionCallRequestFacts(
        request_schema_version=2,
        provider_request_hash=hashlib.sha256(serialized).hexdigest(),
        requested_model=requested_model,
        provider=provider,
        response_format=response_format,
        requested_capabilities=requested_capabilities,
        reason=reason,
    )


def _response_format_kind(value: object) -> ProviderCallResponseFormat:
    if value is None:
        return "none"
    if isinstance(value, Mapping):
        format_type = cast(Mapping[object, object], value).get("type")
        if format_type == "json_object":
            return "json_object"
        if format_type == "json_schema":
            return "json_schema"
    return "other"


def _requested_capabilities(
    *,
    messages: Sequence[Mapping[str, object]],
    controls: Mapping[str, object],
    response_format: ProviderCallResponseFormat,
) -> tuple[ProviderCallRequestedCapability, ...]:
    capabilities: set[ProviderCallRequestedCapability] = set()
    if _messages_contain_image_input(messages):
        capabilities.add("image_input")
    reasoning_effort = controls.get("reasoning_effort")
    if isinstance(reasoning_effort, str) and reasoning_effort not in ("", "none"):
        capabilities.add("reasoning")
    if response_format in ("json_object", "json_schema"):
        capabilities.add("structured_output")
    tools = controls.get("tools")
    if isinstance(tools, Sequence) and not isinstance(tools, (str, bytes, bytearray)):
        tool_sequence = cast(Sequence[object], tools)
        if tool_sequence:
            capabilities.add("tool_calling")
    return tuple(sorted(capabilities))


def _messages_contain_image_input(
    messages: Sequence[Mapping[str, object]],
) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in cast(list[object], content):
            if (
                isinstance(block, Mapping)
                and cast(Mapping[object, object], block).get("type") == "image_url"
            ):
                return True
    return False
