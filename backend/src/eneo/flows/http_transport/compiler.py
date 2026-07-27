from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    merge_resolved_input_edges,
)
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
from eneo.flows.variable_resolver import FlowVariableContext, FlowVariableInterpolation


class InterpolateWithEvidenceFn(Protocol):
    def __call__(
        self,
        template: str,
        context: FlowVariableContext,
        *,
        binding_ref: str,
    ) -> FlowVariableInterpolation: ...


@dataclass(frozen=True)
class EffectiveHttpRequest:
    """Compiled request ready for httpx."""

    method: HttpMethod
    url: str
    headers: dict[str, str]
    body: bytes | None
    json_body: dict[str, Any] | list[Any] | None
    timeout: float
    resolved_input_edges: tuple[FlowResolvedInputEdge, ...] = ()


def compile_http_config(
    authored: HttpAuthoredConfig,
    *,
    direction: str,
    method: HttpMethod,
    variables: dict[str, Any] | None = None,
    interpolate: Callable[[str, dict[str, Any]], str] | None = None,
    interpolate_with_evidence: InterpolateWithEvidenceFn | None = None,
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

    def _interpolate_evidenced(
        template: str, *, binding_ref: str
    ) -> FlowVariableInterpolation:
        if interpolate_with_evidence is not None:
            if not isinstance(ctx, FlowVariableContext):
                raise TypeError(
                    "Evidence interpolation requires a FlowVariableContext."
                )
            return interpolate_with_evidence(
                template,
                ctx,
                binding_ref=binding_ref,
            )
        return FlowVariableInterpolation(text=_interpolate(template), edges=())

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

    custom_header_edges: dict[str, tuple[FlowResolvedInputEdge, ...]] = {}
    for index, header in enumerate(authored.custom_headers):
        if header.secret:
            headers[header.name] = _interpolate(_secret_text(header.value))
            custom_header_edges.pop(header.name, None)
            continue
        interpolation = _interpolate_evidenced(
            _secret_text(header.value),
            binding_ref=f"http.custom_headers[{index}].value",
        )
        headers[header.name] = interpolation.text
        custom_header_edges[header.name] = interpolation.edges

    # URL interpolation
    url_interpolation = _interpolate_evidenced(
        authored.url,
        binding_ref="http.url",
    )

    # Body -> payload
    body_bytes, json_body, body_edges = _compile_body(
        authored,
        direction,
        _interpolate_evidenced,
    )

    return EffectiveHttpRequest(
        method=method,
        url=url_interpolation.text,
        headers=headers,
        body=body_bytes,
        json_body=json_body,
        timeout=float(authored.timeout_seconds),
        resolved_input_edges=merge_resolved_input_edges(
            url_interpolation.edges,
            *custom_header_edges.values(),
            body_edges,
        ),
    )


def _secret_text(value: SecretValue) -> str:
    if isinstance(value, str):
        return value
    return ""


def _compile_body(
    authored: HttpAuthoredConfig,
    direction: str,
    interpolate_fn: Callable[..., FlowVariableInterpolation],
) -> tuple[
    bytes | None,
    dict[str, Any] | list[Any] | None,
    tuple[FlowResolvedInputEdge, ...],
]:
    """Compile body mode into (raw_bytes, json_body)."""
    mode = authored.body.mode

    if mode == HttpBodyMode.NONE:
        return None, None, ()

    if mode == HttpBodyMode.AUTO:
        # AUTO leaves fallback body selection to the runtime caller.
        return None, None, ()

    if mode == HttpBodyMode.JSON_TEMPLATE:
        template = authored.body.template
        if template is None:
            return None, None, ()
        interpolation = interpolate_fn(template, binding_ref="http.body")
        rendered = interpolation.text
        try:
            parsed = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            return rendered.encode("utf-8"), None, interpolation.edges
        return None, parsed, interpolation.edges

    if mode == HttpBodyMode.TEXT_TEMPLATE:
        template = authored.body.template
        if template is None:
            return None, None, ()
        interpolation = interpolate_fn(template, binding_ref="http.body")
        return interpolation.text.encode("utf-8"), None, interpolation.edges

    return None, None, ()
