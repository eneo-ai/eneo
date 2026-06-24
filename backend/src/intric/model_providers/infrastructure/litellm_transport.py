from __future__ import annotations

import socket
from typing import Any, Callable, NoReturn, cast

import aiohttp
import httpx
import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from intric.main.exceptions import (
    APIKeyNotConfiguredException,
    BadRequestException,
    OpenAIException,
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

_PROVIDER_UNAVAILABLE_TEXT = (
    "cannot connect",
    "connection refused",
    "connection reset",
    "connection timed out",
    "temporary failure in name resolution",
    "name or service not known",
    "service unavailable",
    "timed out",
)
_PROVIDER_UNAVAILABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    APIConnectionError,
    Timeout,
    ServiceUnavailableError,
    InternalServerError,
    httpx.ConnectError,
    httpx.TimeoutException,
    aiohttp.ClientError,
    socket.gaierror,
    ConnectionError,
    TimeoutError,
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


async def acompletion(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "acompletion"))
    return await call(**kwargs)


async def aembedding(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "aembedding"))
    return await call(**kwargs)


async def atranscription(**kwargs: Any) -> Any:
    call = cast(Callable[..., Any], getattr(litellm, "atranscription"))
    return await call(**kwargs)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def is_provider_unavailable_error(exc: BaseException) -> bool:
    for chained in _exception_chain(exc):
        if isinstance(chained, _PROVIDER_UNAVAILABLE_EXCEPTIONS):
            return True
        error_text = str(chained).lower()
        if any(marker in error_text for marker in _PROVIDER_UNAVAILABLE_TEXT):
            return True
    return False


def raise_provider_unavailable(exc: BaseException) -> NoReturn:
    raise OpenAIException(
        PROVIDER_UNAVAILABLE_MESSAGE,
        code=PROVIDER_UNAVAILABLE_CODE,
        details={"reason": PROVIDER_UNAVAILABLE_CODE, "retryable": True},
    ) from exc


def raise_public_litellm_error(
    exc: BaseException,
    *,
    provider_type: str,
    is_unavailable: Callable[[BaseException], bool],
    raise_unavailable: Callable[[BaseException], NoReturn],
) -> NoReturn:
    """Map provider exceptions to stable public errors without leaking details."""
    if isinstance(exc, (APIKeyNotConfiguredException, OpenAIException)):
        raise exc

    if is_unavailable(exc):
        raise_unavailable(exc)

    if isinstance(exc, AuthenticationError):
        raise APIKeyNotConfiguredException(
            f"Invalid API credentials for provider '{provider_type}'. "
            "Please verify the provider configuration."
        ) from exc

    if isinstance(exc, RateLimitError):
        raise OpenAIException(
            RATE_LIMIT_MESSAGE,
            code="provider_rate_limited",
            details={"reason": "provider_rate_limited", "retryable": True},
        ) from exc

    if isinstance(exc, BadRequestError):
        raise ProviderRejectedRequestException(
            INVALID_REQUEST_MESSAGE,
            code="provider_rejected_request",
            details={"reason": "provider_rejected_request", "retryable": False},
        ) from exc

    if isinstance(exc, APIError):
        raise OpenAIException(
            PROVIDER_ERROR_MESSAGE,
            code="provider_error",
            details={"reason": "provider_error", "retryable": True},
        ) from exc

    raise OpenAIException(
        PROVIDER_ERROR_MESSAGE,
        code="provider_error",
        details={"reason": "provider_error", "retryable": True},
    ) from exc
