"""Bounded reconstruction of a provider's streamed completion."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import unittest.mock
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, cast

import litellm

STREAM_RETAINED_BYTES_LIMIT: Final = 16 * 1024 * 1024
STREAM_EVENT_LIMIT: Final = 100_000
STREAM_CLOSE_SECONDS: Final = 1.0
# A progress limit, not JSON validation: extremely padded valid JSON trips it.
JSON_WHITESPACE_LIMIT: Final = 1024


class ProviderStreamError(Exception):
    """The provider stream could not be collected as a complete response."""


class ProviderStreamIncomplete(ProviderStreamError):
    """The provider never supplied a terminal finish reason."""


class ProviderStreamBoundExceeded(ProviderStreamError):
    def __init__(self, bound: str, limit: int) -> None:
        super().__init__(f"Provider stream exceeded {bound} ({limit})")
        self.bound = bound
        self.limit = limit


class ProviderJsonWhitespaceAbort(ProviderStreamError):
    def __init__(self, raw_text: str) -> None:
        super().__init__("Provider JSON whitespace progress limit reached")
        self.raw_text = raw_text
        self.finish_reason: None = None


@dataclass
class _JsonProgress:
    in_string: bool = False
    escaped: bool = False
    whitespace: int = 0

    def feed(self, text: str) -> bool:
        for character in text:
            if self.in_string:
                if self.escaped:
                    self.escaped = False
                elif character == "\\":
                    self.escaped = True
                elif character == '"':
                    self.in_string = False
            elif character in " \t\n\r":
                self.whitespace += 1
                if self.whitespace >= JSON_WHITESPACE_LIMIT:
                    return True
            else:
                self.whitespace = 0
                if character == '"':
                    self.in_string = True
        return False


def native_json_request(request: Mapping[str, Any]) -> bool:
    response_format = request.get("response_format")
    if not isinstance(response_format, Mapping):
        return False
    return cast(Mapping[str, object], response_format).get("type") in {
        "json_object",
        "json_schema",
    }


def is_provider_stream(response: object) -> bool:
    if isinstance(response, litellm.CustomStreamWrapper) or inspect.isasyncgen(
        response
    ):
        return True
    if isinstance(response, unittest.mock.NonCallableMock):
        return False
    return callable(getattr(type(response), "__anext__", None))


class ProviderStreamCollector:
    """Own a stream's cleanup outside the caller's request timers."""

    def __init__(self) -> None:
        self._response: Any = None

    async def __aenter__(self) -> ProviderStreamCollector:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._response is not None and is_provider_stream(self._response):
            await asyncio.shield(_close_stream(self._response))

    async def collect(
        self,
        response: Any,
        *,
        request: Mapping[str, Any],
        next_chunk: Callable[[AsyncIterator[Any]], Awaitable[Any]] | None = None,
    ) -> Any:
        self._response = response
        return await _collect_provider_stream(
            response, request=request, next_chunk=next_chunk
        )


async def _collect_provider_stream(
    response: Any,
    *,
    request: Mapping[str, Any],
    next_chunk: Callable[[AsyncIterator[Any]], Awaitable[Any]] | None = None,
) -> Any:
    """Collect provider chunks, retaining native finish and usage provenance.

    The caller owns request deadlines and retries. Cleanup has its own bound
    and cannot replace the failure that caused collection to stop.
    """
    if not is_provider_stream(response):
        return response
    chunks: list[Any] = []
    retained_bytes = 0
    progress: dict[int, _JsonProgress] = {}
    content: dict[int, list[str]] = {}
    detect_whitespace = native_json_request(request)
    stream: AsyncIterator[Any] = response.__aiter__()
    while True:
        try:
            chunk = await (
                next_chunk(stream) if next_chunk is not None else anext(stream)
            )
        except StopAsyncIteration:
            break
        if len(chunks) >= STREAM_EVENT_LIMIT:
            raise ProviderStreamBoundExceeded("event_count", STREAM_EVENT_LIMIT)
        encoded = chunk.model_dump_json().encode("utf-8")
        retained_bytes += len(encoded)
        if retained_bytes > STREAM_RETAINED_BYTES_LIMIT:
            raise ProviderStreamBoundExceeded(
                "retained_bytes", STREAM_RETAINED_BYTES_LIMIT
            )
        chunks.append(chunk)
        if detect_whitespace:
            for choice in getattr(chunk, "choices", None) or ():
                delta = getattr(choice, "delta", None)
                text = getattr(delta, "content", None)
                if not isinstance(text, str) or not text:
                    continue
                index = choice.index
                content.setdefault(index, []).append(text)
                if progress.setdefault(index, _JsonProgress()).feed(text):
                    raise ProviderJsonWhitespaceAbort("".join(content[index]))
    if not _provider_finished(response, chunks):
        raise ProviderStreamIncomplete(
            "The provider stream ended before a finish reason was received"
        )
    builder = cast(Callable[..., Any], getattr(litellm, "stream_chunk_builder"))
    built = builder(chunks, messages=request.get("messages"))
    if built is None:
        raise ProviderStreamIncomplete("The provider stream could not be rebuilt")
    built.usage = _native_usage(response, chunks)
    return built


def _provider_finished(response: object, chunks: list[Any]) -> bool:
    # The wrapper synthesizes a finish on EOF; only the received reason counts.
    if isinstance(response, litellm.CustomStreamWrapper):
        return getattr(response, "received_finish_reason", None) is not None
    return any(
        getattr(choice, "finish_reason", None)
        for chunk in chunks
        for choice in getattr(chunk, "choices", None) or ()
    )


@dataclass(frozen=True)
class _CompletionUsageDetails:
    reasoning_tokens: int | None


@dataclass(frozen=True)
class _ProviderUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    completion_tokens_details: _CompletionUsageDetails

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


def _native_usage(response: object, chunks: list[Any]) -> _ProviderUsage | None:
    # SDK-generated usage is not evidence; the wrapper retains provider chunks
    # separately from its generated final usage event.
    provider_chunks: Any = (
        getattr(response, "chunks", None)
        if isinstance(response, litellm.CustomStreamWrapper)
        else chunks
    )
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    reported = False
    for chunk in provider_chunks or ():
        usage = getattr(chunk, "usage", None)
        if usage is None:
            continue
        reported = True
        prompt_tokens = _largest(prompt_tokens, getattr(usage, "prompt_tokens", None))
        completion_tokens = _largest(
            completion_tokens, getattr(usage, "completion_tokens", None)
        )
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = _largest(
            reasoning_tokens, getattr(details, "reasoning_tokens", None)
        )
    return (
        _ProviderUsage(
            prompt_tokens,
            completion_tokens,
            _CompletionUsageDetails(reasoning_tokens),
        )
        if reported
        else None
    )


def _largest(current: int | None, reported: object) -> int | None:
    if not isinstance(reported, int) or isinstance(reported, bool):
        return current
    return reported if current is None else max(current, reported)


async def _close_stream(response: object) -> None:
    aclose = getattr(response, "aclose", None)
    if not callable(aclose):
        return
    close = cast(Callable[[], Awaitable[Any]], aclose)
    with contextlib.suppress(Exception):
        async with asyncio.timeout(STREAM_CLOSE_SECONDS):
            await close()
