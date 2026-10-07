from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport.authored_config import (
    HttpAuthoredConfig,
    HttpMethod,
    contains_secret_sentinel,
)
from eneo.flows.http_transport.compiler import (
    EffectiveHttpRequest,
    compile_http_config,
)
from eneo.flows.http_transport.errors import (
    AuthoredSecretEncryptionUnavailableError,
    HttpCredentialTransportError,
    HttpTemplateInterpolationError,
    HttpTransportError,
)
from eneo.flows.http_transport.request_preview import HttpRequestPreview
from eneo.flows.http_transport.secret_codec import (
    SupportsEncryption,
    decrypt_authored_config,
    merge_secrets_on_update,
    protect_authored_secrets,
    unprotected_stored_secret_fields,
    unresolved_secret_sentinel_fields,
)
from eneo.flows.http_transport.validator import (
    validate_authored_config,
    validate_http_url,
)
from eneo.main.exceptions import (
    EncryptionNotConfiguredException,
    TypedIOValidationException,
)

_TYPED_TRANSPORT_ERRORS: dict[str, HttpTransportError] = {
    FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL.value: HttpTransportError.INVALID_URL,
    FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value: HttpTransportError.BLOCKED_URL,
    FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE.value: HttpTransportError.RESPONSE_TOO_LARGE,
    FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value: HttpTransportError.CONNECTION_REFUSED,
}


@dataclass(frozen=True)
class HttpTestResult:
    success: bool
    status_code: int | None = None
    duration_ms: float = 0.0
    response_preview: str | None = None
    request_preview: HttpRequestPreview | None = None
    error_code: HttpTransportError | None = None
    error_message: str | None = None


async def execute_http_test(
    *,
    config: HttpAuthoredConfig,
    direction: str,
    method: HttpMethod,
    test_variables: dict[str, Any] | None = None,
    stored_config: HttpAuthoredConfig | None = None,
    encryption_service: SupportsEncryption | None = None,
    interpolate: Callable[[str, dict[str, Any]], str],
    send_http_request: Callable[..., Awaitable[httpx.Response]],
    max_timeout: float,
) -> HttpTestResult:
    """Execute a draft-safe HTTP test without persisting authored config."""

    try:
        merged = protect_authored_secrets(config, encryption_service)
    except AuthoredSecretEncryptionUnavailableError as exc:
        raise EncryptionNotConfiguredException(
            "HTTP credential encryption is unavailable."
        ) from exc
    if stored_config is not None:
        merged = merge_secrets_on_update(merged, stored_config)

    if set(unresolved_secret_sentinel_fields(config)).intersection(
        unprotected_stored_secret_fields(merged, encryption_service)
    ):
        return HttpTestResult(
            success=False,
            error_code=HttpTransportError.UNRESOLVED_STORED_SECRET,
            error_message=_error_message(HttpTransportError.UNRESOLVED_STORED_SECRET),
        )

    decrypted = decrypt_authored_config(merged, encryption_service)
    if contains_secret_sentinel(decrypted.model_dump(mode="json")):
        return HttpTestResult(
            success=False,
            error_code=HttpTransportError.UNRESOLVED_STORED_SECRET,
            error_message=_error_message(HttpTransportError.UNRESOLVED_STORED_SECRET),
        )

    errors = validate_authored_config(
        decrypted, direction=direction, method=method, max_timeout=max_timeout
    )
    if errors:
        return HttpTestResult(
            success=False,
            error_code=errors[0],
            error_message=_error_message(errors[0], max_timeout=max_timeout),
        )

    try:
        effective = compile_http_config(
            decrypted,
            direction=direction,
            method=method,
            variables=test_variables,
            interpolate=interpolate,
        )
    except HttpCredentialTransportError:
        return HttpTestResult(
            success=False,
            error_code=HttpTransportError.CREDENTIALS_REQUIRE_HTTPS,
            error_message=_error_message(HttpTransportError.CREDENTIALS_REQUIRE_HTTPS),
        )
    except HttpTemplateInterpolationError:
        return HttpTestResult(
            success=False,
            error_code=HttpTransportError.VARIABLE_RESOLUTION_FAILED,
            error_message=_error_message(HttpTransportError.VARIABLE_RESOLUTION_FAILED),
            request_preview=None,
        )
    except TypedIOValidationException as exc:
        error_code = _TYPED_TRANSPORT_ERRORS.get(exc.code or "")
        if error_code is None:
            raise
        return HttpTestResult(
            success=False,
            error_code=error_code,
            error_message=_error_message(error_code),
        )

    request_preview = _request_preview(effective)
    url_error = validate_http_url(effective.url)
    if url_error is not None:
        return HttpTestResult(
            success=False,
            error_code=url_error,
            error_message=_error_message(url_error),
            request_preview=request_preview,
        )

    start = time.monotonic()
    try:
        response = await send_http_request(
            method=effective.method,
            url=effective.url,
            headers=effective.headers,
            timeout_seconds=effective.timeout,
            body_bytes=effective.body,
            json_body=effective.json_body,
            read_response_body=not bool(effective.secret_header_names),
        )
    except httpx.TimeoutException:
        duration_ms = (time.monotonic() - start) * 1000
        return HttpTestResult(
            success=False,
            duration_ms=duration_ms,
            error_code=HttpTransportError.TIMEOUT,
            error_message=f"Connection timed out after {config.timeout_seconds} seconds",
            request_preview=request_preview,
        )
    except TypedIOValidationException as exc:
        duration_ms = (time.monotonic() - start) * 1000
        error_code = _TYPED_TRANSPORT_ERRORS.get(exc.code or "")
        if error_code is None:
            # An unmapped typed failure is a server-side defect; hiding it as
            # a connection problem would bury the signal.
            raise
        return HttpTestResult(
            success=False,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message=_error_message(error_code),
            request_preview=request_preview,
        )
    except httpx.HTTPError:
        duration_ms = (time.monotonic() - start) * 1000
        return HttpTestResult(
            success=False,
            duration_ms=duration_ms,
            error_code=HttpTransportError.CONNECTION_REFUSED,
            error_message=_error_message(HttpTransportError.CONNECTION_REFUSED),
            request_preview=request_preview,
        )

    duration_ms = (time.monotonic() - start) * 1000

    # An authenticated target can echo credentials in arbitrary encodings.
    response_preview = None if effective.secret_header_names else response.text[:2000]

    success = response.status_code < 400
    error_code = None
    error_message = None
    if not success:
        error_code = HttpTransportError.STATUS_ERROR
        error_message = f"Server responded with status {response.status_code}"

    return HttpTestResult(
        success=success,
        status_code=response.status_code,
        duration_ms=duration_ms,
        response_preview=response_preview,
        request_preview=request_preview,
        error_code=error_code,
        error_message=error_message,
    )


def _request_preview(effective: EffectiveHttpRequest) -> HttpRequestPreview:
    body = _body_preview(effective)
    return HttpRequestPreview(
        method=effective.method,
        url=_redact_preview(effective.url, effective.secret_values),
        headers={
            name: "[REDACTED]"
            if name.lower() in effective.secret_header_names
            else _redact_preview(value, effective.secret_values)
            for name, value in effective.headers.items()
        },
        body_preview=(
            _redact_preview(body, effective.secret_values)[:500]
            if body is not None
            else None
        ),
    )


def _redact_preview(text: str, secrets: frozenset[str]) -> str:
    if not secrets:
        return text
    # Literal values, longest first, are replaced once before preview truncation.
    pattern = "|".join(
        re.escape(value) for value in sorted(secrets, key=len, reverse=True)
    )
    return re.sub(pattern, "[REDACTED]", text)


def _body_preview(effective: EffectiveHttpRequest) -> str | None:
    if effective.json_body is not None:
        import json

        return json.dumps(effective.json_body, ensure_ascii=False)
    if effective.body is not None:
        return effective.body.decode("utf-8", errors="replace")
    return None


def _error_message(
    error: HttpTransportError, *, max_timeout: float | None = None
) -> str:
    if error == HttpTransportError.TIMEOUT_OUT_OF_RANGE:
        if max_timeout is None:
            raise ValueError("HTTP timeout diagnostic requires the configured limit.")
        return f"Timeout must be between 1 and {max_timeout:g} seconds"
    messages = {
        HttpTransportError.MISSING_URL: "URL required for HTTP delivery",
        HttpTransportError.INVALID_URL: "Invalid URL format",
        HttpTransportError.VARIABLE_RESOLUTION_FAILED: "Variable resolution failed",
        HttpTransportError.UNRESOLVED_STORED_SECRET: "Saved secret is unavailable; re-enter the secret and save the flow",
        HttpTransportError.MISSING_AUTH_CREDENTIALS: "Authentication credentials missing",
        HttpTransportError.INVALID_BODY_JSON: "Invalid JSON in request template",
        HttpTransportError.BODY_NOT_ALLOWED_FOR_GET: "GET requests cannot have a body",
        HttpTransportError.TIMEOUT: "Connection timed out",
        HttpTransportError.CONNECTION_REFUSED: "Could not connect to server",
        HttpTransportError.BLOCKED_URL: "URL blocked by network policy",
        HttpTransportError.RESPONSE_TOO_LARGE: "HTTP response is too large to preview",
        HttpTransportError.STATUS_ERROR: "Server responded with error",
        HttpTransportError.CREDENTIALS_REQUIRE_HTTPS: "HTTP credentials require a fixed HTTPS origin",
    }
    return messages.get(error, error.value)
