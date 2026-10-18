"""One owner for every AI Builder provider completion.

A provider answer is streamed so that a slow model is observable while it
works: the deadline bounds *silence*, the wait for the next yielded chunk
once a chunk that carries output has arrived, not the whole answer, so a model that keeps
producing is not cut off by that deadline however long it takes, while a
stalled stream is still detected. Before the first chunk that carries output
a thinking call cannot be told from a hung one (a provider may send chunks
without output first), so its caller may allow that wait up to the ceiling.
A separate, longer ceiling bounds the
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

The turn that owns the call may stop it: once its stop signal is set (its
ownership of the session was confirmed lost), every wait, for the first
response and for each chunk, ends at once, the stream is closed, and
``ProviderCallStopped`` is raised. It is not a timeout and not a provider
failure; the caller reports it as the lost lease it is.

A provider refusal is raised as it is; nothing is sent again here. Its
envelope is read from wherever the SDK left it: LiteLLM's Responses-API bridge (which carries Azure and OpenAI
gpt-5.4+ requests with function tools) re-raises a provider 400 with only
the envelope text in the exception message, no body and a placeholder
response, so the message is the last source tried.
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Literal, Protocol, cast

import httpx

from eneo.completion_models.infrastructure.stream_collector import (
    ProviderStreamCollector,
)
from eneo.completion_models.infrastructure.stream_collector import (
    ProviderStreamIncomplete as ProviderStreamIncomplete,
)

_MAX_PROVIDER_ERROR_BODY_BYTES = 65_536
_MAX_PROVIDER_FACT_LENGTH = 64
# A sanitized parameter must fit one public error detail string, and a
# correlation id the length a request id may have.
_MAX_PROVIDER_PARAMETER_LENGTH = 256
_MAX_PROVIDER_CORRELATION_ID_LENGTH = 128
# Parameter suffixes can contain user-controlled schema names.
PROVIDER_ERROR_PARAMETERS = frozenset(
    {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "temperature",
        "top_p",
        "top_k",
        "reasoning_effort",
        "max_tokens",
        "max_completion_tokens",
        "verbosity",
        "stream",
        "presence_penalty",
        "frequency_penalty",
        "api_version",
    }
)

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


# Which of Eneo's own provider-call timers expired.
ProviderDeadlineKind = Literal["silence", "ceiling"]


class ProviderDeadlineExpired(TimeoutError):
    """One of Eneo's own provider-call timers expired.

    ``seconds`` is the limit that fired (the first-output allowance or the gap
    limit for silence, the call ceiling for a ceiling) and ``kind`` names the
    timer, so a caller reports both without reading the exception text. A
    limit that is not a finite positive number is a programming error: it
    would reach the public error as a wait nobody could have been given.
    """

    kind: ClassVar[ProviderDeadlineKind]

    def __init__(self, seconds: float) -> None:
        if not (math.isfinite(seconds) and seconds > 0):
            raise ValueError(f"a deadline is a finite positive number, got {seconds}")
        super().__init__(seconds)
        self.seconds = float(seconds)


class ProviderSilenceExpired(ProviderDeadlineExpired):
    """No chunk arrived from the provider within the silence deadline."""

    kind: ClassVar[ProviderDeadlineKind] = "silence"


class ProviderCallCeilingExpired(ProviderDeadlineExpired):
    """The whole provider call exceeded its ceiling.

    Either an answer that kept producing, or a call that may think and produced
    no output at all: the ceiling is its wait before the first output.
    """

    kind: ClassVar[ProviderDeadlineKind] = "ceiling"


class ProviderCallStopped(Exception):
    """The turn that owns the call stopped it; the call was cancelled."""


class ProviderRequestNotAdmitted(Exception):
    """The owning turn refused to admit a request; nothing was sent.

    ``error`` is the turn's own error (a lost lease, a failed write); it is
    not a provider failure and callers raise it as it is.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


@dataclass(frozen=True, slots=True)
class ProviderWorkGate:
    """What a send turn's provider work answers to; the send lease mints it.

    The provider-call seam owns its use: before the outbound request it checks
    ``ownership_lost`` and awaits ``admit``, a lease-guarded write that raises
    ``session_send_lease_lost`` once the turn no longer owns its session. The
    two signals mean different things: ``ownership_lost`` is set only when the
    session is confirmed to be no longer the turn's, and stops the provider
    work in flight; ``lease_lost`` is set whenever the lease can no longer be
    trusted (that loss, or a refresh that failed) and is read only by the
    planner's post-dispatch result fencing (a server decision's result is not
    emitted once it is set).
    """

    admit: Callable[[], Awaitable[None]]
    ownership_lost: asyncio.Event
    lease_lost: asyncio.Event
    session_id: str
    request_id: str


class _StopRace:
    """Races every wait inside it against the turn's stop signal.

    A signal already set sends nothing. Once it is set, the wait in progress
    is cancelled the way ``asyncio.timeout`` cancels on expiry, so cleanup
    around the wait (closing the stream) runs as for any other ending.
    """

    def __init__(self, gate: ProviderWorkGate | None) -> None:
        self._stop_signal = gate.ownership_lost if gate is not None else None
        self._scope: asyncio.Timeout | None = None
        self._watcher: asyncio.Task[None] | None = None

    async def __aenter__(self) -> None:
        stop_signal = self._stop_signal
        if stop_signal is None:
            return
        if stop_signal.is_set():
            raise ProviderCallStopped
        scope = asyncio.timeout(None)
        await scope.__aenter__()
        self._scope = scope
        loop = asyncio.get_running_loop()

        async def stop_when_signalled() -> None:
            await stop_signal.wait()
            scope.reschedule(loop.time())

        self._watcher = asyncio.create_task(stop_when_signalled())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool | None:
        if self._scope is None:
            return None
        if self._watcher is not None:
            self._watcher.cancel()
        try:
            return await self._scope.__aexit__(exc_type, exc, tb)
        except TimeoutError as stopped:
            raise ProviderCallStopped from stopped


@dataclass(frozen=True, slots=True)
class ProviderCallTiming:
    """When the provider's answer arrived, measured from sending the request.

    ``first_chunk_ms`` and ``max_gap_ms`` are None when no chunk arrived (a
    whole, non-streamed answer included). ``max_gap_ms`` is the longest wait
    for a chunk after the first one, the wait the call ended on included, so
    a stall that expired the silence deadline shows at least that deadline.
    """

    provider_elapsed_ms: int
    first_chunk_ms: int | None = None
    max_gap_ms: int | None = None


@dataclass(slots=True)
class ObservedTiming:
    """An ``observe_timing`` callback that keeps what the seam reported."""

    value: ProviderCallTiming | None = None

    def __call__(self, timing: ProviderCallTiming) -> None:
        self.value = timing


class _ChunkClock:
    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._first: float | None = None
        self._last: float | None = None
        self._max_gap = 0.0

    def wait_ended(self, *, chunk_arrived: bool) -> None:
        """One wait for the next chunk ended: with a chunk, the end, or an error."""

        now = time.perf_counter()
        if self._last is not None:
            self._max_gap = max(self._max_gap, now - self._last)
        if chunk_arrived:
            if self._first is None:
                self._first = now
            self._last = now

    def timing(self) -> ProviderCallTiming:
        return ProviderCallTiming(
            provider_elapsed_ms=_ms(time.perf_counter() - self._started),
            first_chunk_ms=(
                None if self._first is None else _ms(self._first - self._started)
            ),
            max_gap_ms=None if self._first is None else _ms(self._max_gap),
        )


class _DispatchedRequest:
    """Provider timing of a call's request; it exists only from its dispatch.

    No clock runs while the turn admits the request: its clock starts when it
    is sent. A call that sent nothing has no provider timing.
    """

    def __init__(self) -> None:
        self._clock: _ChunkClock | None = None

    def dispatch(self) -> _ChunkClock:
        self._clock = _ChunkClock()
        return self._clock

    def timing(self) -> ProviderCallTiming | None:
        """The request's timing, or None when nothing was sent."""

        return self._clock.timing() if self._clock is not None else None


def _ms(seconds: float) -> int:
    return max(0, int(seconds * 1000))


def _chunk_carries_output(chunk: Any) -> bool:
    """Whether a streamed chunk is the model's output, not only the stream's start.

    A provider may open a stream with chunks that carry nothing the model
    produced (a role-only delta, a prompt-filter notice with no choices) while
    the model is still thinking; those must not end the wait that a thinking
    call is allowed. Reasoning text counts as output: a stream that reasons
    aloud is alive and is held to the silence deadline.
    """

    if getattr(chunk, "usage", None) is not None:
        return True
    for choice in getattr(chunk, "choices", None) or ():
        if getattr(choice, "finish_reason", None):
            return True
        delta = getattr(choice, "delta", None)
        if any(
            getattr(delta, field, None)
            for field in (
                "content",
                "tool_calls",
                "function_call",
                "reasoning_content",
                "thinking_blocks",
                "audio",
            )
        ):
            return True
    return False


async def complete_with_silence_deadline(
    litellm_client: CompletionClient,
    *,
    silence_deadline_seconds: float,
    ceiling_seconds: float,
    first_output_deadline_seconds: float,
    request: Mapping[str, Any],
    observe_sdk_input: Callable[[Mapping[str, Any]], None] | None = None,
    observe_timing: Callable[[ProviderCallTiming], None] | None = None,
    gate: ProviderWorkGate | None = None,
) -> Any:
    """The provider's complete answer, streamed under a silence deadline.

    ``silence_deadline_seconds`` is the longest wait for the next yielded
    chunk once a chunk that carries output has arrived.
    ``first_output_deadline_seconds`` is the longest wait for the response
    headers and for each chunk before that first output, between
    ``silence_deadline_seconds`` and ``ceiling_seconds``. A request that is thinking is silent until its first
    output, even when the provider sent chunks without output before it, and
    that cannot be told from a hung one, so its caller may allow that wait up
    to the ceiling. ``ceiling_seconds`` bounds the provider's time on the
    whole call; the SDK is given the ceiling as its own read timeout, only a
    backstop behind these local deadlines. The wait for the turn to admit the
    request is not the provider's time and runs under neither deadline nor
    the timing. Each expiry raises its own ``TimeoutError`` subclass, which
    the failure classifier records as a timeout with an unknown provider
    outcome. The stream is closed on every exit, within a bounded wait that
    never hides the original error. A provider refusal is raised.
    ``observe_timing`` receives the request's timing, once, however the call
    ends, before the stream is closed, and is not called when no request was
    sent. ``gate`` is the owning turn's: the request is admitted through it
    right before it is sent (a refusal ends the call with
    ``ProviderRequestNotAdmitted``), and
    once its ``ownership_lost`` is set the call ends with
    ``ProviderCallStopped``.
    """

    if not (math.isfinite(silence_deadline_seconds) and silence_deadline_seconds > 0):
        raise ValueError("AI Builder silence deadline must be positive and finite")
    if not (
        math.isfinite(ceiling_seconds) and ceiling_seconds >= silence_deadline_seconds
    ):
        raise ValueError(
            "AI Builder call ceiling must be finite and not below the silence deadline"
        )
    # The bounds are finite, so a NaN or infinite deadline fails this too.
    if not (
        silence_deadline_seconds <= first_output_deadline_seconds <= ceiling_seconds
    ):
        raise ValueError(
            "AI Builder first-output deadline must lie between the silence "
            "deadline and the call ceiling"
        )
    outbound = {
        **request,
        "stream": True,
        # Usage arrives in the final chunk where the provider supports it;
        # drop_params removes the option elsewhere.
        "stream_options": {"include_usage": True},
        # The local timers own every deadline. A SDK read timeout equal to
        # one of them raced it, and an expiry the SDK fired first was
        # classified as an ambiguous transport failure with no local deadline.
        "timeout": ceiling_seconds,
    }
    loop = asyncio.get_running_loop()
    ceiling = asyncio.timeout(None)
    dispatched = _DispatchedRequest()

    async with ProviderStreamCollector() as collector:
        try:
            async with _StopRace(gate), ceiling:
                # The ceiling and the timing are the provider's: they start
                # once the turn has admitted the request.
                await _admit(gate)
                ceiling.reschedule(loop.time() + ceiling_seconds)
                clock = dispatched.dispatch()
                if observe_sdk_input is not None:
                    observe_sdk_input(outbound)
                response = await _under_silence(
                    litellm_client.acompletion(**outbound),
                    first_output_deadline_seconds,
                )
                # Chunks without output (a role-only delta, a prompt-filter
                # notice) do not end the wait for the first output.
                first_output_pending = True

                async def next_chunk(stream: AsyncIterator[Any]) -> Any:
                    nonlocal first_output_pending
                    try:
                        chunk = await _under_silence(
                            anext(stream),
                            first_output_deadline_seconds
                            if first_output_pending
                            else silence_deadline_seconds,
                        )
                    except BaseException:
                        clock.wait_ended(chunk_arrived=False)
                        raise
                    if _chunk_carries_output(chunk):
                        first_output_pending = False
                    clock.wait_ended(chunk_arrived=True)
                    return chunk

                return await collector.collect(
                    response, request=outbound, next_chunk=next_chunk
                )
        except TimeoutError as error:
            if isinstance(error, ProviderSilenceExpired):
                raise
            if ceiling.expired():
                raise ProviderCallCeilingExpired(ceiling_seconds) from error
            raise
        finally:
            timing = dispatched.timing()
            if observe_timing is not None and timing is not None:
                observe_timing(timing)


def provider_error_fields(error: BaseException) -> ProviderRejection:
    """Recover structured rejection facts without reading a response stream.

    Try the nested and flat SDK body, then the buffered HTTP body, then the
    one envelope literal the SDK embedded in the exception message. An
    envelope wins only when it supplies a safe fact; otherwise preserve the
    strongest extraction failure. Publication policy belongs to the error
    contract.
    """

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


def safe_provider_error_code(
    value: object, *, source: ProviderRejectionSource
) -> str | None:
    if source not in {
        "body",
        "body.error",
        "response",
        "response.error",
        "message",
        "message.error",
    }:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_PROVIDER_FACT_LENGTH:
        return None
    return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value, re.ASCII) else None


def safe_provider_parameter(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= _MAX_PROVIDER_PARAMETER_LENGTH
    ):
        return None
    if value in PROVIDER_ERROR_PARAMETERS:
        return value
    # Only protocol-owned paths are normalized; schema property names are not.
    match = re.fullmatch(
        r"(?P<root>tools)(?:\[[0-9]+\]|\.[0-9]+)(?:\.type|\.function(?:\.(?:name|description|parameters|strict))?)?"
        r"|(?P<messages>messages)(?:\[[0-9]+\]|\.[0-9]+)(?:\.(?:role|content|name|tool_calls|tool_call_id))?"
        r"|(?P<format>response_format)\.(?:type|json_schema(?:\.(?:name|description|schema|strict))?)"
        r"|(?P<choice>tool_choice)\.(?:type|function(?:\.name)?)",
        value,
        re.ASCII,
    )
    return (
        next((root for root in match.groups() if root is not None), None)
        if match
        else None
    )


def safe_provider_correlation_id(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= _MAX_PROVIDER_CORRELATION_ID_LENGTH
    ):
        return None
    return (
        value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value, re.ASCII) else None
    )


async def _admit(gate: ProviderWorkGate | None) -> None:
    """Admit one outbound request through the owning turn, right before it."""

    if gate is None:
        return
    try:
        await gate.admit()
    except Exception as error:
        raise ProviderRequestNotAdmitted(error) from error
    # A loss confirmed before or while the admission ran stops the request
    # even when the write still found the row (it read before the loss).
    if gate.ownership_lost.is_set():
        raise ProviderCallStopped


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
