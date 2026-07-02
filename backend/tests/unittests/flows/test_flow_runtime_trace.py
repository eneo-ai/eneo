from __future__ import annotations

from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import eneo.flows.runtime.flow_runtime_trace as flow_runtime_trace
from eneo.flows.runtime.flow_runtime_trace import (
    FLOW_RUN_EXECUTE_SPAN_NAME,
    FLOW_RUN_SPAN_ATTRIBUTE_KEYS,
    FLOW_STEP_EXECUTE_SPAN_NAME,
    FLOW_STEP_SPAN_ATTRIBUTE_KEYS,
    trace_flow_run,
    trace_flow_step,
)


@pytest.fixture
def captured_flow_spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        flow_runtime_trace, "_tracer", provider.get_tracer("test.flows")
    )
    yield exporter
    exporter.clear()


def test_flow_run_span_records_allowed_attributes_and_result(captured_flow_spans):
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    run_trace_id = uuid4()

    with trace_flow_run(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        celery_task_id="task-1",
        retry_count=2,
    ) as span_context:
        span_context.set_run_trace_id(run_trace_id)
        span_context.set_result_from_mapping(
            {"status": "skipped", "reason": "run_terminal"}
        )

    span = captured_flow_spans.get_finished_spans()[0]
    attributes = span.attributes
    assert span.name == FLOW_RUN_EXECUTE_SPAN_NAME
    assert set(attributes) <= FLOW_RUN_SPAN_ATTRIBUTE_KEYS
    assert attributes["flow.run.id"] == str(run_id)
    assert attributes["flow.id"] == str(flow_id)
    assert attributes["flow.tenant.id"] == str(tenant_id)
    assert attributes["flow.run.trace_id"] == str(run_trace_id)
    assert attributes["flow.celery.task_id"] == "task-1"
    assert attributes["flow.celery.retry_count"] == 2
    assert attributes["flow.run.result.status"] == "skipped"
    assert attributes["flow.run.result.reason"] == "run_terminal"
    assert not any(
        blocked in key
        for key in attributes
        for blocked in ("prompt", "payload", "filename", "url", "user", "file.id")
    )


def test_flow_run_span_omits_unset_optional_attributes(captured_flow_spans):
    with trace_flow_run(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        celery_task_id=None,
        retry_count=0,
    ) as span_context:
        span_context.set_result_from_mapping({"status": "running"})

    attributes = captured_flow_spans.get_finished_spans()[0].attributes
    assert "flow.celery.task_id" not in attributes
    assert "flow.run.trace_id" not in attributes
    assert attributes["flow.run.result.status"] == "running"


def test_flow_run_span_records_actor_resolution_failure_token(captured_flow_spans):
    with trace_flow_run(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        celery_task_id="task-actor",
        retry_count=0,
    ) as span_context:
        span_context.set_result_from_mapping(
            {"status": "failed", "reason": "service_principal_disabled"}
        )

    attributes = captured_flow_spans.get_finished_spans()[0].attributes
    assert attributes["flow.run.result.status"] == "failed"
    assert attributes["flow.run.result.reason"] == "service_principal_disabled"


def test_flow_run_span_preserves_explicit_reason_when_exception_raises(
    captured_flow_spans,
):
    with pytest.raises(RuntimeError, match="tenant missing"):
        with trace_flow_run(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            celery_task_id="task-tenant",
            retry_count=0,
        ) as span_context:
            span_context.set_result(status="failed", reason="tenant_not_found")
            raise RuntimeError("tenant missing")

    attributes = captured_flow_spans.get_finished_spans()[0].attributes
    assert attributes["flow.run.result.status"] == "failed"
    assert attributes["flow.run.result.reason"] == "tenant_not_found"


def test_flow_run_span_records_step_claim_skip_token(captured_flow_spans):
    with trace_flow_run(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        celery_task_id="task-step",
        retry_count=0,
    ) as span_context:
        span_context.set_result_from_mapping(
            {"status": "skipped", "reason": "step_already_claimed"}
        )

    attributes = captured_flow_spans.get_finished_spans()[0].attributes
    assert attributes["flow.run.result.status"] == "skipped"
    assert attributes["flow.run.result.reason"] == "step_already_claimed"


def test_flow_run_span_falls_back_for_freeform_error(captured_flow_spans, caplog):
    raw_error = "flow failed while rendering private patient summary"

    with trace_flow_run(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        celery_task_id="task-2",
        retry_count=0,
    ) as span_context:
        span_context.set_result_from_mapping({"status": "failed", "error": raw_error})

    attributes = captured_flow_spans.get_finished_spans()[0].attributes
    assert attributes["flow.run.result.reason"] == "unclassified"
    assert raw_error not in attributes.values()
    assert "flow_runtime_span_unclassified_result_reason" in caplog.text


def test_flow_run_span_marks_unhandled_exception(captured_flow_spans):
    with pytest.raises(RuntimeError, match="boom"):
        with trace_flow_run(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            celery_task_id="task-3",
            retry_count=0,
        ):
            raise RuntimeError("boom")

    span = captured_flow_spans.get_finished_spans()[0]
    assert span.attributes["flow.run.result.status"] == "failed"
    assert span.attributes["flow.run.result.reason"] == "unhandled_exception"
    assert span.status.status_code.name == "ERROR"


def test_flow_step_span_records_allowed_attributes_and_result(captured_flow_spans):
    run_id = uuid4()
    run_trace_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()

    with trace_flow_step(
        run_id=run_id,
        run_trace_id=run_trace_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=3,
        attempt_no=2,
        input_type="text",
        output_type="json",
        output_mode="pass_through",
    ) as span_context:
        span_context.set_result(status="completed")

    span = captured_flow_spans.get_finished_spans()[0]
    attributes = span.attributes
    assert span.name == FLOW_STEP_EXECUTE_SPAN_NAME
    assert set(attributes) <= FLOW_STEP_SPAN_ATTRIBUTE_KEYS
    assert attributes["flow.run.id"] == str(run_id)
    assert attributes["flow.run.trace_id"] == str(run_trace_id)
    assert attributes["flow.id"] == str(flow_id)
    assert attributes["flow.tenant.id"] == str(tenant_id)
    assert attributes["flow.step.id"] == str(step_id)
    assert attributes["flow.step.order"] == 3
    assert attributes["flow.step.attempt_no"] == 2
    assert attributes["flow.step.input_type"] == "text"
    assert attributes["flow.step.output_type"] == "json"
    assert attributes["flow.step.output_mode"] == "pass_through"
    assert attributes["flow.step.result.status"] == "completed"
    assert not any(
        blocked in key
        for key in attributes
        for blocked in ("prompt", "payload", "filename", "url", "user", "file.id")
    )


def test_flow_step_span_marks_handler_exception(captured_flow_spans):
    with pytest.raises(RuntimeError, match="provider failed"):
        with trace_flow_step(
            run_id=uuid4(),
            run_trace_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            step_id=uuid4(),
            step_order=1,
            attempt_no=1,
            input_type="text",
            output_type="text",
            output_mode="pass_through",
        ):
            raise RuntimeError("provider failed")

    span = captured_flow_spans.get_finished_spans()[0]
    assert span.attributes["flow.step.result.status"] == "failed"
    assert span.status.status_code.name == "ERROR"
