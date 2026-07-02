from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable

from eneo.flows.http_transport.authored_config import (
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBodyMode,
    HttpMethod,
    SecretValue,
)


@dataclass(frozen=True)
class EffectiveHttpRequest:
    """Compiled request ready for httpx."""

    method: HttpMethod
    url: str
    headers: dict[str, str]
    body: bytes | None
    json_body: dict[str, Any] | list[Any] | None
    timeout: float


def compile_http_config(
    authored: HttpAuthoredConfig,
    *,
    direction: str,
    method: HttpMethod,
    variables: dict[str, Any] | None = None,
    interpolate: Callable[[str, dict[str, Any]], str] | None = None,
) -> EffectiveHttpRequest:
    """Pure function. Compiles authored config into an effective request.

    Args:
        authored: The user-authored HTTP config.
        direction: "input" or "output".
        method: "GET" or "POST".
        variables: Variable context for template interpolation.
        interpolate: Function to interpolate ``{{ }}`` expressions in strings.

    Returns:
        An ``EffectiveHttpRequest`` ready for the HTTP client.
    """
    headers: dict[str, str] = {}
    ctx = variables or {}

    def _interpolate(template: str) -> str:
        if interpolate is not None:
            return interpolate(template, ctx)
        return template

    # Auth -> headers
    match authored.auth:
        case HttpAuthBearer(token=token):
            headers["Authorization"] = f"Bearer {_interpolate(_secret_text(token))}"
        case HttpAuthApiKey(header_name=name, key=key):
            headers[_interpolate(name)] = _interpolate(_secret_text(key))
        case HttpAuthBasicAuth(username=user, password=pwd):
            encoded = base64.b64encode(
                f"{_interpolate(user)}:{_interpolate(_secret_text(pwd))}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {encoded}"
        case HttpAuthNone():
            pass

    # Custom headers
    for h in authored.custom_headers:
        headers[h.name] = _interpolate(_secret_text(h.value))

    # URL interpolation
    url = _interpolate(authored.url)

    # Body -> payload
    body_bytes, json_body = _compile_body(authored, direction, ctx, _interpolate)

    return EffectiveHttpRequest(
        method=method,
        url=url,
        headers=headers,
        body=body_bytes,
        json_body=json_body,
        timeout=float(authored.timeout_seconds),
    )


def _secret_text(value: SecretValue) -> str:
    if isinstance(value, str):
        return value
    return ""


def _compile_body(
    authored: HttpAuthoredConfig,
    direction: str,
    ctx: dict[str, Any],
    interpolate_fn: Callable[[str], str],
) -> tuple[bytes | None, dict[str, Any] | list[Any] | None]:
    """Compile body mode into (raw_bytes, json_body)."""
    mode = authored.body.mode

    if mode == HttpBodyMode.NONE:
        return None, None

    if mode == HttpBodyMode.AUTO:
        # AUTO leaves fallback body selection to the runtime caller.
        return None, None

    if mode == HttpBodyMode.JSON_TEMPLATE:
        template = authored.body.template
        if template is None:
            return None, None
        rendered = interpolate_fn(template)
        try:
            parsed = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            return rendered.encode("utf-8"), None
        return None, parsed

    if mode == HttpBodyMode.TEXT_TEMPLATE:
        template = authored.body.template
        if template is None:
            return None, None
        rendered = interpolate_fn(template)
        return rendered.encode("utf-8"), None

    return None, None
