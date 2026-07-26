from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence, cast
from uuid import UUID

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
class ProviderCallRequestFacts:
    request_schema_version: Literal[1]
    provider_request_hash: str
    requested_model: str
    provider: str | None
    response_format: ProviderCallResponseFormat
    reason: ProviderCallReason


@dataclass(frozen=True, slots=True)
class ProviderCallResultFacts:
    response_model: str | None
    provider_response_id: str | None
    num_tokens_input: int | None
    num_tokens_output: int | None


class ProviderCallObserverError(RuntimeError):
    """Base error for durable observer failures that must not be remapped."""


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


def build_provider_call_request_facts(
    *,
    requested_model: str,
    provider: str | None,
    messages: Sequence[Mapping[str, object]],
    request_kwargs: Mapping[str, object],
    reason: ProviderCallReason,
) -> ProviderCallRequestFacts:
    controls = {
        key: request_kwargs[key]
        for key in sorted(request_kwargs)
        if key in _REQUEST_CONTROL_ALLOWLIST
    }
    serialized = json.dumps(
        {
            "request_schema_version": 1,
            "requested_model": requested_model,
            "messages": list(messages),
            "controls": controls,
            "stream": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ProviderCallRequestFacts(
        request_schema_version=1,
        provider_request_hash=hashlib.sha256(serialized).hexdigest(),
        requested_model=requested_model,
        provider=provider,
        response_format=_response_format_kind(controls.get("response_format")),
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
