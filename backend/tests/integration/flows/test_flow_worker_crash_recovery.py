from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.flow_tables import FlowRunAuditOutbox
from eneo.flows.domain.flow_run_recovery_policy import (
    flow_stale_running_reconcile_after_seconds,
)
from eneo.flows.enums import FlowRunLifecycleSource
from tests.integration.flows.conftest import FlowBrokerWorkerSeam


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hard_exited_worker_redelivers_then_stale_recovery_converges(
    client,
    db_container,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    flow_broker_worker_seam: FlowBrokerWorkerSeam,
) -> None:
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
    )
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {
                "text": "This run must stop after the durable attempt checkpoint."
            },
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-crash-proof:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_run = create_response.json()
    assert created_run["status"] == "queued"
    run_id = created_run["id"]
    assert isinstance(run_id, str)

    queued_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/",
        headers=flow_process_auth_headers,
    )
    assert queued_response.status_code == 200, queued_response.text
    queued_run = queued_response.json()
    assert queued_run["status"] == "queued"
    assert queued_run["dispatch_attempt_count"] == 1
    assert queued_run["dispatch_last_attempt_at"] is not None
    assert queued_run["dispatched_at"] is not None
    assert queued_run["dispatch_next_attempt_at"] is not None

    await flow_broker_worker_seam.start_worker(crash_after_attempt_start_run_id=run_id)
    (
        running_run,
        running_statuses,
    ) = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="running",
        timeout_seconds=30,
    )
    evidence, task_id = await _wait_for_durable_attempt_checkpoint(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        worker=flow_broker_worker_seam,
        timeout_seconds=30,
    )
    assert evidence["run"]["result"] is None

    await flow_broker_worker_seam.wait_for_worker_child_exit(timeout_seconds=30)
    redelivery_result = await flow_broker_worker_seam.wait_for_task_result(
        task_id=task_id,
        timeout_seconds=30,
    )
    assert redelivery_result == {
        "status": "skipped",
        "reason": "run_running_or_revision_changed",
    }

    after_redelivery_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/",
        headers=flow_process_auth_headers,
    )
    assert after_redelivery_response.status_code == 200, after_redelivery_response.text
    after_redelivery = after_redelivery_response.json()
    assert after_redelivery["run"]["status"] == "running"
    assert after_redelivery["run"]["result"] is None
    assert len(after_redelivery["step_results"]) == 1
    assert after_redelivery["step_results"][0]["status"] == "running"
    assert len(after_redelivery["step_attempts"]) == 1
    assert after_redelivery["step_attempts"][0]["status"] == "started"
    assert after_redelivery["step_attempts"][0]["celery_task_id"] == task_id

    async with db_container() as container:
        pre_recovery_audit_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == UUID(run_id))
        )
    assert pre_recovery_audit_count == 0

    updated_at = running_run["updated_at"]
    assert isinstance(updated_at, str)
    await _wait_for_real_stale_threshold(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        run_updated_at=_parse_api_datetime(updated_at),
        worker=flow_broker_worker_seam,
    )

    first_recovery = await flow_broker_worker_seam.send_task_and_wait(
        task_name="flows.reconcile_running",
        timeout_seconds=30,
    )
    assert first_recovery == {"status": "ok", "reconciled": 1}

    (
        failed_run,
        failed_statuses,
    ) = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="failed",
        timeout_seconds=30,
    )
    assert failed_run["result"] is None
    assert failed_run["error"]["code"] == "flow_worker_stalled"

    second_recovery = await flow_broker_worker_seam.send_task_and_wait(
        task_name="flows.reconcile_running",
        timeout_seconds=30,
    )
    assert second_recovery == {"status": "ok", "reconciled": 0}

    final_evidence_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/",
        headers=flow_process_auth_headers,
    )
    assert final_evidence_response.status_code == 200, final_evidence_response.text
    final_evidence = final_evidence_response.json()
    assert final_evidence["run"]["status"] == "failed"
    assert final_evidence["run"]["result"] is None
    assert len(final_evidence["step_results"]) == 1
    assert final_evidence["step_results"][0]["status"] == "failed"
    assert final_evidence["step_results"][0]["output_payload_json"] is None
    assert len(final_evidence["step_attempts"]) == 1
    final_attempt = final_evidence["step_attempts"][0]
    assert final_attempt["status"] == "failed"
    assert final_attempt["celery_task_id"] == task_id
    assert final_attempt["finished_at"] is not None
    assert final_attempt["error_code"] == "flow_worker_stalled"

    observed_statuses = _deduplicate_adjacent(
        ["queued", *running_statuses, *failed_statuses]
    )
    assert observed_statuses == ["queued", "running", "failed"]
    assert "completed" not in observed_statuses

    async with db_container() as container:
        audit_rows = (
            await container.session().execute(
                sa.select(
                    FlowRunAuditOutbox.action,
                    FlowRunAuditOutbox.source,
                    FlowRunAuditOutbox.target_status,
                    FlowRunAuditOutbox.run_revision,
                ).where(FlowRunAuditOutbox.flow_run_id == UUID(run_id))
            )
        ).all()
    assert audit_rows == [
        (
            "flow_run_failed",
            FlowRunLifecycleSource.STALE_RUNNING_RECONCILER.value,
            "failed",
            failed_run["revision"],
        )
    ]


async def _wait_for_durable_attempt_checkpoint(
    *,
    client: AsyncClient,
    headers: Mapping[str, str],
    flow_id: str,
    run_id: str,
    worker: FlowBrokerWorkerSeam,
    timeout_seconds: float,
) -> tuple[dict[str, object], str]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        worker.assert_worker_alive()
        response = await client.get(
            f"/api/v1/flows/{flow_id}/runs/{run_id}/evidence/",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        evidence = response.json()
        step_results = evidence["step_results"]
        attempts = evidence["step_attempts"]
        if (
            evidence["run"]["status"] == "running"
            and len(step_results) == 1
            and step_results[0]["status"] == "running"
            and len(attempts) == 1
            and attempts[0]["status"] == "started"
        ):
            task_id = attempts[0]["celery_task_id"]
            assert isinstance(task_id, str)
            return evidence, task_id
        await asyncio.sleep(0.1)
    raise AssertionError(
        "Flow worker did not reach the committed attempt-start checkpoint. "
        f"Worker log tail:\n{worker.worker_log_tail()}"
    )


async def _wait_for_real_stale_threshold(
    *,
    client: AsyncClient,
    headers: Mapping[str, str],
    flow_id: str,
    run_id: str,
    run_updated_at: datetime,
    worker: FlowBrokerWorkerSeam,
) -> None:
    stale_after_seconds = flow_stale_running_reconcile_after_seconds(
        task_timeout_seconds=worker.task_timeout_seconds
    )
    eligible_at = run_updated_at + timedelta(seconds=stale_after_seconds + 1)
    timeout_seconds = (
        max(
            (eligible_at - datetime.now(timezone.utc)).total_seconds(),
            0,
        )
        + 10
    )
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        worker.assert_worker_alive()
        response = await client.get(
            f"/api/v1/flows/{flow_id}/runs/{run_id}/",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] == "running"
        if datetime.now(timezone.utc) >= eligible_at:
            return
        await asyncio.sleep(0.5)
    raise AssertionError("Flow run did not reach the real stale-recovery threshold.")


def _parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _deduplicate_adjacent(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result
