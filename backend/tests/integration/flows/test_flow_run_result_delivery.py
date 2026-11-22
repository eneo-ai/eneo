"""A run's result sent to a receiver after the run has completed.

An ``http_post`` step whose body mode is ``run_result`` completes the run in
the same transaction that stores its delivery row, and the outbox sends the
result afterwards. The delivery's outcome never changes the run."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunStepResultFiles,
    FlowRunWebhookDeliveries,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_run_contract_models import FlowRunOutboundHttpResultPublic
from eneo.flows.api.flow_run_response import read_run_public
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_MAX_ATTEMPTS,
)
from eneo.flows.domain.flow import FlowRunStatus
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
from eneo.flows.runtime import executor as executor_module
from eneo.flows.runtime import tasks as tasks_module
from eneo.flows.runtime.executor import FlowRunExecutor
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.run_outcome import (
    RunFinalizationResult,
    finalize_run_from_current_results,
)
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from tests.integration.flows.test_flow_webhook_outbox_delivery import (
    _create_queued_webhook_run,
    _create_running_webhook_run,
    _intent,
    _read,
    _read_one,
    _read_scalar,
    _response,
    _run_outbox,
    seed_delivery,  # noqa: F401  (fixture)
)

RUN_RESULT_CONFIG: dict[str, object] = {
    "url": "https://receiver.example.org/eneo/results",
    "auth": {"mode": "none"},
    "timeout_seconds": 5,
    "body": {"mode": "run_result"},
    # Headers may still read run data; only the address may not.
    "custom_headers": [
        {"name": "X-Case", "value": "{{ flow_input.case_id }}", "secret": False}
    ],
}


# The step before the POST step marks its text as one of the run's
# deliverables, so the run has a result to send.
MARKED_TEXT: tuple[str, str, dict[str, object] | None] = (
    "pass_through",
    "text",
    {"deliverable": {"label": "Svar"}},
)


async def _run_state(run_id: UUID) -> tuple[str, list[str]]:
    run_status = await _read_scalar(
        sa.select(FlowRuns.status).where(FlowRuns.id == run_id)
    )
    rows = await _read(
        sa.select(FlowRunWebhookDeliveries.delivery_status).where(
            FlowRunWebhookDeliveries.flow_run_id == run_id
        )
    )
    return run_status, [row.delivery_status for row in rows]


async def _execute(run) -> dict[str, str]:
    try:
        return await tasks_module.execute_flow_run_task(
            run_id=str(run.id),
            flow_id=str(run.flow_id),
            tenant_id=str(run.tenant_id),
            run_revision=run.revision,
            principal_type=PrincipalType.USER.value,
            principal_user_id=str(run.principal_user_id),
            task_id=None,
            retry_count=0,
        )
    finally:
        await tasks_module.execution_heartbeats().stop()


@pytest.fixture
def queued_run_result_run(
    admin_user, completion_model_factory, space_factory, assistant_factory
):
    async def create(
        *,
        include_prior_step: bool = True,
        webhook_question: str | None = "{{flow.input.question}}",
    ):
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            _, run, _ = await _create_queued_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config=RUN_RESULT_CONFIG,
                include_prior_step=include_prior_step,
                prior_step_output=MARKED_TEXT,
                webhook_question=webhook_question,
            )
            await session.commit()
        return run

    return create


@pytest.fixture
def completed_run_result_run(
    admin_user, completion_model_factory, space_factory, assistant_factory
):
    """A completed run whose run_result delivery is due, committed together
    as the executor commits them."""

    async def seed():
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            flow, run, step = await _create_running_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config=RUN_RESULT_CONFIG,
                prior_output_payload={"text": "Svar"},
                prior_step_output=MARKED_TEXT,
            )
            assert flow.id is not None and step.id is not None
            delivery_id = await FlowRunWebhookDeliveryRepository(
                session=session
            ).insert_pending_delivery(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                intent=_intent(
                    run_id=run.id, step_id=step.id, step_order=step.step_order
                ),
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
        return run, delivery_id

    return seed


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_run_result_run_completes_before_its_result_is_sent(
    setup_database,
    object_content_runtime_ready,
    queued_run_result_run,
    monkeypatch,
):
    """The run is completed and its delivery row stored in one commit. The
    wake-up after that commit is lost here; the outbox still sends the
    result, to a completed run."""
    run = await queued_run_result_run()

    async def _answer(_self, **_kwargs):
        return SimpleNamespace(completion="# Möte\n\nKlart.", total_token_count=1)

    lost_wakeups = AsyncMock()
    monkeypatch.setattr(CompletionService, "get_response", _answer)
    monkeypatch.setattr(FlowRunExecutor, "_request_webhook_delivery", lost_wakeups)

    result = await _execute(run)

    assert result == {"status": FlowRunStatus.COMPLETED.value}
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.PENDING.value],
    )
    lost_wakeups.assert_awaited_once()

    sent: list[dict[str, object]] = []

    async def _receive(_self, **kwargs):
        sent.append({**kwargs, "run_status_at_send": (await _run_state(run.id))[0]})
        return _response(200)

    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _receive)

    outcome = await _run_outbox()
    finished = await _read_one(
        sa.select(FlowRuns.status, FlowRuns.finished_at, FlowRuns.created_at).where(
            FlowRuns.id == run.id
        )
    )

    assert outcome["delivered"] == 1
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DELIVERED.value],
    )
    [request] = sent
    assert request["run_status_at_send"] == FlowRunStatus.COMPLETED.value
    assert request["url"] == "https://receiver.example.org/eneo/results"
    assert request["json_body"] is None
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["X-Case"] == "case-123"
    assert len(headers["Idempotency-Key"]) == 64
    body_bytes = request["body_bytes"]
    assert isinstance(body_bytes, bytes)
    body_step_id = json.loads(body_bytes)["deliverables"][0]["step_id"]
    assert json.loads(body_bytes) == {
        "schema": "eneo.flow_run_result.v1",
        "flow_id": str(run.flow_id),
        "run_id": str(run.id),
        "run_created_at": finished.created_at.isoformat(),
        "run_completed_at": finished.finished_at.isoformat(),
        "deliverables": [
            {
                "kind": "text",
                "step_id": body_step_id,
                "step_order": 1,
                "label": "Svar",
                "output_type": "text",
                "text": "# Möte\n\nKlart.",
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_read_in_the_step_input_of_a_run_result_step_is_not_run(
    setup_database,
    object_content_runtime_ready,
    queued_run_result_run,
    monkeypatch,
):
    """The step that sends the run's result reads no step input: a read of a
    step the flow does not have, left from an earlier mode, neither stops
    the run's preflight nor the step, and the result is sent."""
    run = await queued_run_result_run(webhook_question="{{ step_99.output.text }}")

    async def _answer(_self, **_kwargs):
        return SimpleNamespace(completion="Klart.", total_token_count=1)

    monkeypatch.setattr(CompletionService, "get_response", _answer)
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    outcome = await _run_outbox()

    assert outcome["delivered"] == 1
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_result_with_nothing_to_send_is_never_sent(
    setup_database,
    object_content_runtime_ready,
    queued_run_result_run,
    monkeypatch,
):
    """A version published before an empty result was refused can still end
    in a step that sends the run's result with no deliverable: it is dead
    lettered unsent, and the run stays completed."""
    run = await queued_run_result_run(include_prior_step=False)
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    outcome = await _run_outbox()

    assert outcome["dead_lettered"] == 1
    send.assert_not_awaited()
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DEAD_LETTERED.value],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_run_result_run_that_does_not_complete_keeps_no_delivery_row(
    setup_database,
    object_content_runtime_ready,
    queued_run_result_run,
    monkeypatch,
):
    """When the last step's write does not complete the run, the step's
    result, its delivery row and any completion are rolled back together."""
    run = await queued_run_result_run()

    async def _answer(_self, **_kwargs):
        return SimpleNamespace(completion="done", total_token_count=1)

    async def _does_not_complete(**_kwargs):
        return RunFinalizationResult(
            payload={"status": "skipped", "reason": "run_in_progress"},
            terminalization=None,
        )

    send_http_request = AsyncMock()
    monkeypatch.setattr(CompletionService, "get_response", _answer)
    monkeypatch.setattr(
        executor_module, "finalize_run_from_current_results", _does_not_complete
    )
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_http_request)

    await _execute(run)
    await _run_outbox()

    # The task fails the run it could not complete, so the run does not hang.
    assert await _run_state(run.id) == (FlowRunStatus.FAILED.value, [])
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def _result_delivery_status(run, *, admin_user, test_tenant) -> str:
    """The run's ``result.delivery_status`` as reading the run answers it."""
    async with sessionmanager.session() as session, session.begin():
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        service = container.flow_run_service()
        view = await service.enrich_run_with_result_files_and_usage(
            run=await service.get_run(
                run_id=run.id, flow_id=run.flow_id, access_kind="content"
            )
        )
        detail_view = await service.get_run_detail_with_result_files_and_usage(
            flow_id=run.flow_id, run_id=run.id
        )
        detail = FlowAssembler().to_run_detail_public(
            detail_view.run,
            result_files=detail_view.result_files,
            outputs=detail_view.outputs,
            webhook_deliveries=detail_view.webhook_deliveries,
            evidence_access=await service.evidence_access(detail_view.run),
        )
    result = read_run_public(view, started_by=None).result
    assert isinstance(result, FlowRunOutboundHttpResultPublic)
    # The run page reads the detail; it must say the same.
    assert isinstance(detail.result, FlowRunOutboundHttpResultPublic)
    assert detail.result.delivery_status == result.delivery_status
    return result.delivery_status


async def test_a_receiver_down_through_every_attempt_leaves_the_run_completed(
    setup_database,
    completed_run_result_run,
    monkeypatch,
    admin_user,
    test_tenant,
    object_content_runtime_ready,
):
    run, delivery_id = await completed_run_result_run()
    # The run completed before its result was sent, and says so.
    assert (
        await _result_delivery_status(
            run, admin_user=admin_user, test_tenant=test_tenant
        )
        == "pending"
    )
    send_http_request = AsyncMock(return_value=_response(503))
    terminalize_run = AsyncMock()
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_http_request)
    monkeypatch.setattr(FlowRunTerminalizer, "terminalize_run", terminalize_run)
    now = datetime.now(timezone.utc)

    for _ in range(FLOW_WEBHOOK_MAX_ATTEMPTS):
        assert (await _run_outbox(now=now))["attempted"] == 1
        now += timedelta(seconds=2_000)

    delivery = await _read_one(
        sa.select(
            FlowRunWebhookDeliveries.delivery_status,
            FlowRunWebhookDeliveries.delivery_attempts,
        ).where(FlowRunWebhookDeliveries.id == delivery_id)
    )
    run_state = await _read_one(
        sa.select(FlowRuns.status, FlowRuns.error_json).where(FlowRuns.id == run.id)
    )

    assert send_http_request.await_count == FLOW_WEBHOOK_MAX_ATTEMPTS
    keys = {
        call.kwargs["headers"]["Idempotency-Key"]
        for call in send_http_request.await_args_list
    }
    assert len(keys) == 1
    assert delivery.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    assert delivery.delivery_attempts == FLOW_WEBHOOK_MAX_ATTEMPTS
    assert run_state.status == FlowRunStatus.COMPLETED.value
    assert run_state.error_json is None
    # A delivery for a run that has already ended never ends the run.
    terminalize_run.assert_not_awaited()
    assert (
        await _result_delivery_status(
            run, admin_user=admin_user, test_tenant=test_tenant
        )
        == "dead_lettered"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_marked_text_the_run_no_longer_holds_is_never_sent(
    setup_database,
    completed_run_result_run,
    monkeypatch,
):
    """The marked text is gone from its step's result when the delivery is
    due: the result is refused before anything is audited or sent, and the
    run stays completed."""
    run, _ = await completed_run_result_run()
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run.id,
                FlowStepResults.step_order == 1,
            )
            .values(output_payload_json=None)
        )
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    outcome = await _run_outbox()

    assert outcome["dead_lettered"] == 1
    send.assert_not_awaited()
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DEAD_LETTERED.value],
    )
    assert not await _read(
        sa.select(AuditLog.id).where(
            AuditLog.action == ActionType.FLOW_RUN_RESULT_SENDING.value,
            AuditLog.entity_id == run.id,
        )
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_text_result_without_its_audit_row_is_not_sent_and_waits(
    setup_database,
    completed_run_result_run,
    monkeypatch,
):
    run, delivery_id = await completed_run_result_run()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)
    monkeypatch.setattr(
        AuditService, "log", AsyncMock(side_effect=RuntimeError("audit down"))
    )

    await _run_outbox()

    send.assert_not_awaited()
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.PENDING.value],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_run_result_refused_by_the_receiver_is_dead_lettered_once(
    setup_database,
    completed_run_result_run,
    monkeypatch,
):
    run, delivery_id = await completed_run_result_run()
    send_http_request = AsyncMock(return_value=_response(422))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_http_request)

    outcome = await _run_outbox()

    assert outcome["dead_lettered"] == 1
    assert send_http_request.await_count == 1
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DEAD_LETTERED.value],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_template_delivery_for_a_completed_run_is_refused_as_before(
    setup_database,
    seed_delivery,  # noqa: F811  (the fixture imported above)
    monkeypatch,
):
    """A template body is sent while its run is running; a completed run
    gets the same refusal it got before the run result body existed."""
    seeded = await seed_delivery()
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == seeded.run.id)
            .values(
                status=FlowRunStatus.COMPLETED.value,
                finished_at=datetime.now(timezone.utc),
            )
        )
    send_http_request = AsyncMock()
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_http_request)

    outcome = await _run_outbox()
    error = await _read_scalar(
        sa.select(FlowRunWebhookDeliveries.delivery_last_error).where(
            FlowRunWebhookDeliveries.id == seeded.delivery_id
        )
    )

    assert outcome["dead_lettered"] == 1
    assert "no longer running" in error
    send_http_request.assert_not_awaited()


MARKDOWN = "# Möte\n\n- Beslut: klart"
# The form holds only the decision and the first step composes the markdown,
# so a POST step that read the form would send something else.
FORM_DECISION = "Beslut: klart"


@pytest.fixture
def queued_markdown_documents_then_post_run(
    admin_user, completion_model_factory, space_factory, assistant_factory
):
    """Markdown composed from the form, two document deliverables rendered
    from it, then the run result POST step."""

    async def create():
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            _, run, _ = await _create_queued_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config=RUN_RESULT_CONFIG,
                include_prior_step=True,
                prior_step_output=(
                    "compose_text",
                    "text",
                    {"deliverable": {"label": "Markdown"}},
                ),
                later_prior_steps=(
                    (
                        "render_verbatim",
                        "docx",
                        {"deliverable": {"label": "Protokoll"}},
                    ),
                    ("render_verbatim", "docx", {"deliverable": {"label": "Kopia"}}),
                ),
                first_step_question="# Möte\n\n- {{flow.input.question}}",
                # As authored by default: the step reads the step before it.
                webhook_question=None,
            )
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == run.id)
                .values(
                    input_payload_json={"question": FORM_DECISION, "case_id": "c-1"}
                )
            )
            await session.commit()
        return run

    return create


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_result_text_is_the_markdown_and_both_documents_are_sent(
    setup_database,
    object_content_runtime_ready,
    queued_markdown_documents_then_post_run,
    monkeypatch,
):
    """The body carries the marked markdown whole and both documents, each
    under its own label, in step order; no step asks a model."""
    run = await queued_markdown_documents_then_post_run()

    model = AsyncMock(side_effect=AssertionError("no step here calls a model"))

    sent: list[bytes] = []

    async def _receive(_self, **kwargs):
        sent.append(kwargs["body_bytes"])
        return _response(200)

    monkeypatch.setattr(CompletionService, "get_response", model)
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _receive)

    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    await _run_outbox()

    model.assert_not_awaited()
    delivery = await _read_one(
        sa.select(
            FlowRunWebhookDeliveries.delivery_status,
            FlowRunWebhookDeliveries.delivery_last_error,
        ).where(FlowRunWebhookDeliveries.flow_run_id == run.id)
    )
    assert delivery.delivery_status == "delivered", delivery.delivery_last_error
    [body] = [json.loads(item) for item in sent]
    assert "text" not in body
    markdown, *documents = body["deliverables"]
    assert (markdown["kind"], markdown["label"], markdown["text"]) == (
        "text",
        "Markdown",
        MARKDOWN,
    )
    assert [item["label"] for item in documents] == ["Protokoll", "Kopia"]
    for deliverable in documents:
        [file] = deliverable["files"]
        assert file["content_base64"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_marked_document_without_its_file_is_never_sent_in_part(
    setup_database,
    object_content_runtime_ready,
    queued_markdown_documents_then_post_run,
    monkeypatch,
):
    """One document is whole and the other step's file is gone: the result is
    refused before anything is read, audited or sent, and the run stays
    completed."""
    run = await queued_markdown_documents_then_post_run()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)
    monkeypatch.setattr(FlowRunExecutor, "_request_webhook_delivery", AsyncMock())
    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.delete(FlowRunStepResultFiles).where(
                FlowRunStepResultFiles.flow_run_id == run.id,
                FlowRunStepResultFiles.step_order == 3,
            )
        )

    outcome = await _run_outbox()

    assert outcome["dead_lettered"] == 1
    send.assert_not_awaited()
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DEAD_LETTERED.value],
    )
    assert not await _read(
        sa.select(AuditLog.id).where(
            AuditLog.action == ActionType.FLOW_RUN_RESULT_SENDING.value,
            AuditLog.entity_id == run.id,
        )
    )


@pytest.fixture
def queued_long_markdown_then_post_run(
    admin_user, completion_model_factory, space_factory, assistant_factory
):
    """A step whose answer is longer than a step result keeps inline, then
    the POST step reading it."""

    async def create():
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            _, run, _ = await _create_queued_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config=RUN_RESULT_CONFIG,
                include_prior_step=True,
                prior_step_output=MARKED_TEXT,
                webhook_question=None,
            )
            await session.commit()
        return run

    return create


@pytest.mark.asyncio
@pytest.mark.integration
async def test_markdown_beyond_the_inline_limit_is_sent_whole_from_its_file(
    setup_database,
    object_content_runtime_ready,
    queued_long_markdown_then_post_run,
    monkeypatch,
):
    """Text beyond what a step result keeps inline is kept whole in the
    step's file. The POST step reads nothing, so the run completes, and the
    receiver gets the whole text once, read from that file."""
    monkeypatch.setattr(get_settings(), "flow_max_inline_text_bytes", 64)
    run = await queued_long_markdown_then_post_run()
    sent: list[bytes] = []

    async def _receive(_self, **kwargs):
        sent.append(kwargs["body_bytes"])
        return _response(200)

    markdown = "# Lång\n\n" + "x" * 200

    async def _long_answer(_self, **_kwargs):
        return SimpleNamespace(completion=markdown, total_token_count=1)

    monkeypatch.setattr(CompletionService, "get_response", _long_answer)
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _receive)

    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    await _run_outbox()

    [body] = [json.loads(item) for item in sent]
    [text] = body["deliverables"]
    assert text["text"] == markdown
    assert await _run_state(run.id) == (
        FlowRunStatus.COMPLETED.value,
        [FlowOutboxDeliveryStatus.DELIVERED.value],
    )
    [audit] = await _read(
        sa.select(AuditLog.log_metadata).where(
            AuditLog.action == ActionType.FLOW_RUN_RESULT_SENDING.value,
            AuditLog.entity_id == run.id,
        )
    )
    # The row names the step and the file the text was read from, nothing more.
    assert audit.log_metadata["extra"]["step_ids"] == [text["step_id"]]
    assert len(audit.log_metadata["extra"]["file_ids"]) == 1
    assert markdown not in json.dumps(audit.log_metadata)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_markdown_near_the_inline_limit_is_sent_whole_beside_a_prompt(
    setup_database,
    object_content_runtime_ready,
    queued_long_markdown_then_post_run,
    monkeypatch,
):
    """The POST step's assistant keeps an instruction, but the step asks its
    model nothing: its attempt names no model, and the marked text is sent
    whole from the step that wrote it."""
    markdown = "# Lång\n\n" + "x" * 200
    monkeypatch.setattr(
        get_settings(), "flow_max_inline_text_bytes", len(markdown.encode()) + 5
    )
    run = await queued_long_markdown_then_post_run()
    sent: list[bytes] = []

    async def _receive(_self, **kwargs):
        sent.append(kwargs["body_bytes"])
        return _response(200)

    async def _answer(_self, **_kwargs):
        return SimpleNamespace(completion=markdown, total_token_count=1)

    monkeypatch.setattr(CompletionService, "get_response", _answer)
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _receive)

    assert await _execute(run) == {"status": FlowRunStatus.COMPLETED.value}
    await _run_outbox()

    [body] = [json.loads(item) for item in sent]
    assert body["deliverables"][0]["text"] == markdown
    attempt = await _read_one(
        sa.select(FlowStepAttempts.requested_model, FlowStepAttempts.provider).where(
            FlowStepAttempts.flow_run_id == run.id, FlowStepAttempts.step_order == 2
        )
    )
    assert attempt.requested_model is None
    assert attempt.provider is None


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _claim(*, claim_ttl_seconds: float) -> None:
    async with sessionmanager.session() as session, session.begin():
        [_] = await FlowRunWebhookDeliveryRepository(
            session=session
        ).claim_due_delivery_rows(
            now=datetime.now(timezone.utc),
            limit=1,
            claim_ttl_seconds=claim_ttl_seconds,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_run_status_says_where_its_result_delivery_stands(
    setup_database,
    completed_run_result_run,
    client,
    admin_token,
    admin_user,
):
    """``/status/`` names the delivery's state from its outbox row, as the
    detail does, without content and without an audit row: an attempt being
    sent, or one whose next attempt is due, is "sending"; only a failed
    attempt with the next one ahead is "retry_scheduled"."""
    run, delivery_id = await completed_run_result_run()
    headers = {"Authorization": f"Bearer {admin_token}"}
    status_url = f"/api/v1/flows/{run.flow_id}/runs/{run.id}/status/"
    # Without access to the flow's space the status, and its delivery, stay shut.
    refused = await client.get(status_url, headers=headers)
    assert refused.status_code == 403, refused.text
    assert "result_delivery" not in refused.text
    async with sessionmanager.session() as session, session.begin():
        # The reader edits the flow's space, as a person who runs it does.
        await session.execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "SELECT space_id, :user_id, 'editor' FROM flows WHERE id = :flow_id"
            ),
            {"user_id": str(admin_user.id), "flow_id": str(run.flow_id)},
        )
    audit_rows = sa.select(sa.func.count()).select_from(AuditLog)
    audit_rows_before = await _read_scalar(audit_rows)

    async def state() -> tuple[str, int]:
        response = await client.get(status_url, headers=headers)
        assert response.status_code == 200, response.text
        delivery = response.json()["result_delivery"]
        assert delivery["id"] == str(delivery_id)
        return delivery["state"], delivery["delivery_attempts"]

    assert await state() == ("sending", 0)

    # The first attempt, claimed and charged while it is sent.
    await _claim(claim_ttl_seconds=300)
    assert await state() == ("sending", 1)

    # It failed, and the next attempt is an hour ahead.
    next_attempt = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sessionmanager.session() as session, session.begin():
        claim_token = await session.scalar(
            sa.select(FlowRunWebhookDeliveries.claim_token).where(
                FlowRunWebhookDeliveries.id == delivery_id
            )
        )
        assert await FlowRunWebhookDeliveryRepository(
            session=session
        ).record_delivery_failure(
            delivery_id=delivery_id,
            claim_token=claim_token,
            error_message="Receiver answered 503.",
            next_delivery_at=next_attempt,
            dead_lettered_at=None,
        )
    assert await state() == ("retry_scheduled", 1)
    detail = await client.get(
        f"/api/v1/flows/{run.flow_id}/runs/{run.id}/", headers=headers
    )
    assert detail.status_code == 200, detail.text
    [listed] = detail.json()["webhook_deliveries"]
    assert listed["state"] == "retry_scheduled"
    assert listed["next_delivery_at"] is not None

    # The next attempt is due: it is never shown as ahead.
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .values(next_delivery_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
    assert await state() == ("sending", 1)

    # A claim that ran out before its attempt was booked.
    await _claim(claim_ttl_seconds=-1)
    assert await state() == ("sending", 2)

    # Polling the status writes no audit row; the one read of the detail does.
    assert await _read_scalar(audit_rows) == audit_rows_before + 1
