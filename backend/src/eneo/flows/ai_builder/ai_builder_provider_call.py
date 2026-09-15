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

A provider that refuses the request while it is being established, because
of one optional sampling control (temperature, top_p, reasoning_effort, ...),
has done no work; when the caller admits another request, the call is sent
once more without that control, which is the provider's default, under the
same ceiling. A refusal after a stream was acquired is never retried here: the
provider may have generated. The persisted capability snapshot said the
control was accepted, so the refusal is logged as evidence that the snapshot
is wider than the route. The refusal's envelope is read from wherever the
SDK left it: LiteLLM's Responses-API bridge (which carries Azure and OpenAI
gpt-5.4+ requests with function tools) re-raises a provider 400 with only
the envelope text in the exception message, no body and a placeholder
response, so the message is the last source tried.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import json
import math
import unittest.mock
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, cast

import httpx
import litellm
from litellm.exceptions import BadRequestError

from eneo.main.logging import get_logger

logger = get_logger(__name__)

_STREAM_CLOSE_SECONDS = 5.0
_MAX_PROVIDER_ERROR_BODY_BYTES = 65_536
# Provider error codes that state one named request field was refused.
_UNSUPPORTED_PARAMETER_CODES = frozenset({"unsupported_parameter", "unsupported_value"})

# Whether the caller admits one more request without the refused control;
# the caller charges it to its own call budget and telemetry.
RetryAdmission = Callable[[str, Exception], bool]


ProviderRejectionSource = Literal[
    "unavailable",
    "body",
    "body.error",
    "response",
    "response.error",
    "message",
    "message.error",
    "exception.param",
]
ProviderExtractionStatus = Literal["found", "absent", "malformed", "suppressed"]
ProviderCorrelationSource = Literal[
    "request_id", "response.headers", "litellm_response_headers"
]


@dataclass(frozen=True, slots=True)
class ProviderRejection:
    code: str | None = None
    parameter: str | None = None
    source: ProviderRejectionSource = "unavailable"
    status: ProviderExtractionStatus = "absent"
    correlation_id: str | None = None
    correlation_source: ProviderCorrelationSource | None = None
    parameter_source: ProviderRejectionSource | None = None


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
    retry_without_refused_control: RetryAdmission | None = None,
    observe_sdk_input: Callable[[Mapping[str, Any]], None] | None = None,
) -> Any:
    """The provider's complete answer, streamed under a silence deadline.

    ``silence_deadline_seconds`` is the longest wait for the next yielded
    chunk; ``ceiling_seconds`` bounds the whole call, a retried request
    included. Each expiry raises its own ``TimeoutError`` subclass, which the
    failure classifier records as a timeout with an unknown provider outcome.
    The stream is closed on every exit, within a bounded wait that never
    hides the original error. ``retry_without_refused_control`` is asked, with
    the refused control's name and the provider's error, whether one more
    request without that control may be sent; without it every refusal is
    raised.
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
            try:
                if observe_sdk_input is not None:
                    observe_sdk_input(outbound)
                response = await _under_silence(
                    litellm_client.acompletion(**outbound), silence_deadline_seconds
                )
            except BadRequestError as error:
                rejection = provider_error_fields(error)
                parameter = rejected_sampling_parameter(rejection)
                if (
                    parameter is None
                    or parameter not in outbound
                    or retry_without_refused_control is None
                    or not retry_without_refused_control(parameter, error)
                ):
                    raise
                logger.warning(
                    "ai_builder_provider_sampling_parameter_rejected",
                    extra={
                        "parameter": parameter,
                        "model": outbound.get("model"),
                        "provider_error_code": rejection.code,
                        "provider_extraction_source": rejection.source,
                        "provider_extraction_status": rejection.status,
                        "provider_correlation_id": rejection.correlation_id,
                        "provider_correlation_source": rejection.correlation_source,
                    },
                )
                outbound = {
                    key: value for key, value in outbound.items() if key != parameter
                }
                if observe_sdk_input is not None:
                    observe_sdk_input(outbound)
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
    built = builder(chunks, messages=outbound.get("messages"))
    if built is None:
        raise ProviderStreamIncomplete("The provider stream could not be rebuilt")
    # The SDK's rebuilt usage is its own count whenever the provider's usage
    # did not travel as a separate usage-only chunk (it fills one in when the
    # provider sent none, and recounts when usage rode on the final choice).
    # The provider's own figures, combined across its chunks, replace it; when
    # there are none, the existing estimate contract takes over.
    built.usage = _native_usage(response, chunks)
    return built


def rejected_sampling_parameter(rejection: ProviderRejection) -> str | None:
    """The optional sampling control a 400 refused by name, or None."""

    if rejection.code not in _UNSUPPORTED_PARAMETER_CODES:
        return None
    parameter = rejection.parameter
    if parameter in _sampling_controls():
        return parameter
    return None


def _sampling_controls() -> frozenset[str]:
    """The optional sampling controls the capability snapshot owns.

    Imported when asked, not at module load: the capability module's package
    imports the Builder's error contract, which imports this owner.
    """

    from eneo.completion_models.domain.model_kwargs_capabilities import (
        SupportedModelKwargs,
    )

    return frozenset(SupportedModelKwargs.model_fields)


def provider_error_fields(error: BaseException) -> ProviderRejection:
    """Recover structured rejection facts without reading a response stream.

    Try the nested and flat SDK body, then the buffered HTTP body, then the
    one envelope literal the SDK embedded in the exception message. An
    envelope wins only when it supplies a safe fact; otherwise preserve the
    strongest extraction failure. Publication policy belongs to the error
    contract.
    """

    from eneo.flows.ai_builder.ai_builder_error_contract import (
        safe_provider_correlation_id,
        safe_provider_parameter,
    )

    body = getattr(error, "body", None)
    result = _rejection_envelope_fields(body, "body", "body.error")
    response = getattr(error, "response", None)
    if (
        result.code is None
        and result.parameter is None
        and isinstance(response, httpx.Response)
        and response.is_stream_consumed
    ):
        try:
            if len(response.content) > _MAX_PROVIDER_ERROR_BODY_BYTES:
                fallback = ProviderRejection(source="response", status="suppressed")
            elif not response.content:
                fallback = ProviderRejection(source="response")
            else:
                fallback = _rejection_envelope_fields(
                    response.json(), "response", "response.error"
                )
        except (ValueError, RecursionError, httpx.ResponseNotRead):
            fallback = ProviderRejection(source="response", status="malformed")
        result = _select_rejection(result, fallback)
    if result.code is None and result.parameter is None:
        result = _select_rejection(result, _message_envelope_fields(error))

    raw_parameter = getattr(error, "param", None)
    if result.parameter is None and raw_parameter is not None:
        parameter = safe_provider_parameter(raw_parameter)
        result = replace(
            result,
            parameter=parameter,
            parameter_source="exception.param" if parameter is not None else None,
            source="exception.param"
            if result.source == "unavailable"
            else result.source,
            status=(
                "suppressed"
                if parameter is None or result.status == "suppressed"
                else "found"
            ),
        )
    correlation_id = safe_provider_correlation_id(getattr(error, "request_id", None))
    correlation_source: ProviderCorrelationSource | None = (
        "request_id" if correlation_id is not None else None
    )
    header_sources: tuple[tuple[object, ProviderCorrelationSource], ...] = (
        (
            response.headers if isinstance(response, httpx.Response) else None,
            "response.headers",
        ),
        (getattr(error, "litellm_response_headers", None), "litellm_response_headers"),
    )
    for headers, source in header_sources:
        if correlation_id is not None:
            break
        if not isinstance(headers, Mapping):
            continue
        response_headers = cast(Mapping[object, object], headers)
        for header in ("x-request-id", "apim-request-id", "request-id"):
            correlation_id = safe_provider_correlation_id(response_headers.get(header))
            if correlation_id is not None:
                correlation_source = source
                break
    return replace(
        result, correlation_id=correlation_id, correlation_source=correlation_source
    )


def _message_envelope_fields(error: BaseException) -> ProviderRejection:
    """The provider envelope an SDK kept only as text in the exception message.

    The OpenAI SDK formats a readable error body as ``Error code: 400 - {…}``
    (a Python literal); LiteLLM's Responses-API bridge forwards the raw JSON
    text the same way and drops the body attribute. The outermost ``{…}``
    span is parsed as one literal; the message itself is never retained.
    """

    message = getattr(error, "message", None)
    if not isinstance(message, str):
        message = str(error)
    if len(message) > _MAX_PROVIDER_ERROR_BODY_BYTES:
        return ProviderRejection(source="message", status="suppressed")
    start, end = message.find("{"), message.rfind("}")
    if start < 0 or end < start:
        return ProviderRejection(source="message")
    literal = message[start : end + 1]
    try:
        envelope: object = json.loads(literal)
    except RecursionError:
        # Nesting deep enough to exhaust the stack is malformed for our purpose;
        # the literal fallback would exhaust it again. Never let it replace the
        # provider failure this extractor was called to describe.
        return ProviderRejection(source="message", status="malformed")
    except ValueError:
        try:
            envelope = ast.literal_eval(literal)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return ProviderRejection(source="message", status="malformed")
    return _rejection_envelope_fields(envelope, "message", "message.error")


def _rejection_envelope_fields(
    body: object,
    source: ProviderRejectionSource,
    nested_source: ProviderRejectionSource,
) -> ProviderRejection:
    from eneo.flows.ai_builder.ai_builder_error_contract import (
        safe_provider_error_code,
        safe_provider_parameter,
    )

    if body is None:
        return ProviderRejection()
    if not isinstance(body, Mapping):
        return ProviderRejection(source=source, status="malformed")
    body_fields = cast(Mapping[object, object], body)
    result = ProviderRejection(source=source)
    candidates: tuple[tuple[object, ProviderRejectionSource], ...] = (
        (body_fields.get("error"), nested_source),
        (body_fields, source),
    )
    for fields, envelope_source in candidates:
        if fields is None:
            continue
        if not isinstance(fields, Mapping):
            candidate = ProviderRejection(source=envelope_source, status="malformed")
        else:
            error_fields = cast(Mapping[object, object], fields)
            raw_code, raw_parameter = (
                error_fields.get("code"),
                error_fields.get("param"),
            )
            code = safe_provider_error_code(raw_code, source=envelope_source)
            parameter = safe_provider_parameter(raw_parameter)
            suppressed = (
                raw_code is not None
                and code is None
                or raw_parameter is not None
                and parameter is None
            )
            candidate = ProviderRejection(
                code=code,
                parameter=parameter,
                source=envelope_source,
                status="suppressed"
                if suppressed
                else "found"
                if code is not None or parameter is not None
                else "absent",
            )
        result = _select_rejection(result, candidate)
        if result.code is not None or result.parameter is not None:
            break
    return result


def _select_rejection(
    current: ProviderRejection, candidate: ProviderRejection
) -> ProviderRejection:
    if candidate.code is not None or candidate.parameter is not None:
        return candidate
    severity = {"absent": 0, "malformed": 1, "suppressed": 2, "found": 3}
    if (
        current.source == "unavailable"
        or severity[candidate.status] > severity[current.status]
    ):
        return candidate
    return current


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
