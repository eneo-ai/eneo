import httpx

from eneo.main.logging import get_logger
from eneo.model_providers.domain.connection_check import (
    ConnectionCheck,
    ConnectionCheckError,
)
from eneo.model_providers.domain.provider_api import ProviderRequest

logger = get_logger(__name__)

# Room for a slow TLS handshake, short enough for an admin waiting on a button.
CONNECTION_CHECK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _http_client() -> httpx.AsyncClient:
    # Redirects are not followed, so the key is never sent to another host.
    return httpx.AsyncClient(timeout=CONNECTION_CHECK_TIMEOUT)


def classify_status(
    status_code: int, request: ProviderRequest
) -> ConnectionCheckError | None:
    """What an HTTP status says about the connection; None when it works."""
    if 200 <= status_code < 300:
        return None
    if status_code in request.key_rejected_statuses:
        return ConnectionCheckError.AUTHENTICATION_FAILED
    # A redirect means the configured address is not the API's either.
    if status_code == 404 or 300 <= status_code < 400:
        return ConnectionCheckError.NOT_FOUND
    if status_code == 429:
        return ConnectionCheckError.RATE_LIMITED
    if status_code >= 500:
        return ConnectionCheckError.PROVIDER_ERROR
    return ConnectionCheckError.REJECTED


async def probe_connection(
    request: ProviderRequest, *, provider_label: str
) -> ConnectionCheck:
    """Make the request and classify the answer. Only the status line is read:
    bodies and headers can echo the key, so none of them is kept or logged."""
    try:
        async with _http_client() as client:
            async with client.stream(
                "GET", request.url, headers=request.headers
            ) as response:
                status_code = response.status_code
    except httpx.TimeoutException as exc:
        error, detail = ConnectionCheckError.TIMEOUT, type(exc).__name__
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        error, detail = ConnectionCheckError.UNREACHABLE, type(exc).__name__
    except UnicodeEncodeError:
        # Headers are ASCII and only the key varies: no provider accepts it.
        error, detail = ConnectionCheckError.AUTHENTICATION_FAILED, "non-ASCII key"
    else:
        classified = classify_status(status_code, request)
        if classified is None:
            return ConnectionCheck.ok()
        error, detail = classified, f"HTTP {status_code}"

    logger.warning(
        "Connection check for model provider %s failed: %s (%s)",
        provider_label,
        error.value,
        detail,
    )
    return ConnectionCheck.failed(error)
