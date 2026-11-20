"""A run result carries every deliverable's file content, and an audit row
is committed before each send. The content is stored nowhere but its file."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eneo.audit.application.audit_service import AuditService
from eneo.database.database import SafeAsyncSession, sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRunStepResultFiles,
    FlowRunWebhookDeliveries,
    FlowStepResults,
)
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_protocol import PendingFileContent, PreparedFileUpload
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.run_outcome import finalize_run_from_current_results
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.exceptions import TypedIOValidationException
from tests.integration.flows.test_flow_run_result_delivery import RUN_RESULT_CONFIG
from tests.integration.flows.test_flow_webhook_outbox_delivery import (
    _create_running_webhook_run,
    _intent,
    _read,
    _read_one,
    _response,
    _run_outbox,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MARKER = "MARKER-run-result-7f3c"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CONTENT = f"PK\x03\x04 {MARKER} document body".encode()
_SENDING = "flow_run_result_sending"


async def _chunks(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


@pytest.fixture
def run_with_a_document(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    object_content_runtime_ready,
):
    """A completed run whose first step delivered a DOCX marked as a
    deliverable and whose last step sends the run result."""

    async def seed():
        async with db_container() as container:
            saved = await container.file_service(user=admin_user).save_prepared_file(
                PreparedFileUpload(
                    name="Startsidan.docx",
                    file_type=FileType.DOCUMENT,
                    display_media_type=DOCX,
                    contents=(
                        PendingFileContent(
                            variant=FileContentVariant.ORIGINAL,
                            chunks=_chunks(CONTENT),
                            declared_media_type=DOCX,
                            verified_media_type=DOCX,
                        ),
                    ),
                )
            )
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            flow, run, step = await _create_running_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config=RUN_RESULT_CONFIG,
                prior_output_payload={"text": "Dokumentet"},
                prior_step_output=(
                    "render_verbatim",
                    "docx",
                    {"deliverable": {"label": "Startsidan"}},
                ),
            )
            assert flow.id is not None and step.id is not None
            document_step = flow.steps[0]
            step_result_id = await session.scalar(
                sa.select(FlowStepResults.id).where(
                    FlowStepResults.flow_run_id == run.id,
                    FlowStepResults.step_id == document_step.id,
                )
            )
            session.add(
                FlowRunStepResultFiles(
                    flow_run_id=run.id,
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    step_result_id=step_result_id,
                    step_id=document_step.id,
                    step_order=1,
                    attempt_no=1,
                    file_id=saved.id,
                    ordinal=0,
                    source="declared_artifact",
                )
            )
            delivery_id = await FlowRunWebhookDeliveryRepository(
                session=session
            ).insert_pending_delivery(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                intent=_intent(run_id=run.id, step_id=step.id, step_order=2),
            )
            run_repo = FlowRunRepository(session=session)
            audit_outbox_repo = FlowRunAuditOutboxRepository(session=session)
            finalization = await finalize_run_from_current_results(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                flow_run_repo=run_repo,
                terminalizer=FlowRunTerminalizer(
                    run_repo,
                    audit_outbox_repo,
                    FlowRunReviewCheckpointRepository(
                        session=session, audit_outbox_repo=audit_outbox_repo
                    ),
                ),
            )
            assert finalization.payload == {"status": "completed"}
            await session.commit()
        return run, delivery_id, saved.id

    return seed


async def _sending_audits(run_id: UUID) -> list[sa.Row]:
    return await _read(
        sa.select(AuditLog.description, AuditLog.log_metadata).where(
            AuditLog.action == _SENDING, AuditLog.entity_id == run_id
        )
    )


async def test_the_result_carries_each_deliverable_file_and_is_audited_first(
    setup_database, run_with_a_document, monkeypatch, caplog
):
    run, delivery_id, file_id = await run_with_a_document()
    sent: list[dict[str, object]] = []

    async def _receive(_self, **kwargs):
        # The audit row is committed before anything leaves.
        sent.append({**kwargs, "audits": len(await _sending_audits(run.id))})
        return _response(503)

    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _receive)
    caplog.set_level(logging.DEBUG)

    outcome = await _run_outbox()

    assert outcome["attempted"] == 1
    [request] = sent
    assert request["audits"] == 1
    body = json.loads(request["body_bytes"])  # type: ignore[arg-type]
    [deliverable] = body["deliverables"]
    assert deliverable["label"] == "Startsidan"
    assert deliverable["output_type"] == "docx"
    [file] = deliverable["files"]
    assert file["file_id"] == str(file_id)
    assert base64.b64decode(file["content_base64"]) == CONTENT

    [audit] = await _sending_audits(run.id)
    assert audit.log_metadata["extra"]["delivery_id"] == str(delivery_id)
    assert audit.log_metadata["extra"]["file_ids"] == [str(file_id)]
    assert audit.log_metadata["extra"]["url_host"] == "receiver.example.org"
    assert audit.log_metadata["extra"]["delivery_attempt"] == 1

    # The content is in the request only: not in the delivery row, its error,
    # the step results, the audit trail or the logs.
    encoded = base64.b64encode(CONTENT).decode()
    stored = json.dumps(
        [
            [str(value) for value in row]
            for row in await _read(
                sa.select(FlowRunWebhookDeliveries).where(
                    FlowRunWebhookDeliveries.id == delivery_id
                )
            )
        ]
        + [
            [str(value) for value in row]
            for row in await _read(
                sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run.id)
            )
        ]
        + [
            [str(value) for value in row]
            for row in await _read(
                sa.select(AuditLog.description, AuditLog.log_metadata).where(
                    AuditLog.entity_id == run.id
                )
            )
        ]
    )
    for trace in (stored, caplog.text):
        assert MARKER not in trace
        assert encoded not in trace


async def test_without_the_audit_row_nothing_is_sent_and_it_is_tried_again(
    setup_database, run_with_a_document, monkeypatch
):
    run, delivery_id, _ = await run_with_a_document()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)
    monkeypatch.setattr(
        AuditService, "log", AsyncMock(side_effect=RuntimeError("audit down"))
    )

    await _run_outbox()

    send.assert_not_awaited()
    delivery = await _read_one(
        sa.select(FlowRunWebhookDeliveries.delivery_status).where(
            FlowRunWebhookDeliveries.id == delivery_id
        )
    )
    assert delivery.delivery_status == "pending"


async def test_files_over_the_cap_dead_letter_before_any_send(
    setup_database, run_with_a_document, monkeypatch
):
    run, delivery_id, file_id = await run_with_a_document()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)
    monkeypatch.setattr(
        "eneo.flows.runtime.run_result_body.RUN_RESULT_MAX_FILE_BYTES", 1
    )

    await _run_outbox()

    send.assert_not_awaited()
    delivery = await _read_one(
        sa.select(
            FlowRunWebhookDeliveries.delivery_status,
            FlowRunWebhookDeliveries.delivery_last_error,
        ).where(FlowRunWebhookDeliveries.id == delivery_id)
    )
    assert delivery.delivery_status == "dead_lettered"
    assert MARKER not in (delivery.delivery_last_error or "")
    assert await _sending_audits(run.id) == []


async def test_a_document_is_sent_with_a_pool_of_one_connection(
    setup_database, run_with_a_document, monkeypatch
):
    """The delivery's own transaction has ended before the file's bytes are
    read on a connection of their own, so one connection is enough."""
    run, delivery_id, _ = await run_with_a_document()
    engine = create_async_engine(
        sessionmanager._engine.url,  # type: ignore[union-attr]
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
    )
    monkeypatch.setattr(sessionmanager, "_engine", engine)
    monkeypatch.setattr(
        sessionmanager,
        "_sessionmaker",
        async_sessionmaker(
            autocommit=False, bind=engine, autobegin=False, class_=SafeAsyncSession
        ),
    )
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    try:
        outcome = await _run_outbox()
    finally:
        await engine.dispose()

    assert outcome["delivered"] == 1, outcome
    send.assert_awaited_once()


async def test_a_request_refused_when_it_is_compiled_is_never_audited_as_sent(
    setup_database, run_with_a_document, monkeypatch
):
    run, delivery_id, _ = await run_with_a_document()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    def _refuse(_self, *_args, **_kwargs):
        raise TypedIOValidationException(
            "Step 2: output_config.timeout_seconds cannot exceed 1.",
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        )

    monkeypatch.setattr(FlowHttpRuntimeHelper, "resolve_timeout_seconds", _refuse)

    outcome = await _run_outbox()

    assert outcome["dead_lettered"] == 1
    send.assert_not_awaited()
    assert await _sending_audits(run.id) == []
