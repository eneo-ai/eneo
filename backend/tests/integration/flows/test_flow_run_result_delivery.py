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

from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunWebhookDeliveries,
)
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
    assert json.loads(body_bytes) == {
        "schema": "eneo.flow_run_result.v1",
        "flow_id": str(run.flow_id),
        "run_id": str(run.id),
        "run_created_at": finished.created_at.isoformat(),
        "run_completed_at": finished.finished_at.isoformat(),
        # The only step reads the run's form, so that is its text.
        "text": "What happened?",
        "deliverables": [],
    }


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
async def test_a_receiver_down_through_every_attempt_leaves_the_run_completed(
    setup_database,
    completed_run_result_run,
    monkeypatch,
):
    run, delivery_id = await completed_run_result_run()
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
                prior_step_output=("compose_text", "text", None),
                later_prior_steps=(
                    (
                        "render_verbatim",
                        "docx",
                        {"deliverable": {"label": "Protokoll"}},
                    ),
                    ("render_verbatim", "docx", {"deliverable": {"label": "Kopia"}}),
                ),
            )
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == run.id)
                .values(input_payload_json={"question": MARKDOWN, "case_id": "c-1"})
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
    """The body's text is the run's text result: the markdown the POST step
    reads and keeps as its own text, without calling its model."""
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
    assert body["text"] == MARKDOWN
    assert [item["label"] for item in body["deliverables"]] == ["Protokoll", "Kopia"]
    for deliverable in body["deliverables"]:
        [file] = deliverable["files"]
        assert file["content_base64"]


@pytest.fixture
def queued_long_markdown_then_post_run(
    admin_user, completion_model_factory, space_factory, assistant_factory
):
    """Markdown longer than a step result keeps inline, then the POST step."""

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
                prior_step_output=("compose_text", "text", None),
            )
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == run.id)
                .values(input_payload_json={"question": "# Lång\n\n" + "x" * 200})
            )
            await session.commit()
        return run

    return create


@pytest.mark.asyncio
@pytest.mark.integration
async def test_markdown_beyond_the_inline_limit_fails_the_run_and_is_never_cut(
    setup_database,
    object_content_runtime_ready,
    queued_long_markdown_then_post_run,
    monkeypatch,
):
    """Text beyond what a step result keeps inline is never sent in part: the
    POST step cannot read it whole, so the run fails with a typed error and no
    delivery is made."""
    monkeypatch.setattr(get_settings(), "flow_max_inline_text_bytes", 64)
    run = await queued_long_markdown_then_post_run()
    send = AsyncMock(return_value=_response(200))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)

    await _execute(run)
    await _run_outbox()

    send.assert_not_awaited()
    state = await _read_one(
        sa.select(FlowRuns.status, FlowRuns.error_json).where(FlowRuns.id == run.id)
    )
    assert state.status == FlowRunStatus.FAILED.value
    assert state.error_json["code"] == "typed_io_input_too_large"
    assert not await _read(
        sa.select(FlowRunWebhookDeliveries.id).where(
            FlowRunWebhookDeliveries.flow_run_id == run.id
        )
    )
