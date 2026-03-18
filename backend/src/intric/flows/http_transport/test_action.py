from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from intric.flows.http_transport.authored_config import HttpAuthoredConfig
from intric.flows.http_transport.compiler import compile_http_config
from intric.flows.http_transport.errors import HttpTransportError
from intric.flows.http_transport.secret_codec import (
    SupportsEncryption,
    decrypt_authored_config,
    merge_secrets_on_update,
)
from intric.flows.http_transport.validator import validate_authored_config


@dataclass(frozen=True)
class HttpTestResult:
    success: bool
    status_code: int | None = None
    duration_ms: float = 0.0
    response_preview: str | None = None
    request_preview: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


async def execute_http_test(
    *,
    config: HttpAuthoredConfig,
    direction: str,
    method: str,
    test_variables: dict[str, Any] | None = None,
    stored_config: HttpAuthoredConfig | None = None,
    encryption_service: SupportsEncryption | None = None,
    send_http_request: Callable[..., Awaitable[httpx.Response]],
    max_timeout: float = 120.0,
) -> HttpTestResult:
    """Execute a draft-safe HTTP test. Does NOT persist anything.

    1. Validates the submitted config
    2. Merges sentinel values with stored encrypted values
    3. Decrypts secrets
    4. Compiles to effective request
    5. Sends HTTP request
    6. Returns result
    """
    # Validate
    errors = validate_authored_config(
        config, direction=direction, method=method, max_timeout=max_timeout
    )
    if errors:
        return HttpTestResult(
            success=False,
            error_code=errors[0].value,
            error_message=_error_message(errors[0]),
        )

    # Merge secrets if stored config exists
    merged = config
    if stored_config is not None:
        merged = merge_secrets_on_update(config, stored_config)

    # Decrypt
    decrypted = decrypt_authored_config(merged, encryption_service)

    # Compile
    effective = compile_http_config(
        decrypted,
        direction=direction,
        method=method,
        variables=test_variables,
    )

    # Build request preview (with secrets masked)
    request_preview = {
        "method": effective.method,
        "url": effective.url,
        "headers": _mask_sensitive_headers(effective.headers),
        "body_preview": _body_preview(effective),
    }

    # Send
    start = time.monotonic()
    try:
        response = await send_http_request(
            method=effective.method,
            url=effective.url,
            headers=effective.headers,
            timeout_seconds=effective.timeout,
            body_bytes=effective.body,
            json_body=effective.json_body,
        )
    except httpx.TimeoutException:
        duration_ms = (time.monotonic() - start) * 1000
        return HttpTestResult(
            success=False,
            duration_ms=duration_ms,
            error_code=HttpTransportError.TIMEOUT.value,
            error_message=f"Connection timed out after {config.timeout_seconds} seconds",
            request_preview=request_preview,
        )
    except httpx.HTTPError as exc:
        duration_ms = (time.monotonic() - start) * 1000
        return HttpTestResult(
            success=False,
            duration_ms=duration_ms,
            error_code=HttpTransportError.CONNECTION_REFUSED.value,
            error_message=f"Connection failed: {exc}",
            request_preview=request_preview,
        )

    duration_ms = (time.monotonic() - start) * 1000

    # Read response preview
    response_preview = None
    try:
        text = response.text[:2000]
        response_preview = text
    except Exception:
        pass

    success = response.status_code < 400
    error_code = None
    error_message = None
    if not success:
        error_code = HttpTransportError.STATUS_ERROR.value
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


def _mask_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    sensitive = {"authorization", "x-api-key"}
    masked = {}
    for key, value in headers.items():
        if key.lower() in sensitive:
            masked[key] = value[:10] + "..." if len(value) > 10 else value
        else:
            masked[key] = value
    return masked


def _body_preview(effective: Any) -> str | None:
    if effective.json_body is not None:
        import json

        return json.dumps(effective.json_body, ensure_ascii=False)[:500]
    if effective.body is not None:
        return effective.body.decode("utf-8", errors="replace")[:500]
    return None


def _error_message(error: HttpTransportError) -> str:
    messages = {
        HttpTransportError.MISSING_URL: "URL required for HTTP delivery",
        HttpTransportError.INVALID_URL: "Invalid URL format",
        HttpTransportError.MISSING_AUTH_CREDENTIALS: "Authentication credentials missing",
        HttpTransportError.INVALID_BODY_JSON: "Invalid JSON in request template",
        HttpTransportError.BODY_NOT_ALLOWED_FOR_GET: "GET requests cannot have a body",
        HttpTransportError.TIMEOUT_OUT_OF_RANGE: "Timeout must be between 1 and 120 seconds",
        HttpTransportError.SSRF_BLOCKED: "Private network addresses not allowed",
        HttpTransportError.TIMEOUT: "Connection timed out",
        HttpTransportError.CONNECTION_REFUSED: "Could not connect to server",
        HttpTransportError.STATUS_ERROR: "Server responded with error",
    }
    return messages.get(error, error.value)
