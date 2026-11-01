"""A hard stop preserves results from delivery tasks that already finished.

The integration test covers the real deadline and database row lock. Here the
timeout fires only after a sibling task finishes, independently of DB latency.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.application.flow_webhook_delivery_policy import (
    FlowWebhookDeliveryBudget,
    FlowWebhookDeliveryDeadline,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.runtime import tasks as tasks_module
from eneo.flows.runtime.flow_webhook_delivery import (
    FlowRunWebhookDeliveryService,
    FlowWebhookDeliveryBatch,
    FlowWebhookDeliveryResult,
)


@pytest.mark.asyncio
async def test_a_hard_stop_counts_only_unfinished_deliveries_and_keeps_completed_results(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rows = [
        FlowRunWebhookDeliveryRow(
            id=uuid4(),
            tenant_id=uuid4(),
            flow_id=uuid4(),
            flow_run_id=uuid4(),
            step_id=uuid4(),
            step_order=1,
            attempt_no=1,
            idempotency_key="key",
            payload_ref="ref",
            delivery_attempts=1,
            claim_token=uuid4(),
            created_at=datetime.now(timezone.utc),
        )
        for _ in range(2)
    ]
    slow_row, completed_row = rows
    completed = asyncio.Event()
    delivery_tasks: dict[UUID, asyncio.Task[FlowWebhookDeliveryResult]] = {}
    hard_stop = asyncio.Timeout(None)
    timeout_at = Mock(return_value=hard_stop)
    # Replace only this module's timeout factory; TaskGroup and cancellation
    # are real, and other modules keep the original asyncio namespace.
    local_asyncio = SimpleNamespace(**vars(asyncio))
    local_asyncio.timeout_at = timeout_at
    monkeypatch.setattr(tasks_module, "asyncio", local_asyncio)

    async def deliver(
        *, row: FlowRunWebhookDeliveryRow, deadline: FlowWebhookDeliveryDeadline
    ) -> FlowWebhookDeliveryResult:
        task = asyncio.current_task()
        assert task is not None
        delivery_tasks[row.id] = task
        timeout_at.assert_called_once_with(deadline.hard_stop_at)
        if row.id == completed_row.id:
            # A callback runs after the actual delivery worker exits its
            # session, not merely after this service returns its result.
            task.add_done_callback(lambda _: completed.set())
            return FlowWebhookDeliveryResult(attempted_count=1, delivered_count=1)

        await completed.wait()
        assert delivery_tasks[completed_row.id].done()
        assert delivery_tasks[completed_row.id].result().delivered_count == 1
        hard_stop.reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()
        raise AssertionError("The unfinished delivery must be cancelled")

    service = create_autospec(FlowRunWebhookDeliveryService, instance=True)
    service.claim_due_batch.return_value = FlowWebhookDeliveryBatch(
        claimed_rows=rows, result=FlowWebhookDeliveryResult()
    )
    service.deliver_claimed.side_effect = deliver
    # Unbound sessions execute real context-manager cleanup without DB I/O.
    monkeypatch.setattr(tasks_module.sessionmanager, "session", AsyncSession)
    monkeypatch.setattr(
        tasks_module,
        "Container",
        Mock(
            return_value=SimpleNamespace(
                flow_run_webhook_delivery_service=lambda: service
            )
        ),
    )
    monkeypatch.setattr(tasks_module.logger, "disabled", False)
    monkeypatch.setattr(tasks_module.logger, "propagate", False)
    monkeypatch.setattr(tasks_module.logger, "handlers", [caplog.handler])
    budget = FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.2,
        preparation_margin_seconds=1.0,
        persistence_margin_seconds=0.3,
        finish_margin_seconds=0.3,
        cancel_margin_seconds=1.0,
        claim_window_seconds=0.1,
    )
    monkeypatch.setattr(tasks_module, "flow_webhook_delivery_budget", lambda: budget)

    # This outer limit only fails a hung test; it does not trigger the job's
    # hard stop or determine which sibling finishes first.
    async with asyncio.timeout(budget.job_timeout_seconds):
        result = await tasks_module.deliver_flow_webhook_outbox()

    assert result == {
        "status": "hard_stopped",
        "attempted": 1,
        "delivered": 1,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "released": 0,
        "unfinished": 1,
    }
    assert hard_stop.expired()
    assert not delivery_tasks[completed_row.id].cancelled()
    assert delivery_tasks[slow_row.id].cancelled()
    service.claim_due_batch.assert_awaited_once()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [
        (getattr(record, "delivery_id", None), getattr(record, "flow_run_id", None))
        for record in errors
    ] == [(str(slow_row.id), str(slow_row.flow_run_id)), (None, None)]
    assert getattr(errors[1], "unfinished", None) == 1
