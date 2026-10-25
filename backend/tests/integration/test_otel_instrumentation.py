"""Integration tests for OTEL auto-instrumentation.

A request hits the real FastAPI app (built via the `app` / `client` fixtures
in conftest.py with init_observability() and instrument_fastapi() wired in
production order). An InMemorySpanExporter attached to the app's
TracerProvider captures every span produced during the request. We then
assert:

  - A FastAPI server span exists (SpanKind.SERVER).
  - At least one auto-instrumented client span exists (SpanKind.CLIENT).
  - All spans share the same trace_id.

This proves correlated server/client spans, not SQLAlchemy statement tracing.
For this route the client span is SQLAlchemy's `connect` (one per connection
checkout); no statement spans are produced because the engine is created with
the `create_async_engine` imported before init_observability() patched it
(see docs/OBSERVABILITY.md, "SQLAlchemy spans").
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def captured_spans():
    """Capture spans from the app's already-initialised TracerProvider.

    init_observability() sets the global TracerProvider once at import, and
    OpenTelemetry's set_tracer_provider is set-once (a second set is ignored).
    The auto-instrumentors resolve trace.get_tracer() to that global provider,
    so we attach an InMemorySpanExporter to it rather than trying to replace it.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield exporter
    finally:
        exporter.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_produces_correlated_server_and_client_spans(
    client, admin_user_api_key, captured_spans
):
    """An authenticated request must produce a FastAPI server span and at least
    one auto-instrumented client span, all sharing the same trace_id."""
    response = await client.get(
        "/api/v1/users/me/", headers={"X-API-Key": admin_user_api_key.key}
    )
    assert response.status_code == 200

    spans = captured_spans.get_finished_spans()
    assert spans, "No spans captured during the request"

    server_spans = [s for s in spans if s.kind.name == "SERVER"]
    assert server_spans, (
        f"No FastAPI server span captured; got names: {[s.name for s in spans]}"
    )

    client_spans = [s for s in spans if s.kind.name == "CLIENT"]
    assert client_spans, (
        f"No auto-instrumented client spans captured (SQLAlchemy connect / "
        f"Redis / HTTP). Got names: {[s.name for s in spans]}"
    )

    trace_ids = {s.get_span_context().trace_id for s in spans}
    assert len(trace_ids) == 1, (
        f"Spans span multiple traces, expected one: "
        f"{[(s.name, format(s.get_span_context().trace_id, '032x')) for s in spans]}"
    )
