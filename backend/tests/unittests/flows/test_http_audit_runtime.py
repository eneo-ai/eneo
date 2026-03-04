from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.flows.runtime.http_audit import HttpAuditDeps, audit_http_outbound


@dataclass
class _Run:
    id: str
    flow_id: str
    tenant_id: str


@dataclass
class _Step:
    step_order: int
    step_id: str
    user_description: str | None = None


@pytest.mark.asyncio
async def test_audit_http_outbound_logs_sanitized_metadata() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        user=SimpleNamespace(id="user-1"),
        logger=MagicMock(),
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=2, step_id="step-2", user_description="Webhook step")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://alice:secret@example.org/hook?token=abc",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.SUCCESS,
        status_code=204,
        duration_ms=123.456,
        deps=deps,
    )

    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL
    assert kwargs["entity_type"] == EntityType.FLOW_RUN
    extra = kwargs["metadata"]["extra"]
    assert extra["url_host"] == "https://example.org"
    assert extra["url_path"] == "/hook"
    assert extra["status_code"] == 204
    assert extra["duration_ms"] == 123.46
    assert extra["step_description"] == "Webhook step"
    assert kwargs["error_message"] is None


@pytest.mark.asyncio
async def test_audit_http_outbound_noop_without_service() -> None:
    deps = HttpAuditDeps(
        audit_service=None,
        user=SimpleNamespace(id="user-1"),
        logger=MagicMock(),
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=1, step_id="step-1")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/hook",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.FAILURE,
        deps=deps,
    )


@pytest.mark.asyncio
async def test_audit_http_outbound_never_breaks_flow_on_logger_failure() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock(side_effect=RuntimeError("audit down")))
    fake_logger = MagicMock()
    deps = HttpAuditDeps(
        audit_service=audit_service,
        user=SimpleNamespace(id="user-1"),
        logger=fake_logger,
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=9, step_id="step-9")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/hook",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.FAILURE,
        error_message="failed",
        deps=deps,
    )

    fake_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_audit_http_outbound_handles_url_without_hostname() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        user=SimpleNamespace(id="user-1"),
        logger=MagicMock(),
    )
    run = _Run(id="run-2", flow_id="flow-2", tenant_id="tenant-2")
    step = _Step(step_order=3, step_id="step-3")

    await audit_http_outbound(
        run=run,
        step=step,
        url="/relative/path?token=secret",
        method="GET",
        call_type="http_input",
        outcome=Outcome.FAILURE,
        error_message="network error",
        deps=deps,
    )

    kwargs = audit_service.log_async.await_args.kwargs
    extra = kwargs["metadata"]["extra"]
    assert extra["url_host"] == ""
    assert extra["url_path"] == "/relative/path"
    assert kwargs["error_message"] == "network error"


@pytest.mark.asyncio
async def test_audit_http_outbound_uses_step_label_when_description_missing() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        user=SimpleNamespace(id="user-1"),
        logger=MagicMock(),
    )
    run = _Run(id="run-3", flow_id="flow-3", tenant_id="tenant-3")
    step = _Step(step_order=7, step_id="step-7", user_description=None)

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/no-description",
        method="GET",
        call_type="http_input",
        outcome=Outcome.SUCCESS,
        duration_ms=None,
        deps=deps,
    )

    kwargs = audit_service.log_async.await_args.kwargs
    extra = kwargs["metadata"]["extra"]
    assert "step_description" not in extra
    assert "duration_ms" not in extra
