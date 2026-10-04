"""Flow lifecycle audit keeps the actor captured in the run transaction.

The outbox insert records who acted from the run's stable principal and the rows
that exist at that moment; delivery copies that record unchanged, so later renames
or deletions of the user or API key never change or erase the delivered
attribution.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
)
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.users_table import Users
from eneo.flows.enums import FlowRunLifecycleSource, FlowRunStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from tests.fixtures import mint_v2_api_key
from tests.integration.flows.test_flow_audit_outbox_delivery import (
    _create_flow_and_run,
    _delivery_service,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
async def flow_and_run(
    db_container, completion_model_factory, space_factory, assistant_factory, admin_user
):
    async with db_container() as container:
        return await _create_flow_and_run(
            session=container.session(),
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )


@pytest.fixture
def run(flow_and_run):
    return flow_and_run[1]


async def _create_user(db_container, *, tenant_id: UUID, username: str) -> UUID:
    async with db_container() as container:
        user_id = await container.session().scalar(
            sa.insert(Users)
            .values(
                username=username,
                email=f"{username}@example.org",
                state="active",
                used_tokens=0,
                tenant_id=tenant_id,
            )
            .returning(Users.id)
        )
    assert user_id is not None
    return user_id


async def _mint_key(db_container, admin_user) -> UUID:
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            prefix="snap",
        )
    return key.id


async def _delete(db_container, table: Any, row_id: UUID) -> None:
    async with db_container() as container:
        await container.session().execute(sa.delete(table).where(table.id == row_id))


def _user(user_id: UUID) -> FlowPrincipal:
    return FlowPrincipal(principal_type=PrincipalType.USER, principal_user_id=user_id)


def _service(service_id: UUID, key_id: UUID | None) -> FlowPrincipal:
    return FlowPrincipal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=service_id,
        actor_api_key_id=key_id,
    )


async def _insert_outbox(
    db_container,
    run,
    *,
    principal: FlowPrincipal | None,
    source: FlowRunLifecycleSource = FlowRunLifecycleSource.EXECUTOR_COMPLETED,
) -> UUID:
    async with db_container() as container:
        return await FlowRunAuditOutboxRepository(
            session=container.session()
        ).insert_terminal_audit_outbox(
            run=run,
            action=ActionType.FLOW_RUN_COMPLETED,
            principal=principal,
            source=source,
            target_status=FlowRunStatus.COMPLETED,
            error_code=None,
            error_message=None,
        )


async def _deliver(db_container) -> None:
    async with db_container() as container:
        await _delivery_service(container.session()).deliver_due(
            now=datetime.now(timezone.utc) + timedelta(seconds=1)
        )


async def _outbox(db_container, outbox_id: UUID):
    async with db_container() as container:
        return (
            await container.session().execute(
                sa.select(
                    FlowRunAuditOutbox.actor_id,
                    FlowRunAuditOutbox.actor_type,
                    FlowRunAuditOutbox.actor_api_key_id,
                    FlowRunAuditOutbox.actor_snapshot,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()


async def _delivered_metadata(db_container, outbox_id: UUID) -> dict[str, Any]:
    async with db_container() as container:
        rows = (
            await container.session().scalars(
                sa.select(AuditLogTable.log_metadata).where(
                    AuditLogTable.id == outbox_id
                )
            )
        ).all()
    assert len(rows) == 1
    return rows[0]


async def _listed_log(
    client, redis_client, admin_user, admin_user_api_key, *, log_id: UUID, **params
) -> dict[str, Any]:
    headers = {"X-API-Key": admin_user_api_key.key}
    await redis_client.delete(
        f"rate_limit:audit_session:{admin_user.id}:{admin_user.tenant_id}"
    )
    access = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "integration_test",
            "description": "Check flow audit attribution after actor deletion",
        },
        headers=headers,
    )
    assert access.status_code == 200, access.text
    response = await client.get(
        "/api/v1/audit/logs",
        params={"page_size": "1000", **params},
        headers=headers,
        cookies={"audit_session_id": access.cookies["audit_session_id"]},
    )
    assert response.status_code == 200, response.text
    matches = [log for log in response.json()["logs"] if log["id"] == str(log_id)]
    assert len(matches) == 1, response.text
    return matches[0]


async def _make_service_key(db_container, admin_user, key_id: UUID) -> UUID:
    async with db_container() as container:
        session = container.session()
        principal_id = await session.scalar(
            sa.insert(ServicePrincipals)
            .values(
                tenant_id=admin_user.tenant_id,
                display_name="Ingest service",
                scope_type="tenant",
                state="active",
            )
            .returning(ServicePrincipals.id)
        )
        await session.execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == key_id)
            .values(
                ownership="service",
                service_principal_id=principal_id,
                owner_user_id=None,
            )
        )
    assert principal_id is not None
    return principal_id


def _service_snapshot(principal_id: UUID, key_id: UUID | None) -> dict[str, Any]:
    return {
        "type": "service_principal",
        "id": str(principal_id),
        "name": "Ingest service",
        "scope_type": "tenant",
        "scope_id": None,
        **({"actor_api_key_id": str(key_id)} if key_id is not None else {}),
    }


async def test_a_deleted_users_terminal_event_is_listed_with_the_name_at_the_time(
    db_container, run, admin_user, admin_user_api_key, client, redis_client
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="canceller"
    )
    outbox_id = await _insert_outbox(db_container, run, principal=_user(user_id))
    await _delete(db_container, Users, user_id)
    await _deliver(db_container)

    listed = await _listed_log(
        client,
        redis_client,
        admin_user,
        admin_user_api_key,
        log_id=outbox_id,
        actor_id=str(user_id),
    )

    assert listed["actor_id"] is None
    assert listed["metadata"]["actor"] == {
        "type": "user",
        "id": str(user_id),
        "name": "canceller",
        "email": "canceller@example.org",
    }


async def test_a_deleted_service_keys_terminal_event_keeps_the_service_principal(
    db_container, run, admin_user, admin_user_api_key, client, redis_client
):
    key_id = await _mint_key(db_container, admin_user)
    principal_id = await _make_service_key(db_container, admin_user, key_id)
    outbox_id = await _insert_outbox(
        db_container, run, principal=_service(principal_id, key_id)
    )
    captured = await _outbox(db_container, outbox_id)
    await _delete(db_container, ApiKeysV2, key_id)
    assert (await _outbox(db_container, outbox_id)).actor_api_key_id is None
    await _deliver(db_container)

    for actor_filter in (key_id, principal_id):
        listed = await _listed_log(
            client,
            redis_client,
            admin_user,
            admin_user_api_key,
            log_id=outbox_id,
            actor_id=str(actor_filter),
        )
        assert listed["metadata"]["actor"] == _service_snapshot(principal_id, key_id)
    assert (captured.actor_type, captured.actor_api_key_id) == ("api_key", key_id)


async def test_a_service_run_whose_key_was_deleted_is_attributed_to_its_principal(
    db_container, flow_and_run, admin_user, admin_user_api_key, client, redis_client
):
    flow, _user_run = flow_and_run
    key_id = await _mint_key(db_container, admin_user)
    principal_id = await _make_service_key(db_container, admin_user, key_id)
    async with db_container() as container:
        service_run = await FlowRunRepository(session=container.session()).create(
            flow_id=flow.id,
            flow_version=1,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_service_id=principal_id,
            created_by_api_key_id=key_id,
            runtime_service_permission=ApiKeyPermission.WRITE,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"question": "What happened?"},
            preseed_steps=[
                {
                    "step_id": flow.steps[0].id,
                    "assistant_id": flow.steps[0].assistant_id,
                    "step_order": 1,
                }
            ],
        )
    await _delete(db_container, ApiKeysV2, key_id)

    async with db_container() as container:
        result = await container.flow_run_terminalizer().terminalize_run(
            run_id=service_run.id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError(
                code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                message="The step failed.",
            ),
        )
    assert result.did_transition and result.audit_outbox_id is not None
    outbox_id = result.audit_outbox_id
    captured = await _outbox(db_container, outbox_id)
    await _deliver(db_container)

    listed = await _listed_log(
        client,
        redis_client,
        admin_user,
        admin_user_api_key,
        log_id=outbox_id,
        actor_id=str(principal_id),
    )

    assert listed["metadata"]["actor"] == _service_snapshot(principal_id, None)
    assert (captured.actor_type, captured.actor_api_key_id) == ("system", None)


async def test_a_system_transition_records_the_system_and_its_source(db_container, run):
    outbox_id = await _insert_outbox(
        db_container,
        run,
        principal=None,
        source=FlowRunLifecycleSource.ABANDONMENT_RECONCILER,
    )
    await _deliver(db_container)

    metadata = await _delivered_metadata(db_container, outbox_id)

    assert metadata["actor"] == {"type": "system", "via": "abandonment_reconciler"}


async def test_a_user_deleted_before_capture_is_recorded_without_a_name(
    db_container, run, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="already-gone"
    )
    await _delete(db_container, Users, user_id)

    outbox_id = await _insert_outbox(db_container, run, principal=_user(user_id))
    stored = await _outbox(db_container, outbox_id)
    await _deliver(db_container)

    expected = {"type": "user", "id": str(user_id)}
    assert (stored.actor_id, stored.actor_api_key_id) == (None, None)
    assert stored.actor_snapshot == expected
    assert (await _delivered_metadata(db_container, outbox_id))["actor"] == expected


async def test_a_key_deleted_before_capture_keeps_its_principal_and_key_id(
    db_container, run, admin_user
):
    key_id = await _mint_key(db_container, admin_user)
    principal_id = await _make_service_key(db_container, admin_user, key_id)
    await _delete(db_container, ApiKeysV2, key_id)

    outbox_id = await _insert_outbox(
        db_container, run, principal=_service(principal_id, key_id)
    )
    stored = await _outbox(db_container, outbox_id)

    assert (stored.actor_type, stored.actor_api_key_id) == ("system", None)
    assert stored.actor_snapshot == _service_snapshot(principal_id, key_id)


async def test_a_legacy_outbox_row_without_a_snapshot_delivers_no_actor_block(
    db_container, run, admin_user
):
    outbox_id = await _insert_outbox(db_container, run, principal=_user(admin_user.id))
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(actor_snapshot=None)
        )
    await _deliver(db_container)

    metadata = await _delivered_metadata(db_container, outbox_id)

    assert "actor" not in metadata
    assert metadata["flow_run_id"] == str(run.id)


async def test_a_repeated_delivery_keeps_one_row_with_the_same_snapshot(
    db_container, run, admin_user
):
    outbox_id = await _insert_outbox(db_container, run, principal=_user(admin_user.id))
    await _deliver(db_container)
    first = await _delivered_metadata(db_container, outbox_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=datetime.now(timezone.utc),
                delivered_at=None,
            )
        )
        await container.session().execute(
            sa.update(Users)
            .where(Users.id == admin_user.id)
            .values(username="renamed-before-redelivery")
        )
    await _deliver(db_container)

    second = await _delivered_metadata(db_container, outbox_id)

    assert second == first
    assert first["actor"] == {
        "type": "user",
        "id": str(admin_user.id),
        "name": admin_user.username,
        "email": admin_user.email,
    }
