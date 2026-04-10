from __future__ import annotations

from typing import Any, cast

from intric.flows.http_transport.authored_config import (
    CustomHeader,
    HttpAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)


def is_authored_config(raw: dict[str, Any] | None) -> bool:
    """Check if config is in authored format (has ``auth`` key)."""
    return isinstance(raw, dict) and "auth" in raw


def normalize_legacy_config(raw: dict[str, Any]) -> HttpAuthoredConfig:
    """Convert legacy dict config to authored config shape.

    Called on read/runtime when the config lacks the ``auth`` field.
    Legacy format: ``{url, headers, timeout_seconds, body_template, body_json, response_format}``.
    """
    url = raw.get("url", "")
    if not isinstance(url, str):
        url = ""

    timeout = raw.get("timeout_seconds", 30)
    if not isinstance(timeout, (int, float)):
        timeout = 30

    headers_raw = raw.get("headers", {})
    headers = cast(dict[str, Any], headers_raw) if isinstance(headers_raw, dict) else {}

    auth = _infer_auth_from_headers(headers)
    custom_headers = _extract_non_auth_headers(headers)
    body = _infer_body_from_legacy(raw)

    response_format = raw.get("response_format")
    if response_format not in ("text", "json"):
        response_format = None

    return HttpAuthoredConfig(
        url=url,
        auth=auth,
        timeout_seconds=int(timeout),
        body=body,
        custom_headers=custom_headers,
        response_format=response_format,
    )


_AUTH_HEADER_NAMES = {"authorization"}


def _infer_auth_from_headers(headers: dict[str, Any]) -> HttpAuth:
    """Infer auth mode from legacy headers dict."""
    auth_value = None
    for key, value in headers.items():
        if key.lower() == "authorization" and isinstance(value, str):
            auth_value = value
            break

    if auth_value is None:
        return HttpAuthNone()

    if auth_value.lower().startswith("bearer "):
        token = auth_value[7:]  # len("Bearer ") == 7
        return HttpAuthBearer(token=token)

    # Can't reliably detect basic auth from encrypted headers, store as bearer fallback
    return HttpAuthBearer(token=auth_value)


def _extract_non_auth_headers(headers: dict[str, Any]) -> list[CustomHeader]:
    """Extract headers that are NOT auth-related."""
    result: list[CustomHeader] = []
    for key, value in headers.items():
        if key.lower() in _AUTH_HEADER_NAMES:
            continue
        str_value = value if isinstance(value, str) else str(value)
        result.append(CustomHeader(name=key, value=str_value, secret=True))
    return result


def _infer_body_from_legacy(raw: dict[str, Any]) -> HttpBody:
    """Infer body config from legacy dict format."""
    body_template = raw.get("body_template")
    body_json = raw.get("body_json")

    if isinstance(body_template, str) and body_template.strip():
        return HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template=body_template)

    if isinstance(body_json, (dict, list)):
        import json

        return HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template=json.dumps(body_json))

    return HttpBody(mode=HttpBodyMode.AUTO)
