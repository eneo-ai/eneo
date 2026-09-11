"""One owner for every AI Builder provider completion.

A provider answer is streamed so that a slow model is observable while it
works: the deadline bounds *silence*, the wait for the next yielded chunk
(the first one included), not the whole answer, so a model that keeps
producing is not cut off by that deadline however long it takes, while a
dead connection is still detected. A separate, longer ceiling bounds the
whole call; it is deployment policy of its own, not the send-lock lease,
which the turn renews while it works. The chunks are rebuilt into the
complete completion LiteLLM would have returned, so everything after the
call (tool-call parsing, usage, incomplete-output guards) is unchanged.

A stream that ends without a terminal finish reason is not an answer: it is
reported as incomplete with an unknown provider outcome, never retried here.
Usage keeps its provenance: the rebuilt answer carries the usage the
provider itself sent, and none when it sent none, so the existing estimate
contract applies instead of an SDK count passing as the provider's.

A client that answers whole (a provider route without streaming, a test
double) is accepted as it is.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import math
import unittest.mock
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol, cast

import litellm

_STREAM_CLOSE_SECONDS = 5.0


class CompletionClient(Protocol):
    async def acompletion(self, **kwargs: Any) -> Any: ...


class ProviderSilenceExpired(TimeoutError):
    """No chunk arrived from the provider within the silence deadline."""


class ProviderCallCeilingExpired(TimeoutError):
    """The whole provider call exceeded its ceiling while still producing."""


class ProviderStreamIncomplete(Exception):
    """The stream ended without a terminal finish reason.

    Whatever arrived may parse, but the provider never said it was done, so
    the outcome is unknown.
    """


async def complete_with_silence_deadline(
    litellm_client: CompletionClient,
    *,
    silence_deadline_seconds: float,
    ceiling_seconds: float,
    request: Mapping[str, Any],
) -> Any:
    """The provider's complete answer, streamed under a silence deadline.

    ``silence_deadline_seconds`` is the longest wait for the next yielded
    chunk; ``ceiling_seconds`` bounds the whole call. Each expiry raises its
    own ``TimeoutError`` subclass, which the failure classifier records as a
    timeout with an unknown provider outcome. The stream is closed on every
    exit, within a bounded wait that never hides the original error.
    """

    if not (math.isfinite(silence_deadline_seconds) and silence_deadline_seconds > 0):
        raise ValueError("AI Builder silence deadline must be positive and finite")
    if not (
        math.isfinite(ceiling_seconds) and ceiling_seconds >= silence_deadline_seconds
    ):
        raise ValueError(
            "AI Builder call ceiling must be finite and not below the silence deadline"
        )
    outbound = {
        **request,
        "stream": True,
        # Usage arrives in the final chunk where the provider supports it;
        # drop_params removes the option elsewhere.
        "stream_options": {"include_usage": True},
        "timeout": silence_deadline_seconds,
    }
    chunks: list[Any] = []
    response: Any = None
    ceiling = asyncio.timeout(ceiling_seconds)
    try:
        async with ceiling:
            response = await _under_silence(
                litellm_client.acompletion(**outbound), silence_deadline_seconds
            )
            if not _is_stream(response):
                return response
            stream: AsyncIterator[Any] = response.__aiter__()
            while True:
                try:
                    chunk = await _under_silence(
                        stream.__anext__(), silence_deadline_seconds
                    )
                except StopAsyncIteration:
                    break
                chunks.append(chunk)
    except TimeoutError as error:
        if isinstance(error, ProviderSilenceExpired):
            raise
        if ceiling.expired():
            raise ProviderCallCeilingExpired(ceiling_seconds) from error
        raise
    finally:
        # Cleanup runs outside both request timers and is shielded from the
        # cancellation that ended them, within its own bound, so a stream is
        # released whichever way the call ended and the cause is preserved.
        if response is not None and _is_stream(response):
            await asyncio.shield(_close_stream(response))
    if not _provider_finished(response, chunks):
        raise ProviderStreamIncomplete(
            "The provider stream ended before a finish reason was received"
        )
    builder = cast(Callable[..., Any], getattr(litellm, "stream_chunk_builder"))
    built = builder(chunks, messages=request.get("messages"))
    if built is None:
        raise ProviderStreamIncomplete("The provider stream could not be rebuilt")
    # The SDK's rebuilt usage is its own count whenever the provider's usage
    # did not travel as a separate usage-only chunk (it fills one in when the
    # provider sent none, and recounts when usage rode on the final choice).
    # The provider's own figures, combined across its chunks, replace it; when
    # there are none, the existing estimate contract takes over.
    built.usage = _native_usage(response, chunks)
    return built


def _provider_finished(response: object, chunks: list[Any]) -> bool:
    """Whether the provider itself said the answer was complete.

    LiteLLM's stream wrapper records the finish reason the provider actually
    sent (`received_finish_reason`) and synthesizes one on a plain end of
    stream; only the recorded one is evidence. A bare async iterator (a
    provider adapter without the wrapper, a test double) is judged by the
    finish reasons its chunks carry.
    """

    if isinstance(response, litellm.CustomStreamWrapper):
        return getattr(response, "received_finish_reason", None) is not None
    return any(
        getattr(choice, "finish_reason", None)
        for chunk in chunks
        for choice in getattr(chunk, "choices", None) or ()
    )


def _native_usage(response: object, chunks: list[Any]) -> litellm.Usage | None:
    """The usage the provider itself sent, combined across its chunks, or None.

    LiteLLM's wrapper keeps the chunks the provider sent in ``chunks`` and
    builds its final usage chunk separately; only usage present in the
    provider's own chunks is evidence. A provider reports its counts as
    running totals, and may report the components in different events
    (Anthropic sends input tokens with the first event and output tokens with
    the last), so each component is the largest value any chunk reported for
    it. A bare async iterator is judged by the chunks it yielded.
    """

    provider_chunks: Any = (
        getattr(response, "chunks", None)
        if isinstance(response, litellm.CustomStreamWrapper)
        else chunks
    )
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    for chunk in provider_chunks or ():
        usage = getattr(chunk, "usage", None)
        if usage is None:
            continue
        prompt_tokens = _largest(prompt_tokens, getattr(usage, "prompt_tokens", None))
        completion_tokens = _largest(
            completion_tokens, getattr(usage, "completion_tokens", None)
        )
    if prompt_tokens is None and completion_tokens is None:
        return None
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    return litellm.Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _largest(current: int | None, reported: object) -> int | None:
    if not isinstance(reported, int) or isinstance(reported, bool):
        return current
    return reported if current is None else max(current, reported)


async def _under_silence(awaitable: Awaitable[Any], seconds: float) -> Any:
    """Await under the silence deadline; only that timer's own expiry is silence.

    A ``TimeoutError`` the awaited call raises itself (an SDK timeout) keeps
    its identity and is classified as the SDK's timeout, not as local silence.
    """

    silence = asyncio.timeout(seconds)
    try:
        async with silence:
            return await awaitable
    except TimeoutError as error:
        if silence.expired():
            raise ProviderSilenceExpired(seconds) from error
        raise


async def _close_stream(response: object) -> None:
    """Release the provider connection; bounded, and never masking the cause."""

    aclose = getattr(response, "aclose", None)
    if not callable(aclose):
        return
    close = cast(Callable[[], Awaitable[Any]], aclose)
    with contextlib.suppress(Exception):
        async with asyncio.timeout(_STREAM_CLOSE_SECONDS):
            await close()


def _is_stream(response: object) -> bool:
    """A LiteLLM stream or any async iterator; a whole answer is neither.

    Mock doubles are excluded explicitly: a mock answers every attribute,
    including ``__anext__``, and would otherwise pass as an empty stream.
    """

    if isinstance(response, litellm.CustomStreamWrapper) or inspect.isasyncgen(
        response
    ):
        return True
    if isinstance(response, unittest.mock.NonCallableMock):
        return False
    return callable(getattr(type(response), "__anext__", None))
