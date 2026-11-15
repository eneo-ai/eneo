"""An organisation's administrator switches Flows on and off in the tenant
settings, for their own organisation only, and sees whether the two platform
task workers run.

The integration conftest seeds the global `flows_core` row on. Every test here
turns it off first, as an installation runs, so only the organisation's own
row (written by the switch) can open the flow routes.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from eneo.audit.domain.action_types import ActionType
from eneo.audit.schemas.audit_config_schemas import ActionUpdate, CategoryUpdate
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.feature_flag.feature_flag_repo import FeatureFlagRepository
from eneo.tasks.contracts import TaskWorkerReadiness
from tests.fixtures import mint_v2_api_key

SWITCH = "/api/v1/settings/flows"
WORKERS = "/api/v1/settings/task-workers"
SETTINGS = "/api/v1/settings/"
# A flow route an administrator can read once Flows are on.
FLOW_ROUTE = "/api/v1/settings/flow-input-limits"


async def _flag_rows() -> dict[str, Any]:
    """The global `flows_core` row and every organisation's own row."""
    async with sessionmanager.session() as session, session.begin():
        global_enabled = await session.scalar(
            sa.text(
                "SELECT enabled FROM global_feature_flags WHERE name = 'flows_core'"
            )
        )
        rows = await session.execute(
            sa.text(
                "SELECT tenant_id, enabled FROM tenant_feature_flags "
                "WHERE name = 'flows_core'"
            )
        )
        return {
            "global": global_enabled,
            "tenants": {row.tenant_id: row.enabled for row in rows},
        }


async def _set_tenant_row(db_container, tenant_id: UUID, *, enabled: bool) -> None:
    async with db_container() as container:
        flag = await container.feature_flag_repo().one(name="flows_core")
        service = container.feature_flag_service()
        if enabled:
            await service.enable_tenant(flag.feature_id, tenant_id)
        else:
            await service.disable_tenant(flag.feature_id, tenant_id)


async def _switch_audit_rows(tenant_id: UUID) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == ActionType.TENANT_SETTINGS_UPDATED.value)
            .order_by(AuditLog.timestamp)
        )
        return [
            dict(row.log_metadata)
            for row in rows
            if row.log_metadata.get("setting") == "flows_enabled"
        ]


@pytest.fixture
async def global_flows_off(db_container) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.text(
                "UPDATE global_feature_flags SET enabled = false "
                "WHERE name = 'flows_core'"
            )
        )


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    _ = patch_auth_service_jwt
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def _other_organisation(db_container, tenant_factory, user_factory):
    """A second organisation whose Owner holds admin and every flow permission,
    and which has chosen Flows off with its own row."""
    async with db_container() as container:
        session = container.session()
        tenant = await tenant_factory(session)
        user = await user_factory(session, tenant_id=tenant.id)
        owner = Roles(
            name="Owner",
            permissions=["admin", "flows_view", "flows_run", "flows_manage"],
            tenant_id=tenant.id,
            predefined_source="Owner",
        )
        session.add(owner)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=user.id, role_id=owner.id)
        )
        key = await mint_v2_api_key(
            container.api_key_v2_repo(), tenant_id=tenant.id, user_id=user.id
        )
        tenant_id = tenant.id
    await _set_tenant_row(db_container, tenant_id, enabled=False)
    return tenant_id, key


@pytest.mark.usefixtures("global_flows_off")
async def test_an_admin_switches_flows_on_and_off_for_their_own_organisation(
    client: AsyncClient,
    db_container,
    admin_user,
    admin_headers,
    tenant_factory,
    user_factory,
):
    other_id, other_key = await _other_organisation(
        db_container, tenant_factory, user_factory
    )
    assert (await client.get(FLOW_ROUTE, headers=admin_headers)).status_code == 404

    switched_on = await client.patch(
        SWITCH, json={"enabled": True}, headers=admin_headers
    )

    assert switched_on.status_code == 200, switched_on.text
    assert switched_on.json()["flows_enabled"] is True
    # Each request below runs in its own session: the switch has committed.
    settings = await client.get(SETTINGS, headers=admin_headers)
    assert settings.json()["flows_enabled"] is True
    assert (await client.get(FLOW_ROUTE, headers=admin_headers)).status_code == 200
    other_route = await client.get(FLOW_ROUTE, headers={"X-API-Key": other_key.key})
    assert other_route.status_code == 404, other_route.text
    assert await _flag_rows() == {
        "global": False,
        "tenants": {admin_user.tenant_id: True, other_id: False},
    }

    switched_off = await client.patch(
        SWITCH, json={"enabled": False}, headers=admin_headers
    )

    assert switched_off.status_code == 200, switched_off.text
    assert switched_off.json()["flows_enabled"] is False
    assert (await client.get(SETTINGS, headers=admin_headers)).json()[
        "flows_enabled"
    ] is False
    assert (await client.get(FLOW_ROUTE, headers=admin_headers)).status_code == 404
    assert await _flag_rows() == {
        "global": False,
        "tenants": {admin_user.tenant_id: False, other_id: False},
    }


@pytest.mark.usefixtures("global_flows_off")
async def test_a_member_without_admin_cannot_switch_flows(
    client: AsyncClient, db_container, admin_user, user_factory, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    async with db_container() as container:
        session = container.session()
        member = await user_factory(session)
        role = Roles(
            name="flow-member",
            permissions=["flows_view", "flows_run", "flows_manage"],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=member.id, role_id=role.id)
        )
        member_in_db = await container.user_repo().get_user_by_id(member.id)
        token = container.auth_service().create_access_token_for_user(member_in_db)
    before = await _flag_rows()

    response = await client.patch(
        SWITCH, json={"enabled": True}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403, response.text
    assert await _flag_rows() == before


@pytest.mark.usefixtures("global_flows_off")
@pytest.mark.parametrize(
    ("permission", "status"), [("read", 403), ("write", 403), ("admin", 200)]
)
async def test_only_a_key_with_the_admin_permission_switches_flows(
    client: AsyncClient, db_container, admin_user, permission, status
):
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            permission=permission,
        )
    before = await _flag_rows()

    response = await client.patch(
        SWITCH, json={"enabled": True}, headers={"X-API-Key": key.key}
    )

    assert response.status_code == status, response.text
    if status == 200:
        assert await _flag_rows() == {
            **before,
            "tenants": {**before["tenants"], admin_user.tenant_id: True},
        }
    else:
        assert await _flag_rows() == before


@pytest.mark.usefixtures("global_flows_off")
async def test_an_audited_switch_records_the_old_and_new_value(
    client: AsyncClient, admin_user, admin_headers
):
    for enabled in (True, False):
        response = await client.patch(
            SWITCH, json={"enabled": enabled}, headers=admin_headers
        )
        assert response.status_code == 200, response.text

    rows = await _switch_audit_rows(admin_user.tenant_id)

    assert [row["changes"] for row in rows] == [
        {"flows_enabled": {"old": False, "new": True}},
        {"flows_enabled": {"old": True, "new": False}},
    ]


@pytest.mark.usefixtures("global_flows_off")
async def test_overlapping_switches_audit_the_value_the_later_one_changed(
    db_container, admin_user
):
    """Two administrators of one organisation switch at the same moment. The
    later switch waits for the earlier one before it reads the old value, so
    its audit row says what it actually changed."""
    async with db_container() as later:
        later_pid = await later.session().scalar(sa.text("SELECT pg_backend_pid()"))
        racing: asyncio.Task[Any] | None = None
        try:
            async with db_container() as earlier:
                await earlier.settings_service().update_flows_setting(enabled=True)
                racing = asyncio.create_task(
                    later.settings_service().update_flows_setting(enabled=False)
                )
                await _wait_until_waiting_for_a_lock(later_pid)
            # Leaving `earlier` committed the switch on.
            await asyncio.wait_for(racing, timeout=5)
        finally:
            if racing is not None:
                racing.cancel()
                await asyncio.gather(racing, return_exceptions=True)

    rows = await _switch_audit_rows(admin_user.tenant_id)
    assert [row["changes"] for row in rows] == [
        {"flows_enabled": {"old": False, "new": True}},
        {"flows_enabled": {"old": True, "new": False}},
    ]
    assert (await _flag_rows())["tenants"][admin_user.tenant_id] is False


async def _wait_until_waiting_for_a_lock(pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with sessionmanager.session() as session, session.begin():
            wait_event_type = await session.scalar(
                sa.text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": pid},
            )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Session {pid} never waited on the earlier switch")


@pytest.mark.usefixtures("global_flows_off")
@pytest.mark.parametrize("switched_off", ["audit_logging", "category", "action"])
async def test_no_audit_row_when_the_audit_configuration_leaves_it_out(
    client: AsyncClient, db_container, admin_user, admin_headers, switched_off
):
    tenant_id = admin_user.tenant_id
    async with db_container() as container:
        if switched_off == "audit_logging":
            flag = await container.feature_flag_repo().one(name="audit_logging_enabled")
            await container.feature_flag_service().disable_tenant(
                flag.feature_id, tenant_id
            )
        elif switched_off == "category":
            await container.audit_config_service().update_config(
                tenant_id, [CategoryUpdate(category="admin_actions", enabled=False)]
            )
        else:
            await container.audit_config_service().update_action_config(
                tenant_id,
                [
                    ActionUpdate(
                        action=ActionType.TENANT_SETTINGS_UPDATED.value, enabled=False
                    )
                ],
            )

    response = await client.patch(SWITCH, json={"enabled": True}, headers=admin_headers)

    assert response.status_code == 200, response.text
    assert (await _flag_rows())["tenants"][tenant_id] is True
    assert await _switch_audit_rows(tenant_id) == []


@pytest.mark.usefixtures("global_flows_off")
async def test_a_failed_commit_answers_with_an_error_and_keeps_flows_off(
    raw_client: AsyncClient, admin_user, admin_headers, monkeypatch
):
    """The response is sent after the commit, so a commit that fails reaches
    the caller instead of a success the database never kept."""
    original = FeatureFlagRepository.set_tenant

    async def _mark(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        self.db_session.sync_session.info["fail_commit"] = True

    def _before_commit(session: Session) -> None:
        if session.info.pop("fail_commit", False):
            raise RuntimeError("commit failed")

    monkeypatch.setattr(FeatureFlagRepository, "set_tenant", _mark)
    event.listen(Session, "before_commit", _before_commit)
    try:
        response = await raw_client.patch(
            SWITCH, json={"enabled": True}, headers=admin_headers
        )
    finally:
        event.remove(Session, "before_commit", _before_commit)

    assert response.status_code == 500, response.text
    assert admin_user.tenant_id not in (await _flag_rows())["tenants"]
    assert await _switch_audit_rows(admin_user.tenant_id) == []


@pytest.mark.parametrize(
    ("readiness", "expected"),
    [
        (
            TaskWorkerReadiness(True, False, probe_ok=True),
            {
                "probe_ok": True,
                "execution_worker_ready": True,
                "maintenance_worker_ready": False,
            },
        ),
        (
            TaskWorkerReadiness(False, False, probe_ok=False),
            {
                "probe_ok": False,
                "execution_worker_ready": False,
                "maintenance_worker_ready": False,
            },
        ),
    ],
    ids=["probe-ok", "probe-failed"],
)
async def test_an_admin_reads_the_workers_state_without_flows_and_without_tenant_data(
    client: AsyncClient,
    db_container,
    admin_user,
    admin_headers,
    monkeypatch,
    readiness,
    expected,
):
    await _set_tenant_row(db_container, admin_user.tenant_id, enabled=False)
    monkeypatch.setattr(
        "eneo.settings.settings_router.load_task_worker_readiness",
        AsyncMock(return_value=readiness),
    )

    response = await client.get(WORKERS, headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json() == expected


async def test_only_an_admin_with_an_admin_key_reads_the_workers_state(
    client: AsyncClient,
    db_container,
    admin_user,
    user_factory,
    patch_auth_service_jwt,
    monkeypatch,
):
    _ = patch_auth_service_jwt
    monkeypatch.setattr(
        "eneo.settings.settings_router.load_task_worker_readiness",
        AsyncMock(return_value=TaskWorkerReadiness(True, True, probe_ok=True)),
    )
    async with db_container() as container:
        session = container.session()
        member = await user_factory(session)
        role = Roles(
            name="flow-runner",
            permissions=["flows_view", "flows_run"],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=member.id, role_id=role.id)
        )
        member_in_db = await container.user_repo().get_user_by_id(member.id)
        token = container.auth_service().create_access_token_for_user(member_in_db)
        write_key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            permission="write",
        )
        admin_key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )

    anonymous = await client.get(WORKERS)
    member_response = await client.get(
        WORKERS, headers={"Authorization": f"Bearer {token}"}
    )
    key_response = await client.get(WORKERS, headers={"X-API-Key": write_key.key})
    admin_key_response = await client.get(WORKERS, headers={"X-API-Key": admin_key.key})

    assert anonymous.status_code == 401, anonymous.text
    assert member_response.status_code == 403, member_response.text
    assert key_response.status_code == 403, key_response.text
    assert admin_key_response.status_code == 200, admin_key_response.text
