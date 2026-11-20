"""Sending a run's result again after its delivery ended in dead letter.

The route resets one dead-lettered run result delivery to a fresh attempt
budget, with an audit row in the same commit. The outbox then sends it as
before: to the same receiver with the same idempotency key."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.actor_types import ActorType
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRunWebhookDeliveries,
    Flows,
    FlowStepAttempts,
    FlowVersions,
)
from eneo.flows import FlowRepository
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_MAX_ATTEMPTS,
)
from eneo.flows.application.flow_webhook_redelivery import redeliver_run_result
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.exceptions import ConflictException, NotFoundException
from eneo.spaces.api.space_models import SpaceRoleValue
from tests.integration.flows import test_flow_consumer_api_contract as consumer
from tests.integration.flows.test_flow_evidence_api_contracts import (
    _add_space_membership,
    _create_view_only_user_and_token,
)
from tests.integration.flows.test_flow_run_result_delivery import (  # noqa: F401
    completed_run_result_run,
)
from tests.integration.flows.test_flow_webhook_outbox_delivery import (
    _create_running_webhook_run,
    _intent,
    _read,
    _read_one,
    _response,
    _run_outbox,
    _write,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

admin_token = consumer.admin_token


def _path(run, delivery_id: UUID) -> str:
    return (
        f"/api/v1/flows/{run.flow_id}/runs/{run.id}/webhook-deliveries/"
        f"{delivery_id}/redeliver/"
    )


async def _make_editor(run, user_id: UUID) -> None:
    space_id = (
        await _read_one(sa.select(Flows.space_id).where(Flows.id == run.flow_id))
    )[0]
    await _write(
        sa.text(
            "INSERT INTO spaces_users (space_id, user_id, role) "
            "VALUES (:space_id, :user_id, :role) ON CONFLICT DO NOTHING"
        ).bindparams(
            space_id=space_id, user_id=user_id, role=SpaceRoleValue.EDITOR.value
        )
    )


async def _dead_letter(delivery_id: UUID, at: datetime) -> None:
    await _write(
        sa.update(FlowRunWebhookDeliveries)
        .where(FlowRunWebhookDeliveries.id == delivery_id)
        .values(
            delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
            delivery_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            next_delivery_at=None,
            dead_lettered_at=at,
            delivery_last_error="HTTP 503",
        )
    )


async def _delivery(delivery_id: UUID):
    return await _read_one(
        sa.select(
            FlowRunWebhookDeliveries.delivery_status,
            FlowRunWebhookDeliveries.delivery_attempts,
            FlowRunWebhookDeliveries.dead_lettered_at,
            FlowRunWebhookDeliveries.idempotency_key,
        ).where(FlowRunWebhookDeliveries.id == delivery_id)
    )


async def _redeliver(run, delivery_id: UUID, expected: datetime):
    return await redeliver_run_result(
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        run_id=run.id,
        delivery_id=delivery_id,
        expected_dead_lettered_at=expected,
        actor_id=run.principal_user_id,
        actor_type=ActorType.USER,
        actor_api_key_id=None,
        audit_metadata={},
    )


async def _evidence_delivery_status(client, run, headers) -> str:
    """Where the run's evidence export says the result's delivery stands."""
    evidence = await client.get(
        f"/api/v1/flows/{run.flow_id}/runs/{run.id}/evidence/", headers=headers
    )
    assert evidence.status_code == 200, evidence.text
    return evidence.json()["run"]["result"]["delivery_status"]


@pytest.fixture
def dead_lettered_run(completed_run_result_run, admin_user):  # noqa: F811
    async def seed(at: datetime | None = None):
        run, delivery_id = await completed_run_result_run()
        at = at or datetime(2026, 7, 22, 8, 30, 0, 123456, tzinfo=timezone.utc)
        await _dead_letter(delivery_id, at)
        await _make_editor(run, admin_user.id)
        return run, delivery_id, at

    return seed


async def test_a_dead_lettered_result_is_sent_again_with_the_same_key(
    setup_database,
    client,
    admin_token,
    completed_run_result_run,  # noqa: F811
    admin_user,
    monkeypatch,
):
    run, delivery_id = await completed_run_result_run()
    await _make_editor(run, admin_user.id)
    headers = {"Authorization": f"Bearer {admin_token}"}
    send = AsyncMock(return_value=_response(503))
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send)
    now = datetime.now(timezone.utc)
    for _ in range(FLOW_WEBHOOK_MAX_ATTEMPTS):
        await _run_outbox(now=now)
        now += timedelta(seconds=2_000)

    detail = await client.get(
        f"/api/v1/flows/{run.flow_id}/runs/{run.id}/", headers=headers
    )
    assert detail.status_code == 200, detail.text
    [seen] = detail.json()["webhook_deliveries"]
    assert seen["delivery_status"] == "dead_lettered"
    assert detail.json()["result"]["delivery_status"] == "dead_lettered"
    assert await _evidence_delivery_status(client, run, headers) == "dead_lettered"

    response = await client.post(
        _path(run, delivery_id),
        json={"expected_dead_lettered_at": seen["dead_lettered_at"]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(delivery_id)
    assert body["delivery_status"] == "pending"
    assert body["delivery_attempts"] == 0
    assert body["dead_lettered_at"] is None
    assert await _evidence_delivery_status(client, run, headers) == "pending"
    audit = await _read_one(
        sa.select(AuditLog.log_metadata).where(
            AuditLog.action == "flow_run_webhook_redelivered",
            AuditLog.entity_id == run.id,
        )
    )
    assert audit.log_metadata["delivery_id"] == str(delivery_id)
    assert audit.log_metadata["previous_delivery_attempts"] == FLOW_WEBHOOK_MAX_ATTEMPTS

    send.return_value = _response(200)
    assert (await _run_outbox(now=now + timedelta(seconds=1)))["delivered"] == 1
    assert (await _delivery(delivery_id)).delivery_status == "delivered"
    keys = {call.kwargs["headers"]["Idempotency-Key"] for call in send.await_args_list}
    assert send.await_count == FLOW_WEBHOOK_MAX_ATTEMPTS + 1
    assert len(keys) == 1
    assert (await _read_one(sa.select(FlowRuns.status).where(FlowRuns.id == run.id)))[
        0
    ] == "completed"


async def test_redelivery_refusals_are_typed_and_change_nothing(
    setup_database, client, admin_token, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    headers = {"Authorization": f"Bearer {admin_token}"}

    async def refusal(expected: datetime | str) -> tuple[int, str | None]:
        response = await client.post(
            _path(run, delivery_id),
            json={"expected_dead_lettered_at": str(expected)},
            headers=headers,
        )
        payload = response.json()
        return response.status_code, (payload.get("context") or {}).get("reason")

    assert await refusal(at - timedelta(microseconds=1)) == (
        409,
        "dead_lettered_at_changed",
    )
    # A time without a zone is not a dead letter the caller has seen.
    assert (await refusal("2026-07-22T08:30:00"))[0] == 422

    await _write(
        sa.update(FlowRuns).where(FlowRuns.id == run.id).values(status="failed")
    )
    assert await refusal(at.isoformat()) == (409, "run_not_completed")
    await _write(
        sa.update(FlowRuns).where(FlowRuns.id == run.id).values(status="completed")
    )

    assert (await _delivery(delivery_id)).delivery_status == "dead_lettered"
    assert (await refusal(at.isoformat()))[0] == 200
    assert await refusal(at.isoformat()) == (409, "not_dead_lettered")


async def test_a_template_delivery_is_not_sent_again(
    setup_database,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        assert flow.id is not None and step.id is not None
        delivery_id = await FlowRunWebhookDeliveryRepository(
            session=session
        ).insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id, step_order=step.step_order),
        )
        await session.commit()
    at = datetime.now(timezone.utc)
    await _dead_letter(delivery_id, at)

    with pytest.raises(ConflictException) as refused:
        await _redeliver(run, delivery_id, at)

    assert refused.value.context == {
        "reason": "not_run_result",
        "delivery_id": str(delivery_id),
    }


async def test_redelivery_needs_edit_rights_and_a_delivery_of_this_run(
    setup_database,
    client,
    admin_token,
    dead_lettered_run,
    db_container,
    patch_auth_service_jwt,
    admin_user,
):
    run, delivery_id, at = await dead_lettered_run()
    body = {"expected_dead_lettered_at": at.isoformat()}
    viewer, viewer_token = await _create_view_only_user_and_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        tenant_id=admin_user.tenant_id,
    )
    space_id = (
        await _read_one(sa.select(Flows.space_id).where(Flows.id == run.flow_id))
    )[0]
    await _add_space_membership(
        db_container=db_container, space_id=space_id, user_id=viewer.id
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    headers = {"Authorization": f"Bearer {admin_token}"}

    assert (
        await client.post(_path(run, delivery_id), json=body, headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.post(_path(run, uuid4()), json=body, headers=headers)
    ).status_code == 404
    other_run_path = (
        f"/api/v1/flows/{run.flow_id}/runs/{uuid4()}/webhook-deliveries/"
        f"{delivery_id}/redeliver/"
    )
    assert (
        await client.post(other_run_path, json=body, headers=headers)
    ).status_code == 404
    assert (await _delivery(delivery_id)).delivery_status == "dead_lettered"

    async with db_container() as container:
        await FlowRepository(session=container.session()).delete(
            run.flow_id, run.tenant_id
        )
    retired = await client.post(_path(run, delivery_id), json=body, headers=headers)
    assert retired.status_code == 404, retired.text
    assert (await _delivery(delivery_id)).delivery_status == "dead_lettered"


async def test_a_service_key_cannot_send_a_result_again(
    setup_database, client, admin_token, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    service_key = await consumer._create_flow_service_key(client, token=admin_token)

    response = await client.post(
        _path(run, delivery_id),
        json={"expected_dead_lettered_at": at.isoformat()},
        headers={"X-API-Key": service_key},
    )

    assert response.status_code == 403, response.text
    assert (await _delivery(delivery_id)).delivery_status == "dead_lettered"
    assert not await _redelivery_audits(run.id)


async def test_a_delivery_is_found_only_under_its_own_run_and_flow(
    setup_database, client, admin_token, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    # A second run of the same flow, with a dead letter of its own.
    other_run_id, other_delivery_id = uuid4(), uuid4()
    await _copy_row(FlowRuns, run.id, id=other_run_id)
    [(attempt_id,)] = await _read(
        sa.select(FlowStepAttempts.id).where(
            FlowStepAttempts.flow_run_id == run.id,
            FlowStepAttempts.step_id
            == sa.select(FlowRunWebhookDeliveries.step_id)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .scalar_subquery(),
        )
    )
    await _copy_row(FlowStepAttempts, attempt_id, id=uuid4(), flow_run_id=other_run_id)
    await _copy_row(
        FlowRunWebhookDeliveries,
        delivery_id,
        id=other_delivery_id,
        flow_run_id=other_run_id,
        idempotency_key=f"other-{uuid4()}",
    )
    space_id = await consumer._create_space(client, token=admin_token)
    other_flow = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": f"other-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert other_flow.status_code == 201, other_flow.text
    body = {"expected_dead_lettered_at": at.isoformat()}
    headers = {"Authorization": f"Bearer {admin_token}"}

    other_runs_delivery = await client.post(
        _path(run, other_delivery_id), json=body, headers=headers
    )
    other_flows_path = (
        f"/api/v1/flows/{other_flow.json()['id']}/runs/{run.id}/"
        f"webhook-deliveries/{delivery_id}/redeliver/"
    )
    under_other_flow = await client.post(other_flows_path, json=body, headers=headers)

    assert other_runs_delivery.status_code == 404, other_runs_delivery.text
    assert under_other_flow.status_code == 404, under_other_flow.text
    for kept in (delivery_id, other_delivery_id):
        assert (await _delivery(kept)).delivery_status == "dead_lettered"
    assert not await _redelivery_audits(run.id)
    assert not await _redelivery_audits(other_run_id)


async def _copy_row(table, row_id: UUID, **changes) -> None:
    """Insert a copy of one row with ``changes`` applied."""
    columns = table.__table__
    [row] = await _read(sa.select(columns).where(columns.c.id == row_id))
    await _write(sa.insert(columns).values({**row._mapping, **changes}))


async def _redelivery_audits(run_id: UUID) -> list:
    return await _read(
        sa.select(AuditLog.id).where(
            AuditLog.action == "flow_run_webhook_redelivered",
            AuditLog.entity_id == run_id,
        )
    )


@pytest.mark.parametrize(
    "failed_log",
    [AsyncMock(return_value=None), AsyncMock(side_effect=RuntimeError("down"))],
    ids=["not_written", "raised"],
)
async def test_a_failed_audit_refuses_the_redelivery(
    setup_database, client, admin_token, dead_lettered_run, monkeypatch, failed_log
):
    run, delivery_id, at = await dead_lettered_run()
    monkeypatch.setattr(AuditService, "log", failed_log)

    response = await client.post(
        _path(run, delivery_id),
        json={"expected_dead_lettered_at": at.isoformat()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "flow_run_webhook_redelivery_audit_unavailable"
    delivery = await _delivery(delivery_id)
    assert delivery.delivery_status == "dead_lettered"
    assert delivery.dead_lettered_at == at


async def test_a_redelivery_is_audited_even_when_the_action_is_turned_off(
    setup_database, client, admin_token, dead_lettered_run, monkeypatch
):
    run, delivery_id, at = await dead_lettered_run()
    monkeypatch.setattr(
        AuditService, "_should_log_action", AsyncMock(return_value=False)
    )

    response = await client.post(
        _path(run, delivery_id),
        json={"expected_dead_lettered_at": at.isoformat()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert (await _delivery(delivery_id)).delivery_status == "pending"
    audit = await _read_one(
        sa.select(AuditLog.log_metadata).where(
            AuditLog.action == "flow_run_webhook_redelivered",
            AuditLog.entity_id == run.id,
        )
    )
    assert audit.log_metadata["delivery_id"] == str(delivery_id)


async def _wait_until_blocked(task: asyncio.Task) -> None:
    await asyncio.sleep(0.5)
    assert not task.done()


async def test_two_redeliveries_of_one_dead_letter_reset_it_once(
    setup_database, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    async with sessionmanager.session() as first, first.begin():
        await first.execute(
            sa.select(FlowRuns.id).where(FlowRuns.id == run.id).with_for_update()
        )
        second = asyncio.create_task(_redeliver(run, delivery_id, at))
        await _wait_until_blocked(second)
        assert await FlowRunWebhookDeliveryRepository(
            session=first
        ).redeliver_dead_lettered(
            delivery_id=delivery_id,
            tenant_id=run.tenant_id,
            expected_dead_lettered_at=at,
            now=datetime.now(timezone.utc),
        )

    with pytest.raises(ConflictException) as refused:
        await second
    assert refused.value.context["reason"] == "not_dead_lettered"


async def test_a_late_redelivery_cannot_reset_a_second_dead_letter(
    setup_database, dead_lettered_run
):
    run, delivery_id, first_at = await dead_lettered_run()
    await _redeliver(run, delivery_id, first_at)
    await _dead_letter(delivery_id, first_at + timedelta(minutes=30))

    with pytest.raises(ConflictException) as refused:
        await _redeliver(run, delivery_id, first_at)

    assert refused.value.context["reason"] == "dead_lettered_at_changed"
    assert (await _delivery(delivery_id)).delivery_status == "dead_lettered"


async def _clear_audit_outbox(run_id: UUID) -> None:
    # The run's own audit rows would hold back the purge; only the delivery
    # is under test here.
    await _write(
        sa.delete(FlowRunAuditOutbox).where(FlowRunAuditOutbox.flow_run_id == run_id)
    )


async def test_a_purge_that_wins_leaves_nothing_to_send_again(
    setup_database, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    await _clear_audit_outbox(run.id)
    async with sessionmanager.session() as purge, purge.begin():
        await purge.execute(
            sa.select(FlowRuns.id).where(FlowRuns.id == run.id).with_for_update()
        )
        redelivery = asyncio.create_task(_redeliver(run, delivery_id, at))
        await _wait_until_blocked(redelivery)
        result = await FlowRunHistoryPurgeRepository(purge).purge_run_history([run.id])
        assert result.counts.flow_runs_purged == 1

    with pytest.raises(NotFoundException):
        await redelivery


async def test_a_redelivery_that_wins_keeps_the_run_from_the_purge(
    setup_database, dead_lettered_run
):
    run, delivery_id, at = await dead_lettered_run()
    await _clear_audit_outbox(run.id)
    await _redeliver(run, delivery_id, at)

    async with sessionmanager.session() as purge, purge.begin():
        result = await FlowRunHistoryPurgeRepository(purge).purge_run_history([run.id])

    assert result.counts.flow_runs_purged == 0
    assert (await _delivery(delivery_id)).delivery_status == "pending"


async def test_a_pinned_definition_that_fails_its_checksum_keeps_its_own_error(
    setup_database, client, admin_token, dead_lettered_run
):
    """Only writing and committing the audit row answers that the audit is
    unavailable; a damaged pinned version says what it is."""
    run, delivery_id, at = await dead_lettered_run()
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowVersions)
            .where(FlowVersions.flow_id == run.flow_id)
            .values(definition_checksum="0" * 64)
        )

    response = await client.post(
        _path(run, delivery_id),
        json={"expected_dead_lettered_at": at.isoformat()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_definition_checksum_mismatch"
    delivery = await _delivery(delivery_id)
    assert delivery.delivery_status == "dead_lettered"
    assert await _redelivery_audits(run.id) == []
