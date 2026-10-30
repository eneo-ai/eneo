from __future__ import annotations

import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, NoReturn, cast

import aiohttp
import httpx
import litellm
import openai
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    MidStreamFallbackError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnsupportedParamsError,
)

from eneo.flows.runtime.step_deadline import (
    current_step_deadline_scope,
    mark_provider_request_in_flight,
    require_step_budget,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    BadRequestException,
    OpenAIException,
    ProviderCapabilityRejectedException,
    ProviderRejectedRequestException,
)

INVALID_REQUEST_MESSAGE = "The AI provider rejected the request. Verify the model configuration and try again."
PROVIDER_ERROR_MESSAGE = (
    "The AI provider could not process the request. Please try again later."
)
RATE_LIMIT_MESSAGE = "The AI provider rate limit was exceeded. Please try again later."
STREAM_ERROR_MESSAGE = "The AI response stream ended unexpectedly. Please try again."
PROVIDER_UNAVAILABLE_MESSAGE = (
    "AI service is temporarily unavailable. Please try again later."
)
PROVIDER_UNAVAILABLE_CODE = "provider_unavailable"
STREAM_ERROR_CODE = "stream_error"


@dataclass(frozen=True)
class ProviderFailure:
    """What a failed provider call tells the user, and whether retrying helps.

    ``code`` is the public reason clients branch on. ``unavailable`` marks the
    failures that point at the provider being down, overloaded or unreachable
    rather than at the request or the model configuration.
    """

    code: str
    message: str
    retryable: bool
    unavailable: bool
    status: int = 503

    def to_exception(self) -> OpenAIException:
        exception_type = (
            ProviderRejectedRequestException
            if self.code == PROVIDER_REJECTED_REQUEST.code
            else OpenAIException
        )
        return exception_type(
            self.message,
            code=self.code,
            details={"reason": self.code, "retryable": self.retryable},
        )


# Eneo could not open a connection: DNS, refused, TLS or connect timeout. The
# provider may be down, but so may the network path to it.
PROVIDER_UNREACHABLE = ProviderFailure(
    code="provider_unreachable",
    message="The AI provider could not be reached. Please try again later.",
    retryable=True,
    unavailable=True,
)
PROVIDER_TIMEOUT = ProviderFailure(
    code="provider_timeout",
    message="The AI provider did not respond in time. Please try again later.",
    retryable=True,
    unavailable=True,
)
# The provider answered, with a server error or an overload status.
PROVIDER_UNAVAILABLE = ProviderFailure(
    code=PROVIDER_UNAVAILABLE_CODE,
    message=PROVIDER_UNAVAILABLE_MESSAGE,
    retryable=True,
    unavailable=True,
)
PROVIDER_CONNECTION_LOST = ProviderFailure(
    code="provider_connection_lost",
    message=("The connection to the AI provider was interrupted. Please try again."),
    retryable=True,
    unavailable=True,
)
PROVIDER_RATE_LIMITED = ProviderFailure(
    code="provider_rate_limited",
    message=RATE_LIMIT_MESSAGE,
    retryable=True,
    unavailable=False,
)
PROVIDER_MODEL_NOT_FOUND = ProviderFailure(
    code="provider_model_not_found",
    message=(
        "The AI provider does not offer the configured model. "
        "Contact your administrator."
    ),
    retryable=False,
    unavailable=False,
)
PROVIDER_REJECTED_REQUEST = ProviderFailure(
    code="provider_rejected_request",
    message=INVALID_REQUEST_MESSAGE,
    retryable=False,
    unavailable=False,
    status=400,
)
PROVIDER_ERROR = ProviderFailure(
    code="provider_error",
    message=PROVIDER_ERROR_MESSAGE,
    retryable=True,
    unavailable=False,
)
_FAILURES_BY_CODE = {
    failure.code: failure
    for failure in (
        PROVIDER_UNREACHABLE,
        PROVIDER_TIMEOUT,
        PROVIDER_UNAVAILABLE,
        PROVIDER_CONNECTION_LOST,
        PROVIDER_RATE_LIMITED,
        PROVIDER_MODEL_NOT_FOUND,
        PROVIDER_REJECTED_REQUEST,
        PROVIDER_ERROR,
    )
}

_CONNECT_FAILURES: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    aiohttp.ClientConnectorError,
    socket.gaierror,
    ConnectionRefusedError,
)
_CONNECTION_DROPS: tuple[type[BaseException], ...] = (
    MidStreamFallbackError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    aiohttp.ClientPayloadError,
    aiohttp.ServerDisconnectedError,
    ConnectionResetError,
)
_TIMEOUTS: tuple[type[BaseException], ...] = (
    Timeout,
    httpx.TimeoutException,
    TimeoutError,
)
# Anything left over that still says the provider or the path to it failed.
_UNAVAILABLE_FALLBACKS: tuple[type[BaseException], ...] = (
    APIConnectionError,
    ServiceUnavailableError,
    InternalServerError,
    aiohttp.ClientError,
    ConnectionError,
)
# Exceptions only the provider call raises; anything else in a stream is a
# failure on Eneo's side.
_PROVIDER_RAISED: tuple[type[BaseException], ...] = (
    openai.OpenAIError,
    OpenAIException,
    httpx.HTTPError,
    aiohttp.ClientError,
    socket.gaierror,
    ConnectionError,
    TimeoutError,
)
_UNSUPPORTED_CAPABILITY_CODES = frozenset(
    {
        "unsupported_parameter",
        "unsupported_value",
    }
)
_FAILURE_TEXT: tuple[tuple[str, ProviderFailure], ...] = (
    ("cannot connect", PROVIDER_UNREACHABLE),
    ("connection refused", PROVIDER_UNREACHABLE),
    ("connection timed out", PROVIDER_UNREACHABLE),
    ("temporary failure in name resolution", PROVIDER_UNREACHABLE),
    ("name or service not known", PROVIDER_UNREACHABLE),
    ("connection reset", PROVIDER_CONNECTION_LOST),
    ("service unavailable", PROVIDER_UNAVAILABLE),
    ("timed out", PROVIDER_TIMEOUT),
)

# Deterministic failures (invalid request/config, bad credentials) that adapter
# retry policies must not re-attempt — a retry can never change the outcome.
NON_RETRYABLE_PROVIDER_ERRORS: tuple[type[BaseException], ...] = (
    BadRequestException,
    ProviderRejectedRequestException,
    APIKeyNotConfiguredException,
)


def get_supported_openai_params(model: str) -> list[str] | None:
    return cast(
        list[str] | None, getattr(litellm, "get_supported_openai_params")(model=model)
    )


def get_model_info(model: str) -> dict[str, object]:
    return cast(dict[str, object], getattr(litellm, "get_model_info")(model=model))


async def acompletion(**kwargs: Any) -> Any:
    scope = current_step_deadline_scope()
    if scope is not None:
        require_step_budget(phase="provider request (not sent)")
        kwargs["timeout"] = scope.deadline.remaining()
    call = cast(Callable[..., Any], getattr(litellm, "acompletion"))
    mark_provider_request_in_flight(True)
    return await call(**kwargs)


async def aembedding(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "aembedding"))
    return await call(**kwargs)


async def arerank(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "arerank"))
    return await call(**kwargs)


async def atranscription(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "atranscription"))
    return await call(**kwargs)


async def aimage_generation(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "aimage_generation"))
    return await call(**kwargs)


async def aimage_edit(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "aimage_edit"))
    return await call(**kwargs)


# LiteLLM's pre-call refusal ("Setting `response_format` is not supported by
# openai, gpt-image-1"), its per-model list variant ("The following parameters
# are not supported for model gpt-image-1: response_format, quality"), and the
# provider's own rejection once the request was sent ("Unknown parameter:
# 'quality'").
_UNSUPPORTED_PARAM_RES = (
    re.compile(r"Setting `(\w+)` is not supported"),
    re.compile(r"not supported for model [^:]*: *(\w+)"),
    re.compile(r"Unknown parameter: '(\w+)'"),
)


def unsupported_param(exc: BaseException) -> str | None:
    """The request parameter a model rejected, when that is what ``exc`` says.

    LiteLLM refuses parameters a model does not support before any network
    call and providers reject unknown ones after it; each error names at least
    one parameter, so callers drop the first and retry.
    """
    for candidate in _exception_chain(exc):
        if not isinstance(candidate, (UnsupportedParamsError, BadRequestError)):
            continue
        text = str(candidate)
        for pattern in _UNSUPPORTED_PARAM_RES:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _status_code(exc: BaseException) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def classify_provider_failure(exc: BaseException) -> ProviderFailure:
    """Classify a failed provider call from its whole exception chain.

    LiteLLM reports a refused connection as ``InternalServerError`` (500) and a
    dropped stream as ``MidStreamFallbackError`` (a ``ServiceUnavailableError``),
    so the transport errors underneath are checked before any status code.
    """
    chain = _exception_chain(exc)
    statuses = {status for c in chain if (status := _status_code(c)) is not None}

    for candidate in chain:
        if isinstance(candidate, OpenAIException) and candidate.code:
            known = _FAILURES_BY_CODE.get(candidate.code)
            if known is not None:
                return known
    if 429 in statuses or any(isinstance(c, RateLimitError) for c in chain):
        return PROVIDER_RATE_LIMITED
    if any(isinstance(c, _CONNECT_FAILURES) for c in chain):
        return PROVIDER_UNREACHABLE
    # LiteLLM also wraps mid-stream read timeouts in MidStreamFallbackError;
    # the concrete cause takes precedence over that generic stream wrapper.
    if statuses & {408, 504} or any(isinstance(c, _TIMEOUTS) for c in chain):
        return PROVIDER_TIMEOUT
    if any(isinstance(c, _CONNECTION_DROPS) for c in chain):
        return PROVIDER_CONNECTION_LOST
    # Some providers answer an unknown model with 404 and LiteLLM may still
    # wrap it as BadRequestError, so this precedes the rejection check.
    if 404 in statuses or any(isinstance(c, NotFoundError) for c in chain):
        return PROVIDER_MODEL_NOT_FOUND
    if any(status >= 500 for status in statuses) or any(
        isinstance(c, _UNAVAILABLE_FALLBACKS) for c in chain
    ):
        return PROVIDER_UNAVAILABLE
    if any(isinstance(c, BadRequestError) for c in chain):
        return PROVIDER_REJECTED_REQUEST
    for candidate in chain:
        error_text = str(candidate).lower()
        for marker, failure in _FAILURE_TEXT:
            if marker in error_text:
                return failure
    return PROVIDER_ERROR


def classify_stream_failure(exc: BaseException) -> ProviderFailure | None:
    """Classify a failure inside a running stream, or None when Eneo caused it.

    A stream also runs Eneo's own tool handling, so only exceptions raised by
    the provider call (or describing a provider failure) are blamed on it.
    """
    failure = classify_provider_failure(exc)
    if failure is not PROVIDER_ERROR:
        return failure
    if any(isinstance(c, _PROVIDER_RAISED) for c in _exception_chain(exc)):
        return failure
    return None


def is_provider_unavailable_error(exc: BaseException) -> bool:
    return classify_provider_failure(exc).unavailable


def provider_failure_for_code(code: str | None) -> ProviderFailure | None:
    """The provider failure a public code names, or None for any other code.

    For callers that decide on an error Eneo already typed: unlike
    ``classify_provider_failure`` it never reads the message."""
    return _FAILURES_BY_CODE.get(code) if code is not None else None


def raise_provider_unavailable(exc: BaseException) -> NoReturn:
    raise classify_provider_failure(exc).to_exception() from exc


def _provider_error_field(exc: BaseException, field: str) -> object:
    value = getattr(exc, field, None)
    if value is not None:
        return value
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return None
    body_fields = cast(Mapping[object, object], body)
    error = body_fields.get("error")
    if isinstance(error, Mapping):
        return cast(Mapping[object, object], error).get(field)
    return body_fields.get(field)


def _is_response_format_capability_rejection(exc: BaseException) -> bool:
    return (
        _provider_error_field(exc, "param") == "response_format"
        and _provider_error_field(exc, "code") in _UNSUPPORTED_CAPABILITY_CODES
    )


def raise_public_litellm_error(
    exc: BaseException,
    *,
    provider_type: str,
    is_unavailable: Callable[[BaseException], bool],
    raise_unavailable: Callable[[BaseException], NoReturn],
    retry_without_capability_safe: bool = False,
) -> NoReturn:
    """Map provider exceptions to stable public errors without leaking details."""
    if isinstance(exc, (APIKeyNotConfiguredException, OpenAIException)):
        raise exc

    if isinstance(exc, BadRequestError) and _is_response_format_capability_rejection(
        exc
    ):
        raise ProviderCapabilityRejectedException(
            INVALID_REQUEST_MESSAGE,
            capability="response_format",
            retry_without_capability_safe=retry_without_capability_safe,
            code="provider_rejected_request",
            details={
                "reason": "provider_capability_rejected",
                "capability": "response_format",
                "retryable": False,
            },
        ) from exc

    if is_unavailable(exc):
        raise_unavailable(exc)

    if isinstance(exc, AuthenticationError):
        raise APIKeyNotConfiguredException(
            f"Invalid API credentials for provider '{provider_type}'. "
            "Please verify the provider configuration."
        ) from exc

    raise classify_provider_failure(exc).to_exception() from exc
