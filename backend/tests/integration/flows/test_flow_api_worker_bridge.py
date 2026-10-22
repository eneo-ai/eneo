from __future__ import annotations

import hashlib
import io
import os
import zipfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
)
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
    assert isinstance(attempt["dispatch_task_id"], str)
    assert attempt["finished_at"] is not None
    # A compose-text step calls no completion model, so its attempt names none.
    assert attempt["requested_model"] is None
    assert attempt["provider"] is None
    assert attempt["provenance_json"] is None

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
async def test_broker_accepted_delivery_executes_after_dispatch_budget_exhaustion(
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
    submitted_text = "A delayed accepted delivery remains claimable after exhaustion."
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": submitted_text},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-delayed-delivery-proof:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]
    assert isinstance(run_id, str)

    exhausted_at = datetime.now(timezone.utc)
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run_id))
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS,
                dispatch_next_attempt_at=None,
                dispatch_exhausted_at=exhausted_at,
            )
        )
        await container.session().commit()

    exhausted_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/",
        headers=flow_process_auth_headers,
    )
    assert exhausted_response.status_code == 200, exhausted_response.text
    exhausted_run = exhausted_response.json()
    assert exhausted_run["status"] == "queued"
    assert exhausted_run["dispatch_exhausted_at"] is not None

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
    assert completed_run["dispatch_attempt_count"] == FLOW_DISPATCH_MAX_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_broker_accepted_delivery_loss_recovers_through_scheduled_redispatch(
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
    last_attempt_at = datetime.now(timezone.utc) - timedelta(
        seconds=FLOW_QUEUED_REDISPATCH_AFTER_SECONDS
    )
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run_id))
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS - 1,
                dispatch_last_attempt_at=last_attempt_at,
                dispatch_next_attempt_at=last_attempt_at
                + timedelta(seconds=FLOW_QUEUED_REDISPATCH_AFTER_SECONDS),
            )
        )
        await container.session().commit()

    await flow_broker_worker_seam.start_worker()
    redispatch_result = await flow_broker_worker_seam.send_task_and_wait(
        task_name="flows.redispatch_stale_queued",
        timeout_seconds=30,
    )
    assert redispatch_result == {"status": "ok", "redispatched": 1}

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
    assert completed_run["dispatch_attempt_count"] == FLOW_DISPATCH_MAX_ATTEMPTS
    assert completed_run["dispatch_next_attempt_at"] is None

    second_redispatch_result = await flow_broker_worker_seam.send_task_and_wait(
        task_name="flows.redispatch_stale_queued",
        timeout_seconds=30,
    )
    assert second_redispatch_result == {"status": "ok", "redispatched": 0}

    evidence_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/",
        headers=flow_process_auth_headers,
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()
    assert len(evidence["step_attempts"]) == 1
    assert evidence["step_attempts"][0]["status"] == "completed"

    async with db_container() as container:
        terminal_audit_rows = (
            await container.session().execute(
                sa.select(
                    FlowRunAuditOutbox.action,
                    FlowRunAuditOutbox.target_status,
                ).where(FlowRunAuditOutbox.flow_run_id == UUID(run_id))
            )
        ).all()
    assert terminal_audit_rows == [("flow_run_completed", "completed")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_generated_pdf_downloads_under_the_flow_name_and_run_day(
    client,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    flow_broker_worker_seam,
) -> None:
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
        name="Nämndmöte: protokoll",
        output_mode="render_verbatim",
        output_type="pdf",
    )
    await flow_broker_worker_seam.start_worker()
    # Text that already is a PDF is stored as it is, so no renderer is needed.
    pdf_text = "%PDF-1.4\n%%EOF"
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": pdf_text},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-file-name-proof:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]

    completed_run, _ = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="completed",
        timeout_seconds=30,
    )

    run_day = (
        datetime.fromisoformat(str(completed_run["created_at"]))
        .astimezone(timezone.utc)
        .date()
        .isoformat()
    )
    result = completed_run["result"]
    assert isinstance(result, dict)
    assert result["kind"] == "artifact"
    [artifact] = result["files"]
    assert artifact["name"] == f"Nämndmöte protokoll {run_day}.pdf"

    signed_url_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}"
        f"/artifacts/{artifact['file_id']}/signed-url/",
        json={"expires_in": 60, "content_disposition": "attachment"},
        headers=flow_process_auth_headers,
    )
    assert signed_url_response.status_code == 200, signed_url_response.text
    download_response = await client.get(signed_url_response.json()["url"])
    assert download_response.status_code == 200, download_response.text
    assert download_response.content == pdf_text.encode("latin-1")
    assert download_response.headers["content-disposition"] == (
        f'attachment; filename="Namndmote protokoll {run_day}.pdf"; '
        f"filename*=UTF-8''N%C3%A4mndm%C3%B6te%20protokoll%20{run_day}.pdf"
    )


# The runtime lays out PDFs with its WeasyPrint sidecar; CI installs it, a
# developer machine may not.
_PDF_SIDECAR_INSTALLED = Path(
    os.environ.get("PDF_PYTHON", "/opt/pdf/bin/python3")
).exists()


@pytest.mark.parametrize(
    "output_type",
    [
        "docx",
        pytest.param(
            "pdf",
            marks=pytest.mark.skipif(
                not _PDF_SIDECAR_INSTALLED,
                reason="The tool runtime's PDF sidecar is not installed here.",
            ),
        ),
    ],
)
async def test_a_rendered_document_is_stored_recorded_and_served_by_a_signed_link(
    client,
    db_container,
    flow_process_auth_headers,
    create_published_compose_text_flow,
    flow_broker_worker_seam,
    output_type: str,
) -> None:
    # The worker renders the step's text in the shared tool runtime (a real
    # process, not a stand-in) and stores the document as the step's declared
    # artifact. The run's result is the stored bytes, served only through a
    # signed link that names the producing run's file.
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
        name="Beslutsunderlag",
        output_mode="render_verbatim",
        output_type=output_type,
    )
    await flow_broker_worker_seam.start_worker()
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {
                "text": "# Beslut\n\nNämnden godkänner förslaget om ny bibliotekslokal."
            },
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-rendered-document:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]

    completed_run, _ = await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="completed",
        timeout_seconds=60,
    )
    result = completed_run["result"]
    assert isinstance(result, dict) and result["kind"] == "artifact"
    [artifact] = result["files"]
    assert artifact["source"] == "declared_artifact"
    assert artifact["step_id"] == flow.step_id
    assert artifact["attempt_no"] == 1
    assert artifact["name"].endswith(f".{output_type}")

    unsigned = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}"
        f"/artifacts/{artifact['file_id']}/signed-url/",
    )
    assert unsigned.status_code in {401, 403, 405}
    signed_url_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}"
        f"/artifacts/{artifact['file_id']}/signed-url/",
        json={"expires_in": 60, "content_disposition": "attachment"},
        headers=flow_process_auth_headers,
    )
    assert signed_url_response.status_code == 200, signed_url_response.text
    signed_url = signed_url_response.json()["url"]
    download = await client.get(signed_url)
    assert download.status_code == 200, download.text
    content = download.content
    assert len(content) == artifact["size"]
    assert artifact["checksum"].removeprefix("sha256:") == (
        hashlib.sha256(content).hexdigest()
    )
    if output_type == "pdf":
        assert content.startswith(b"%PDF-")
        assert artifact["mimetype"] == "application/pdf"
    else:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            body = document.read("word/document.xml").decode("utf-8")
        assert "godkänner förslaget" in body
        assert artifact["mimetype"] == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    tampered = await client.get(signed_url.replace("token=", "token=x", 1))
    assert tampered.status_code != 200
    # The run holds the classification level its evidence, the document
    # among it, was produced at: nothing in this space is classified.
    async with db_container() as container:
        recorded_level = await container.session().scalar(
            sa.select(FlowRuns.evidence_classification_level).where(
                FlowRuns.id == UUID(run_id)
            )
        )
    assert recorded_level == 0


async def test_a_run_cancelled_while_queued_starts_no_step_when_its_delivery_arrives(
    client: AsyncClient,
    db_container,
    flow_process_auth_headers: Mapping[str, str],
    create_published_compose_text_flow,
    flow_broker_worker_seam: FlowBrokerWorkerSeam,
) -> None:
    # The run is cancelled while its delivery waits on the queue. The worker
    # that takes the delivery afterwards starts no step: the run stays
    # cancelled, with no attempt and one terminal audit record.
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
    )
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": "Avbryts innan den startar."},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-queued-cancel:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]
    [queued_job] = await flow_broker_worker_seam.broker_client.zrange(
        flow_broker_worker_seam.queue_name, 0, -1
    )
    task_id = queued_job.decode() if isinstance(queued_job, bytes) else queued_job

    cancel_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/cancel/",
        headers=flow_process_auth_headers,
    )
    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json()["status"] == "cancelled"

    await flow_broker_worker_seam.start_worker()
    task_result = await flow_broker_worker_seam.wait_for_task_result(
        task_id=task_id, timeout_seconds=30
    )
    assert task_result["status"] == "skipped"
    assert str(task_result["reason"]).startswith("run_cancelled")

    evidence_response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/evidence/",
        headers=flow_process_auth_headers,
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()
    assert evidence["run"]["status"] == "cancelled"
    assert evidence["run"]["result"] is None
    assert evidence["step_attempts"] == []
    assert all(
        result["output_payload_json"] is None for result in evidence["step_results"]
    )
    async with db_container() as container:
        audit_rows = (
            await container.session().execute(
                sa.select(
                    FlowRunAuditOutbox.action,
                    FlowRunAuditOutbox.target_status,
                ).where(FlowRunAuditOutbox.flow_run_id == UUID(run_id))
            )
        ).all()
    assert audit_rows == [("flow_run_cancelled", "cancelled")]


@pytest.mark.parametrize("decision", ["edit_and_continue", "reject", "expire"])
async def test_a_review_decided_after_a_worker_restart_ends_the_run_it_paused(
    client: AsyncClient,
    db_container,
    flow_process_auth_headers: Mapping[str, str],
    create_published_compose_text_flow,
    flow_broker_worker_seam: FlowBrokerWorkerSeam,
    decision: str,
) -> None:
    # The run pauses for review in one worker process, and the decision is
    # taken after that worker is gone and another has started. An edited
    # approval continues the run in the new worker with the reviewer's text
    # and without running the step again; a rejection cancels the run, and so
    # does the maintenance worker's expiry job once the review has expired.
    flow = await create_published_compose_text_flow(
        client,
        flow_process_auth_headers,
        review_policy={"mode": "edit"},
    )
    await flow_broker_worker_seam.start_worker()
    create_response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={
            "expected_flow_version": flow.published_version,
            "input_payload_json": {"text": "Utkast till beslut."},
        },
        headers={
            **flow_process_auth_headers,
            "Idempotency-Key": f"flow-review-restart:{uuid4().hex}",
        },
    )
    assert create_response.status_code == 201, create_response.text
    run_id = create_response.json()["id"]
    run_path = f"/api/v1/flows/{flow.flow_id}/runs/{run_id}"
    await flow_broker_worker_seam.wait_for_public_run_status(
        client=client,
        headers=flow_process_auth_headers,
        flow_id=flow.flow_id,
        run_id=run_id,
        expected_status="awaiting_review",
        timeout_seconds=30,
    )

    await flow_broker_worker_seam.close()
    await flow_broker_worker_seam.start_worker()

    active_response = await client.get(
        f"{run_path}/review-checkpoints/active/",
        headers=flow_process_auth_headers,
    )
    assert active_response.status_code == 200, active_response.text
    checkpoint = active_response.json()
    checkpoint_path = f"{run_path}/review-checkpoints/{checkpoint['id']}"
    if decision == "expire":
        async with db_container() as container:
            await container.session().execute(
                sa.update(FlowRunReviewCheckpoints)
                .where(FlowRunReviewCheckpoints.id == UUID(checkpoint["id"]))
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await container.session().commit()
        expiry = await flow_broker_worker_seam.send_task_and_wait(
            task_name="flows.reconcile_review_expiry",
            timeout_seconds=30,
        )
        assert expiry == {"status": "ok", "reconciled": 1}
        ended, _ = await flow_broker_worker_seam.wait_for_public_run_status(
            client=client,
            headers=flow_process_auth_headers,
            flow_id=flow.flow_id,
            run_id=run_id,
            expected_status="cancelled",
            timeout_seconds=30,
        )
        assert ended["result"] is None
        assert ended["error"]["code"] == "flow_review_expired"
    elif decision == "reject":
        reject_response = await client.post(
            f"{checkpoint_path}/reject/",
            json={
                "expected_checkpoint_revision": checkpoint["revision"],
                "reason": "Underlaget saknar beslutsdatum.",
            },
            headers=flow_process_auth_headers,
        )
        assert reject_response.status_code == 200, reject_response.text
        ended, _ = await flow_broker_worker_seam.wait_for_public_run_status(
            client=client,
            headers=flow_process_auth_headers,
            flow_id=flow.flow_id,
            run_id=run_id,
            expected_status="cancelled",
            timeout_seconds=30,
        )
        assert ended["result"] is None
        assert ended["error"]["code"] == "flow_review_rejected"
    else:
        edit_response = await client.patch(
            f"{checkpoint_path}/",
            json={
                "expected_checkpoint_revision": checkpoint["revision"],
                "edited_value": "Granskat beslut.",
            },
            headers=flow_process_auth_headers,
        )
        assert edit_response.status_code == 200, edit_response.text
        continue_response = await client.post(
            f"{checkpoint_path}/approve-and-continue/",
            json={"expected_checkpoint_revision": edit_response.json()["revision"]},
            headers={
                **flow_process_auth_headers,
                "Idempotency-Key": f"flow-review-continue:{uuid4().hex}",
            },
        )
        assert continue_response.status_code == 202, continue_response.text
        ended, _ = await flow_broker_worker_seam.wait_for_public_run_status(
            client=client,
            headers=flow_process_auth_headers,
            flow_id=flow.flow_id,
            run_id=run_id,
            expected_status="completed",
            timeout_seconds=30,
        )
        assert ended["result"] == {"kind": "inline_text", "text": "Granskat beslut."}

    evidence_response = await client.get(
        f"{run_path}/evidence/", headers=flow_process_auth_headers
    )
    assert evidence_response.status_code == 200, evidence_response.text
    [attempt] = evidence_response.json()["step_attempts"]
    assert attempt["attempt_no"] == 1
    assert attempt["status"] == "completed"
