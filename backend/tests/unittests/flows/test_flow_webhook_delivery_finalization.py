"""A recorded webhook delivery finalizes its run from the step statuses, and
reads a step output only when the run completes: the last completed one."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest

from eneo.flows.domain.flow import (
    FlowRunStatus,
    FlowStepResultAnnotation,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.runtime.flow_webhook_delivery import FlowRunWebhookDeliveryService


def _row() -> FlowRunWebhookDeliveryRow:
    return FlowRunWebhookDeliveryRow(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=2,
        attempt_no=1,
        idempotency_key="key",
        payload_ref="ref",
        delivery_attempts=1,
        claim_token=uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def _service(
    *statuses: FlowStepResultStatus,
) -> tuple[FlowRunWebhookDeliveryService, AsyncMock, AsyncMock]:
    flow_run_repo = create_autospec(FlowRunRepository, instance=True)
    flow_run_repo.save_step_result.side_effect = (
        lambda _run_id, result, **_kwargs: result
    )
    flow_run_repo.list_step_result_annotations.return_value = [
        FlowStepResultAnnotation(step_id=uuid4(), step_order=order, status=status)
        for order, status in enumerate(statuses, start=1)
    ]
    flow_run_repo.read_last_completed_output_payload.return_value = {
        "text": "delivered"
    }
    webhook_delivery_repo = AsyncMock()
    webhook_delivery_repo.mark_delivery_succeeded.return_value = True
    terminalizer = SimpleNamespace(
        terminalize_run=AsyncMock(
            side_effect=lambda **kwargs: SimpleNamespace(
                run=SimpleNamespace(status=kwargs["target_status"])
            )
        )
    )
    service = FlowRunWebhookDeliveryService(
        webhook_delivery_repo=webhook_delivery_repo,
        flow_repo=AsyncMock(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        flow_run_terminalizer=terminalizer,  # pyright: ignore[reportArgumentType]
        encryption_service=AsyncMock(),
        audit_service=None,
        user_repo=AsyncMock(),
        api_key_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        http_runtime=AsyncMock(),
    )
    return service, flow_run_repo, terminalizer.terminalize_run


@pytest.mark.asyncio
async def test_a_delivered_last_step_completes_the_run_with_the_last_output():
    service, flow_run_repo, terminalize_run = _service(
        FlowStepResultStatus.COMPLETED, FlowStepResultStatus.COMPLETED
    )
    row = _row()

    recorded = await service._record_success(  # pyright: ignore[reportPrivateUsage]
        row=row, payload=SimpleNamespace(step_result=SimpleNamespace())
    )

    assert recorded is True
    flow_run_repo.list_step_results.assert_not_awaited()
    flow_run_repo.list_step_result_annotations.assert_awaited_once_with(
        run_id=row.flow_run_id, tenant_id=row.tenant_id
    )
    flow_run_repo.read_last_completed_output_payload.assert_awaited_once_with(
        run_id=row.flow_run_id, tenant_id=row.tenant_id
    )
    kwargs = terminalize_run.await_args.kwargs
    assert kwargs["target_status"] == FlowRunStatus.COMPLETED
    assert kwargs["source"] == FlowRunLifecycleSource.EXECUTOR_COMPLETED
    assert kwargs["output_payload_json"] == {"text": "delivered"}


@pytest.mark.asyncio
async def test_a_delivery_in_a_cancelled_run_never_reads_a_step_output():
    service, flow_run_repo, terminalize_run = _service(
        FlowStepResultStatus.COMPLETED, FlowStepResultStatus.CANCELLED
    )

    recorded = await service._record_success(  # pyright: ignore[reportPrivateUsage]
        row=_row(), payload=SimpleNamespace(step_result=SimpleNamespace())
    )

    assert recorded is True
    flow_run_repo.list_step_results.assert_not_awaited()
    flow_run_repo.read_last_completed_output_payload.assert_not_awaited()
    kwargs = terminalize_run.await_args.kwargs
    assert kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert kwargs["error"].code == FlowApiErrorCode.RUN_CANCELLED.value
    assert kwargs["output_payload_json"] is None
