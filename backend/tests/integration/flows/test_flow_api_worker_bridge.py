from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from time import monotonic
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.flow_tables import FlowRunAuditOutbox
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.main.config import Settings
from tests.integration.flows.conftest import (
    FlowBrokerWorkerSeam,
    _flow_worker_environment,
)


def test_flow_process_environment_excludes_ambient_secrets(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    monkeypatch.setenv("PATH", "/test-bin")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-worker")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-worker")

    environment = _flow_worker_environment(
        settings=test_settings,
        queue_name="flows.process-proof",
    )

    assert environment["PATH"] == "/test-bin"
    assert environment["POSTGRES_PASSWORD"] == test_settings.postgres_password
    assert "OPENAI_API_KEY" not in environment
    assert "UNRELATED_SECRET" not in environment


@pytest.mark.asyncio
@pytest.mark.integration
async def test_public_flow_run_crosses_real_broker_and_worker(
    client,
    db_container,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    flow_broker_worker_seam,
) -> None:
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
    )
    await flow_broker_worker_seam.start_worker()

    submitted_text = "Deterministic public broker-to-worker result."
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": submitted_text},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-process-proof:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_run = create_response.json()
    assert created_run["status"] == "queued"
    run_id = created_run["id"]
    assert isinstance(run_id, str)

    (
        completed_run,
        observed_statuses,
    ) = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="completed",
        timeout_seconds=30,
    )
    assert observed_statuses[-1] == "completed"
    assert completed_run["result"] == {
        "kind": "inline_text",
        "text": submitted_text,
    }
    assert completed_run["dispatch_attempt_count"] == 1
    assert completed_run["dispatch_last_attempt_at"] is not None
    assert completed_run["dispatched_at"] is not None
    assert completed_run["dispatch_last_error"] is None
    assert completed_run["dispatch_next_attempt_at"] is None
    assert completed_run["dispatch_exhausted_at"] is None

    steps_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/steps/",
        headers=flow_process_auth_headers,
    )
    assert steps_response.status_code == 200, steps_response.text
    steps = steps_response.json()
    assert len(steps) == 1
    step = steps[0]
    assert step["step_id"] == flow.step_id
    assert step["status"] == "completed"
    assert step["current_attempt_no"] == 1
    assert step["output_payload_json"] == {"text": submitted_text}
    assert step["model_parameters_json"] == {"mode": "compose_text"}
    assert step["num_tokens_input"] == 0
    assert step["num_tokens_output"] == 0
    assert {diagnostic["code"] for diagnostic in step["diagnostics"]} >= {
        "compose_text_used"
    }

    evidence_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/",
        headers=flow_process_auth_headers,
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()
    assert evidence["run"]["status"] == "completed"
    assert evidence["run"]["result"] == {
        "kind": "inline_text",
        "text": submitted_text,
    }
    assert len(evidence["step_results"]) == 1
    assert evidence["step_results"][0]["output_payload_json"] == {
        "text": submitted_text
    }
    assert len(evidence["step_attempts"]) == 1
    attempt = evidence["step_attempts"][0]
    assert attempt["status"] == "completed"
    assert attempt["attempt_no"] == 1
    assert isinstance(attempt["celery_task_id"], str)
    assert attempt["finished_at"] is not None
    attempt_start = attempt["provenance_json"]["attempt_start"]
    assert attempt_start["input_text_length"] == len(submitted_text)
    assert attempt_start["requested_model"]
    assert attempt_start["provider"]

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
            "flow_run_completed",
            FlowRunLifecycleSource.EXECUTOR_COMPLETED.value,
            "completed",
            completed_run["revision"],
        )
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_broker_accepted_delivery_loss_recovers_through_public_redispatch(
    client: AsyncClient,
    db_container,
    flow_process_auth_headers: Mapping[str, str],
    create_published_compose_text_flow,
    flow_broker_worker_seam: FlowBrokerWorkerSeam,
) -> None:
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
    )
    submitted_text = "Broker-accepted delivery loss must remain recoverable."
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": submitted_text},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-delivery-loss-proof:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_run = create_response.json()
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
    assert queued_run["dispatched_at"] is not None
    assert queued_run["dispatch_next_attempt_at"] is not None

    await flow_broker_worker_seam.discard_single_queued_delivery()
    await _wait_until_public_dispatch_is_due(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        timeout_seconds=40,
    )

    redispatch_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/redispatch/",
        headers=flow_process_auth_headers,
    )
    assert redispatch_response.status_code == 200, redispatch_response.text
    redispatch_payload = redispatch_response.json()
    assert redispatch_payload["redispatched_count"] == 1
    redispatched_run = redispatch_payload["run"]
    assert redispatched_run["status"] == "queued"
    assert redispatched_run["dispatch_attempt_count"] == 2
    assert redispatched_run["dispatched_at"] is not None
    assert redispatched_run["dispatch_next_attempt_at"] is not None

    await flow_broker_worker_seam.start_worker()
    (
        completed_run,
        observed_statuses,
    ) = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="completed",
        timeout_seconds=30,
    )
    assert observed_statuses[-1] == "completed"
    assert completed_run["result"] == {
        "kind": "inline_text",
        "text": submitted_text,
    }
    assert completed_run["dispatch_attempt_count"] == 2
    assert completed_run["dispatch_next_attempt_at"] is None

    async with db_container() as container:
        terminal_audit_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.flow_run_id == UUID(run_id))
            .where(FlowRunAuditOutbox.action == "flow_run_completed")
        )
    assert terminal_audit_count == 1


async def _wait_until_public_dispatch_is_due(
    *,
    client: AsyncClient,
    headers: Mapping[str, str],
    flow_id: str,
    run_id: str,
    timeout_seconds: float,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        response = await client.get(
            f"/api/v1/flows/{flow_id}/runs/{run_id}/",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] == "queued"
        next_attempt_at = run["dispatch_next_attempt_at"]
        assert isinstance(next_attempt_at, str)
        if datetime.now(timezone.utc) >= _parse_api_datetime(next_attempt_at):
            return
        await asyncio.sleep(0.25)
    raise AssertionError("The queued Flow run did not reach its dispatch deadline.")


def _parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
