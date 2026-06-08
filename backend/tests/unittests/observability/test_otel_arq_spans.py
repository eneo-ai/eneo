"""Tests for ARQ job root-span creation (worker._traced_job).

Spec acceptance criterion this covers:
    "All log entries within a job are correlated via the job's own trace_id."

v1 decision: each ARQ job runs inside its own root span. We verify that
`_traced_job` opens a span around the job coroutine, names it by kind
("arq.job <name>" / "arq.cron <name>"), tags it with the job id when present,
and that code running inside the job sees that span as the active one (which
is what makes in-job log lines carry the matching trace_id).

These are unit tests: `_traced_job` is pure span plumbing and needs no DB or
Redis. We monkeypatch the module-level `_tracer` so spans land in an isolated
InMemorySpanExporter regardless of global TracerProvider state.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from intric.worker import worker as worker_module


@pytest.fixture
def captured_spans(monkeypatch):
    """Point worker._tracer at an isolated InMemorySpanExporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(worker_module, "_tracer", provider.get_tracer("test"))
    yield exporter
    exporter.clear()


@pytest.mark.asyncio
async def test_traced_job_creates_root_span_and_propagates_trace_id(captured_spans):
    """A queued job runs inside a root span named 'arq.job <name>', tagged with
    the job id, and the active trace_id inside the job matches the span."""
    seen_trace_id: list[str] = []

    async def fake_job(ctx, params):  # noqa: ARG001
        span_ctx = trace.get_current_span().get_span_context()
        seen_trace_id.append(format(span_ctx.trace_id, "032x"))
        return "done"

    traced = worker_module._traced_job("job", fake_job)
    job_id = UUID("12345678-1234-5678-1234-567812345678")

    result = await traced({"job_id": job_id}, params=None)

    assert result == "done"

    spans = captured_spans.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "arq.job fake_job"
    assert span.attributes["arq.job_name"] == "fake_job"
    assert span.attributes["arq.job_id"] == str(job_id)

    # The code running inside the job saw the span as active (so its log lines
    # would carry this trace_id).
    assert seen_trace_id == [format(span.get_span_context().trace_id, "032x")]


@pytest.mark.asyncio
async def test_traced_cron_uses_cron_kind_without_job_id(captured_spans):
    """A cron job is named 'arq.cron <name>'; cron job ids are non-UUID strings,
    so no arq.job_id attribute is set."""

    async def fake_cron(ctx):  # noqa: ARG001
        return None

    traced = worker_module._traced_job("cron", fake_cron)

    await traced({"job_id": "cron:fake_cron:1717000000"})

    spans = captured_spans.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "arq.cron fake_cron"
    assert span.attributes["arq.job_name"] == "fake_cron"
    assert "arq.job_id" not in span.attributes


@pytest.mark.asyncio
async def test_traced_job_records_exception(captured_spans):
    """If the job raises, the span still ends and records the error status."""

    async def failing_job(ctx, params):  # noqa: ARG001
        raise ValueError("boom")

    traced = worker_module._traced_job("job", failing_job)

    with pytest.raises(ValueError, match="boom"):
        await traced({"job_id": UUID("12345678-1234-5678-1234-567812345678")}, None)

    spans = captured_spans.get_finished_spans()
    assert len(spans) == 1
    # start_as_current_span sets ERROR status on unhandled exception by default
    assert spans[0].status.status_code.name == "ERROR"
