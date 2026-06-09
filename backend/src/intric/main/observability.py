"""OpenTelemetry observability init for API server and worker.

Provides a shared, idempotent init function that sets up:
- TracerProvider with W3C TraceContext propagation (no exporters in v1)
- Auto-instrumentation for FastAPI, SQLAlchemy, Redis, httpx, aiohttp-client
- Redaction of sensitive query parameters from span attributes

Must be called before SQLAlchemy engines, Redis pools, and aiohttp sessions
are created for auto-instrumentation to take effect.

ARQ worker jobs start their own root traces (v1 decision):
ARQ has no built-in metadata envelope separate from job kwargs, so injecting
traceparent into job data would mix trace context with domain parameters.
Worker jobs therefore create independent root traces; request-to-job propagation
is planned for v2 when a clean metadata mechanism is available.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode

from opentelemetry import trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

if TYPE_CHECKING:
    pass

_initialized = False

# Query parameter names that contain credentials or tokens and must be redacted
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)^(code|state|token|access_token|refresh_token|client_secret"
    r"|[a-z0-9_]*token[a-z0-9_]*|[a-z0-9_]*secret[a-z0-9_]*)$"
)

# HTTP header names that must never appear in span attributes
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie"})


def redact_url_query(url: str) -> str:
    """Replace sensitive query parameter values with [REDACTED].

    Used by the server_request_hook to scrub spans before they are recorded.
    Exported so tests can verify redaction logic directly.
    """
    if "?" not in url:
        return url
    base, query = url.split("?", 1)
    params = parse_qsl(query, keep_blank_values=True)
    redacted = [
        (k, "[REDACTED]" if _SENSITIVE_PARAM_RE.match(k) else v) for k, v in params
    ]
    # safe="[]" keeps the [REDACTED] sentinel human-readable; without it
    # urlencode percent-encodes the brackets to %5B...%5D.
    return base + "?" + urlencode(redacted, safe="[]")


def _redact_span_url_attrs(span: Any) -> None:
    """Redact sensitive query params from all URL-bearing span attributes."""
    if not span or not span.is_recording():
        return
    attributes: dict[str, Any] = span.attributes or {}
    for attr_key in ("url.full", "http.url", "http.target"):
        val = attributes.get(attr_key)
        if val and isinstance(val, str) and "?" in val:
            span.set_attribute(attr_key, redact_url_query(val))


def _server_request_hook(span: Any, scope: dict[str, Any]) -> None:
    """OTEL FastAPI server_request_hook: redact sensitive span attributes."""
    if not span or not span.is_recording():
        return

    # Redact sensitive query parameters from URL attributes already set
    _redact_span_url_attrs(span)

    # Also redact from the raw ASGI query string (sets url.query attribute)
    query_bytes = scope.get("query_string", b"")
    if query_bytes:
        if isinstance(query_bytes, bytes):
            query_str = query_bytes.decode("utf-8", errors="replace")
        else:
            query_str = str(query_bytes)

        params = parse_qsl(query_str, keep_blank_values=True)
        if any(_SENSITIVE_PARAM_RE.match(k) for k, _ in params):
            redacted = [
                (k, "[REDACTED]" if _SENSITIVE_PARAM_RE.match(k) else v)
                for k, v in params
            ]
            span.set_attribute("url.query", urlencode(redacted, safe="[]"))

    # Redact any sensitive header attributes that the instrumentation may have set
    header_attrs: dict[str, Any] = span.attributes or {}
    for attr_key in list(header_attrs.keys()):
        if any(h in attr_key.lower() for h in _SENSITIVE_HEADERS):
            span.set_attribute(attr_key, "[REDACTED]")


def _httpx_request_hook(span: Any, request: Any) -> None:  # noqa: ARG001
    """Redact sensitive URL query params from outgoing httpx client spans."""
    _redact_span_url_attrs(span)


def _aiohttp_request_hook(span: Any, params: Any) -> None:  # noqa: ARG001
    """Redact sensitive URL query params from outgoing aiohttp client spans."""
    _redact_span_url_attrs(span)


def init_observability() -> None:
    """Set up OTEL TracerProvider, propagators, and auto-instrumentation.

    Idempotent — safe to call multiple times; subsequent calls are no-ops.
    Call before SQLAlchemy engines, Redis pools, and aiohttp sessions are
    created so that auto-instrumentation captures those integrations.
    """
    global _initialized
    if _initialized:
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "eneo")
    service_version = os.getenv("OTEL_SERVICE_VERSION", "unknown")
    deployment_env = os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "production")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            # OTel semantic conventions ≥1.24: deployment.environment.name
            # Configured via OTEL_DEPLOYMENT_ENVIRONMENT env var.
            "deployment.environment.name": deployment_env,
        }
    )

    # Real TracerProvider — generates trace/span IDs for every request.
    # No exporters in v1: spans are not shipped to a trace backend.
    # InMemorySpanExporter is used in tests to verify instrumentation.
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # W3C TraceContext propagation (traceparent / tracestate headers)
    set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )

    # Global auto-instrumentation — must run before engines/pools are created
    from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import (  # pyright: ignore[reportMissingTypeStubs]  # opentelemetry-instrumentation-sqlalchemy ships without type stubs
        SQLAlchemyInstrumentor,
    )

    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()  # pyright: ignore[reportUnknownMemberType]  # opentelemetry-instrumentation-redis instrument() is untyped
    HTTPXClientInstrumentor().instrument(request_hook=_httpx_request_hook)
    AioHttpClientInstrumentor().instrument(request_hook=_aiohttp_request_hook)

    _initialized = True


def instrument_fastapi(app: Any) -> None:
    """Instrument a specific FastAPI app instance.

    Must be called after init_observability() and after the FastAPI app is
    created. Adds the OTEL middleware and wires the redaction hook.
    """
    from opentelemetry.instrumentation.fastapi import (  # pyright: ignore[reportMissingTypeStubs]  # opentelemetry-instrumentation-fastapi ships without type stubs
        FastAPIInstrumentor,
    )

    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=_server_request_hook,
        excluded_urls=r"/api/healthz.*",
    )
