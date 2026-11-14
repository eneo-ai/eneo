"""The nightly API key maintenance, run against a real database.

Every check reads committed rows in a new session. The expiry and race
tests also sign in with the key, because sign-in judges a key by its dates,
never by the stored ``state``; the isolation and limit tests use keys that
cannot sign in and read the stored state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.schemas.audit_config_schemas import CategoryUpdate
from eneo.authentication import api_key_maintenance
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    ApiKeyExtendRequest,
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2InDB,
)
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.feature_flag_table import GlobalFeatureFlag
from eneo.database.tables.tenant_table import Tenants
from eneo.tenants.tenant import TenantBase
from tests.integration.fixtures.locks import wait_until_blocked

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Any route behind the full API key sign-in chain.
_AUTH_ENDPOINT = "/api/v1/assistants/"


@pytest.fixture
async def token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def create_key(
    client, token: str, *, name: str, expires_at: datetime | None = None
) -> tuple[UUID, str]:
    body: dict[str, object] = {
        "name": name,
        "key_type": "sk_",
        "permission": "read",
        "scope_type": "tenant",
    }
    if expires_at is not None:
        body["expires_at"] = expires_at.isoformat()
    response = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return UUID(payload["api_key"]["id"]), payload["secret"]


async def set_key_columns(db_container, key_id: UUID, **values: Any) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2).where(ApiKeysV2.id == key_id).values(**values)
        )


async def make_unused(db_container, key_id: UUID, *, days: int) -> None:
    then = datetime.now(timezone.utc) - timedelta(days=days)
    await set_key_columns(db_container, key_id, created_at=then, last_used_at=then)


async def set_unused_days(db_container, tenant_id: UUID, days: int | None) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(api_key_policy={"auto_expire_unused_days": days})
        )


async def insert_key(
    db_container, tenant_id: UUID, *, name: str, created_at: datetime, **values: Any
) -> UUID:
    """A service key straight in the table, for runs that never sign in."""
    async with db_container() as container:
        key = await container.api_key_v2_repo().create(
            tenant_id=tenant_id,
            ownership=ApiKeyOwnership.SERVICE.value,
            scope_type=ApiKeyScopeType.TENANT.value,
            permission=ApiKeyPermission.READ.value,
            key_type=ApiKeyType.SK.value,
            key_hash=uuid4().hex,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=ApiKeyType.SK.value,
            key_suffix=uuid4().hex[-8:],
            name=name,
            state=ApiKeyState.ACTIVE.value,
            created_at=created_at,
            **values,
        )
        return key.id


async def insert_due_keys(db_container, tenant_id: UUID, count: int) -> list[UUID]:
    """``count`` keys past their end date, returned oldest first. Each is
    inserted older than the one before, so the job's order cannot come from
    the order of insertion."""
    start = datetime.now(timezone.utc) - timedelta(days=30)
    newest_first = [
        await insert_key(
            db_container,
            tenant_id,
            name=f"due-{index}",
            created_at=start - timedelta(minutes=index),
            expires_at=start + timedelta(days=1),
        )
        for index in range(count)
    ]
    return newest_first[::-1]


async def add_tenant(db_container) -> UUID:
    async with db_container() as container:
        tenant = await container.tenant_repo().add(
            TenantBase(name=f"maintenance-{uuid4().hex[:8]}")
        )
        assert tenant is not None
        return tenant.id


async def run_maintenance(db_container, **context: Any) -> dict[str, Any]:
    async with db_container(**context) as container:
        return await container.api_key_maintenance_service().run_daily_maintenance()


def fail_with_sql_error(monkeypatch, method: str, should_fail) -> None:
    """Make the repository ``method`` raise a real SQL error, which aborts the
    transaction unless a savepoint contains it, whenever ``should_fail`` is
    true for its arguments."""
    original = getattr(ApiKeysV2Repository, method)

    async def failing(self, *args, **kwargs):
        if should_fail(*args, **kwargs):
            await self.session.execute(sa.text("SELECT 1/0"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ApiKeysV2Repository, method, failing)


async def read_key(db_container, key_id: UUID) -> ApiKeyV2InDB:
    async with db_container() as container:
        key = await container.session().scalar(
            sa.select(ApiKeysV2).where(ApiKeysV2.id == key_id)
        )
        return ApiKeyV2InDB.model_validate(key)


async def sign_in_status(client, secret: str) -> int:
    response = await client.get(_AUTH_ENDPOINT, headers={"X-API-Key": secret})
    return response.status_code


async def audit_actions(db_container, key_id: UUID) -> list[str]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(AuditLog.action)
            .where(AuditLog.entity_id == key_id)
            .order_by(AuditLog.timestamp)
        )
        return list(rows)


async def audit_rows(db_container, key_id: UUID) -> list[sa.Row[Any]]:
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(
                AuditLog.action,
                AuditLog.actor_type,
                AuditLog.actor_id,
                AuditLog.log_metadata.label("log_metadata"),
            )
            .where(AuditLog.entity_id == key_id)
            .order_by(AuditLog.timestamp)
        )
        return list(result.all())


async def turn_off_audit_logging_and_admin_actions(
    db_container, tenant_id: UUID
) -> None:
    """What a tenant admin can turn off: audit logging as a whole, and the
    category the job's actions belong to."""
    async with db_container() as container:
        flag_id = await container.session().scalar(
            sa.select(GlobalFeatureFlag.id).where(
                GlobalFeatureFlag.name == "audit_logging_enabled"
            )
        )
        assert flag_id is not None
        await container.feature_flag_service().disable_tenant(
            feature_id=flag_id, tenant_id=tenant_id
        )
        await container.audit_config_service().update_config(
            tenant_id, [CategoryUpdate(category="admin_actions", enabled=False)]
        )
    async with db_container() as container:
        assert not await container.feature_flag_service().check_is_feature_enabled(
            feature_name="audit_logging_enabled", tenant_id=tenant_id
        )


def after_selection(
    monkeypatch, key_id: UUID, action: Callable[[], Awaitable[None]]
) -> None:
    """Run ``action``, committed in its own session, right after the job has
    selected ``key_id`` and before it changes the key."""
    original = ApiKeysV2Repository.list_matching
    pending = True

    async def list_then_act(self, *args, **kwargs):
        nonlocal pending
        keys = await original(self, *args, **kwargs)
        if pending and any(key.id == key_id for key in keys):
            pending = False
            await action()
        return keys

    monkeypatch.setattr(ApiKeysV2Repository, "list_matching", list_then_act)


def pin_job_clock(monkeypatch, at: datetime) -> None:
    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - the job always asks for UTC
            return at

    monkeypatch.setattr(api_key_maintenance, "datetime", PinnedDatetime)


async def test_an_unused_key_with_a_future_end_date_stops_working(
    client, db_container, token, admin_user
):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    unused_id, unused_secret = await create_key(
        client, token, name="unused", expires_at=future
    )
    await make_unused(db_container, unused_id, days=10)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    past_id, _ = await create_key(client, token, name="past", expires_at=past)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    no_policy_tenant = await add_tenant(db_container)
    unused_without_policy = await insert_key(
        db_container,
        no_policy_tenant,
        name="unused-without-policy",
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    assert await sign_in_status(client, unused_secret) == 200
    await make_unused(db_container, unused_id, days=10)

    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 1
    # Without a policy, an unused key stays active.
    assert (await read_key(db_container, unused_without_policy)).state == "active"
    assert result["expired"] == 1
    unused = await read_key(db_container, unused_id)
    assert unused.state == "expired"
    assert unused.expires_at <= datetime.now(timezone.utc)
    assert await sign_in_status(client, unused_secret) == 401
    # A key whose end date had already passed keeps that date.
    assert (await read_key(db_container, past_id)).expires_at == past


async def rotate(client, token: str, key_id: UUID) -> tuple[UUID, str]:
    response = await client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return UUID(payload["api_key"]["id"]), payload["secret"]


async def test_a_rotated_key_is_revoked_when_its_grace_period_ends(
    client, db_container, token
):
    old_id, old_secret = await create_key(client, token, name="rotated")
    new_id, new_secret = await rotate(client, token, old_id)
    ended = datetime.now(timezone.utc) - timedelta(minutes=1)
    await set_key_columns(db_container, old_id, rotation_grace_until=ended)

    result = await run_maintenance(db_container)

    assert result["rotation_revoked"] == 1
    old = await read_key(db_container, old_id)
    assert old.state == "revoked"
    assert old.revoked_reason_code == "rotation_completed"
    assert old.rotation_grace_until == ended
    assert await sign_in_status(client, old_secret) == 401
    assert await sign_in_status(client, new_secret) == 200
    assert (await read_key(db_container, new_id)).state == "active"


async def test_a_key_used_after_selection_keeps_working(
    client, db_container, token, admin_user, monkeypatch
):
    used_id, used_secret = await create_key(client, token, name="used")
    idle_id, idle_secret = await create_key(client, token, name="idle")
    await make_unused(db_container, used_id, days=10)
    await make_unused(db_container, idle_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)

    async def use() -> None:
        assert await sign_in_status(client, used_secret) == 200

    after_selection(monkeypatch, used_id, use)
    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 1
    used = await read_key(db_container, used_id)
    assert used.state == "active"
    assert await sign_in_status(client, used_secret) == 200
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, used_id
    )
    assert await sign_in_status(client, idle_secret) == 401


async def test_a_key_revoked_after_selection_keeps_its_revocation(
    client, db_container, token, admin_user, monkeypatch
):
    key_id, secret = await create_key(client, token, name="revoked")
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)

    async def revoke() -> None:
        response = await client.post(
            f"/api/v1/api-keys/{key_id}/revoke",
            json={"reason_code": "key_compromised", "reason_text": "Leaked"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

    after_selection(monkeypatch, key_id, revoke)
    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 0
    key = await read_key(db_container, key_id)
    assert key.state == "revoked"
    assert key.revoked_reason_code == "key_compromised"
    assert key.revoked_reason_text == "Leaked"
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, key_id
    )
    assert await sign_in_status(client, secret) == 401


async def test_a_key_extended_after_selection_keeps_its_new_end_date(
    client, db_container, token, admin_user, monkeypatch
):
    """Still unused after the extension, so only the check that the end date
    is the one the job selected keeps the job from ending it."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key_id, secret = await create_key(client, token, name="extended", expires_at=future)
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    later = datetime.now(timezone.utc) + timedelta(days=60)

    after_selection(monkeypatch, key_id, _extend(db_container, key_id, later))
    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 0
    key = await read_key(db_container, key_id)
    assert key.expires_at == later
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, key_id
    )
    assert await sign_in_status(client, secret) == 200


async def test_a_new_grace_period_after_selection_keeps_the_old_key_working(
    client, db_container, token, monkeypatch
):
    """A key inside its grace period can be rotated again, which moves the
    grace period; a run that selected it under the earlier period must not
    revoke it."""
    old_id, old_secret = await create_key(client, token, name="rotating")
    await rotate(client, token, old_id)
    now = datetime.now(timezone.utc)
    await set_key_columns(
        db_container, old_id, rotation_grace_until=now + timedelta(hours=1)
    )
    pin_job_clock(monkeypatch, now + timedelta(hours=2))

    async def rotate_again() -> None:
        await rotate(client, token, old_id)

    after_selection(monkeypatch, old_id, rotate_again)
    result = await run_maintenance(db_container)

    assert result["rotation_revoked"] == 0
    old = await read_key(db_container, old_id)
    assert old.revoked_at is None
    assert old.rotation_grace_until is not None
    assert old.rotation_grace_until > now + timedelta(hours=2)
    assert ActionType.API_KEY_REVOKED.value not in await audit_actions(
        db_container, old_id
    )
    assert await sign_in_status(client, old_secret) == 200


async def expired_ids(db_container, key_ids: list[UUID]) -> set[UUID]:
    return {
        key_id
        for key_id in key_ids
        if (await read_key(db_container, key_id)).state == "expired"
    }


async def test_a_failing_key_does_not_stop_the_others(
    db_container, admin_user, monkeypatch
):
    first, middle, last = await insert_due_keys(db_container, admin_user.tenant_id, 3)
    fail_with_sql_error(
        monkeypatch, "expire_matching", lambda *_, key, **__: key.id == middle
    )

    result = await run_maintenance(db_container)

    assert result["expired"] == 2
    assert result["errors"] == [
        {
            "step": "expires_at",
            "key_id": str(middle),
            "tenant_id": str(admin_user.tenant_id),
            "error": "DBAPIError",
        }
    ]
    assert await expired_ids(db_container, [first, middle, last]) == {first, last}


async def test_a_failing_selection_stops_only_its_step(
    client, db_container, token, admin_user, monkeypatch
):
    due = await insert_due_keys(db_container, admin_user.tenant_id, 1)
    # Recently used, so only the failing expiry step would take it.
    await set_key_columns(db_container, due[0], last_used_at=datetime.now(timezone.utc))
    unused_id, _ = await create_key(client, token, name="unused")
    await make_unused(db_container, unused_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    calls = 0

    def first_call(*_args, **_kwargs) -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    fail_with_sql_error(monkeypatch, "list_matching", first_call)

    result = await run_maintenance(db_container)

    assert result["expired"] == 0
    assert result["auto_expired"] == 1
    assert result["errors"] == [{"step": "expires_at", "error": "DBAPIError"}]
    assert await expired_ids(db_container, [*due, unused_id]) == {unused_id}


async def test_a_tenant_that_cannot_be_loaded_does_not_stop_the_others(
    client, db_container, token, admin_user
):
    unused_id, _ = await create_key(client, token, name="unused")
    await make_unused(db_container, unused_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    broken_id = await add_tenant(db_container)
    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
        # A state the tenant model refuses, as if written outside the app.
        await container.session().execute(
            sa.update(Tenants).where(Tenants.id == broken_id).values(state="bogus")
        )

    result = await run_maintenance(db_container, user=admin_user, tenant=tenant)

    async with db_container(user=admin_user, tenant=tenant) as container:
        await container.session().execute(
            sa.update(Tenants).where(Tenants.id == broken_id).values(state="active")
        )
    assert result["auto_expired"] == 1
    assert result["errors"] == [
        {"step": "unused", "tenant_id": str(broken_id), "error": "ValidationError"}
    ]
    assert await expired_ids(db_container, [unused_id]) == {unused_id}


async def test_a_policy_out_of_range_stops_only_its_tenant(db_container, admin_user):
    """A number of days the tenant could save but that reaches before year 1
    fails that tenant's cutoff, not the night's run."""
    old = datetime.now(timezone.utc) - timedelta(days=30)
    broken_id = await add_tenant(db_container)
    await set_unused_days(db_container, broken_id, 1_000_000)
    await insert_key(db_container, broken_id, name="unused-broken", created_at=old)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    unused_id = await insert_key(
        db_container, admin_user.tenant_id, name="unused", created_at=old
    )
    rotated_id = await insert_key(
        db_container,
        admin_user.tenant_id,
        name="rotated",
        created_at=old,
        last_used_at=datetime.now(timezone.utc),
        rotation_grace_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    result = await run_maintenance(db_container)

    assert result["auto_expired"] == 1
    assert result["rotation_revoked"] == 1
    assert result["errors"] == [
        {"step": "unused", "tenant_id": str(broken_id), "error": "OverflowError"}
    ]
    assert await expired_ids(db_container, [unused_id]) == {unused_id}
    assert (await read_key(db_container, rotated_id)).state == "revoked"


async def test_more_keys_than_the_limit_are_taken_over_several_runs(
    db_container, admin_user, monkeypatch
):
    monkeypatch.setattr(api_key_maintenance, "API_KEY_MAINTENANCE_BATCH_LIMIT", 3)
    always_failing, *rest = await insert_due_keys(db_container, admin_user.tenant_id, 5)
    fail_with_sql_error(
        monkeypatch, "expire_matching", lambda *_, key, **__: key.id == always_failing
    )

    first = await run_maintenance(db_container)

    assert first["expired"] == 2
    assert first["limit_reached"] == [{"step": "expires_at"}]
    assert [error["key_id"] for error in first["errors"]] == [str(always_failing)]
    assert await expired_ids(db_container, rest) == set(rest[:2])

    second = await run_maintenance(db_container)

    assert second["expired"] == 2
    assert second["limit_reached"] == [{"step": "expires_at"}]
    assert await expired_ids(db_container, rest) == set(rest)


async def test_the_limit_for_unused_keys_applies_per_tenant(
    db_container, admin_user, monkeypatch
):
    monkeypatch.setattr(api_key_maintenance, "API_KEY_MAINTENANCE_BATCH_LIMIT", 2)
    other_tenant = await add_tenant(db_container)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    keys: dict[UUID, list[UUID]] = {}
    for tenant_id, count in ((admin_user.tenant_id, 3), (other_tenant, 1)):
        await set_unused_days(db_container, tenant_id, 7)
        keys[tenant_id] = [
            await insert_key(
                db_container,
                tenant_id,
                name=f"unused-{index}",
                created_at=old + timedelta(minutes=index),
            )
            for index in range(count)
        ]

    result = await run_maintenance(db_container)

    # A limit per step would have stopped at two keys in all.
    assert result["auto_expired"] == 3
    assert result["limit_reached"] == [
        {"step": "unused", "tenant_id": str(admin_user.tenant_id)}
    ]
    assert result["errors"] == []
    assert await expired_ids(db_container, keys[admin_user.tenant_id]) == set(
        keys[admin_user.tenant_id][:2]
    )
    assert await expired_ids(db_container, keys[other_tenant]) == set(
        keys[other_tenant]
    )


async def test_a_lost_connection_fails_the_job_and_keeps_nothing(
    db_container, admin_user, monkeypatch
):
    first, second = await insert_due_keys(db_container, admin_user.tenant_id, 2)
    original = ApiKeysV2Repository.expire_matching
    update_failed = False

    async def drop_connection_at_second(self, condition, *, key, **kwargs):
        nonlocal update_failed
        if key.id == second:
            pid = await self.session.scalar(sa.text("SELECT pg_backend_pid()"))
            async with db_container() as other:
                await other.session().execute(
                    sa.text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                )
        try:
            return await original(self, condition, key=key, **kwargs)
        except DBAPIError:
            update_failed = True
            raise

    monkeypatch.setattr(
        ApiKeysV2Repository, "expire_matching", drop_connection_at_second
    )

    with pytest.raises(DBAPIError) as failure:
        await run_maintenance(db_container)

    # The run stops at the first statement on the dead connection instead of
    # reporting it as one key's error and going on.
    assert update_failed, "the error must come from the job's update, not its commit"
    assert isinstance(failure.value, DBAPIError)
    assert failure.value.connection_invalidated
    assert await expired_ids(db_container, [first, second]) == set()


async def test_every_transition_is_audited_even_with_the_action_turned_off(
    client, db_container, token, admin_user
):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    unused_id, _ = await create_key(client, token, name="unused", expires_at=future)
    await make_unused(db_container, unused_id, days=10)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    past_id, _ = await create_key(client, token, name="past", expires_at=past)
    rotated_id, _ = await create_key(client, token, name="rotated")
    await rotate(client, token, rotated_id)
    grace_ended = datetime.now(timezone.utc) - timedelta(minutes=1)
    await set_key_columns(db_container, rotated_id, rotation_grace_until=grace_ended)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    await turn_off_audit_logging_and_admin_actions(db_container, admin_user.tenant_id)

    result = await run_maintenance(db_container)

    assert (result["expired"], result["auto_expired"], result["rotation_revoked"]) == (
        1,
        1,
        1,
    )
    [unused_row] = await audit_rows(db_container, unused_id)
    assert unused_row.action == ActionType.API_KEY_EXPIRED.value
    assert unused_row.actor_type == "system"
    assert unused_row.actor_id is None
    extra = unused_row.log_metadata["extra"]
    assert extra["reason"] == "unused"
    assert extra["days"] == "7"
    assert extra["previous_expires_at"] == future.isoformat()
    assert datetime.fromisoformat(extra["expires_at"]) <= datetime.now(timezone.utc)

    [past_row] = await audit_rows(db_container, past_id)
    assert past_row.log_metadata["extra"]["reason"] == "expires_at"
    assert past_row.log_metadata["extra"]["expires_at"] == past.isoformat()

    rotated_rows = [
        row
        for row in await audit_rows(db_container, rotated_id)
        if row.action == ActionType.API_KEY_REVOKED.value
    ]
    assert len(rotated_rows) == 1
    assert rotated_rows[0].actor_type == "system"
    assert rotated_rows[0].log_metadata["extra"] == {
        "reason_code": "rotation_completed",
        "rotation_grace_until": grace_ended.isoformat(),
    }


async def test_a_transition_rolled_back_with_its_audit_row_leaves_neither(
    db_container, admin_user, monkeypatch
):
    [key_id] = await insert_due_keys(db_container, admin_user.tenant_id, 1)
    original = AuditService.log

    async def log_then_fail(self, **kwargs):
        written = await original(self, **kwargs)
        await self.repository.session.execute(sa.text("SELECT 1/0"))
        return written

    monkeypatch.setattr(AuditService, "log", log_then_fail)

    result = await run_maintenance(db_container)

    assert result["expired"] == 0
    assert [error["key_id"] for error in result["errors"]] == [str(key_id)]
    assert (await read_key(db_container, key_id)).state == "active"
    assert await audit_rows(db_container, key_id) == []


async def test_keys_recorded_as_expired_but_still_working_are_closed(
    client, db_container, token, admin_user
):
    """Earlier runs recorded unused keys as expired but left a later end
    date, and an extension could clear the date of such a key. Whatever the
    policy says now, the next run ends their access, once."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    dated_id, dated_secret = await create_key(client, token, name="dated")
    open_id, open_secret = await create_key(client, token, name="open")
    await set_key_columns(db_container, dated_id, state="expired", expires_at=future)
    await set_key_columns(db_container, open_id, state="expired", expires_at=None)
    await set_unused_days(db_container, admin_user.tenant_id, None)
    assert await sign_in_status(client, dated_secret) == 200
    assert await sign_in_status(client, open_secret) == 200

    first = await run_maintenance(db_container)

    assert first["expired_state_closed"] == 2
    assert first["errors"] == []
    assert await sign_in_status(client, dated_secret) == 401
    assert await sign_in_status(client, open_secret) == 401
    for key_id, previous in ((dated_id, future.isoformat()), (open_id, None)):
        key = await read_key(db_container, key_id)
        assert key.state == "expired"
        assert key.expires_at is not None
        assert key.expires_at <= datetime.now(timezone.utc)
        [row] = await audit_rows(db_container, key_id)
        assert row.action == ActionType.API_KEY_EXPIRED.value
        assert row.actor_type == "system"
        extra = row.log_metadata["extra"]
        assert extra["reason"] == "stale_expired_state"
        assert extra["previous_expires_at"] == previous
        assert extra["expires_at"] == key.expires_at.isoformat()

    second = await run_maintenance(db_container)

    assert second["expired_state_closed"] == 0
    assert second["expired"] == 0
    assert len(await audit_rows(db_container, dated_id)) == 1
    assert len(await audit_rows(db_container, open_id)) == 1


class _RollBack(Exception):
    pass


def _extend(db_container, key_id: UUID, until: datetime):
    async def change() -> None:
        async with db_container() as container:
            await container.api_key_lifecycle_service().extend_expiration(
                key_id=key_id, request=ApiKeyExtendRequest(expires_at=until)
            )

    return change


def _edit(db_container, key_id: UUID, until: datetime):
    async def change() -> None:
        async with db_container() as container:
            await container.api_key_lifecycle_service().update_key(
                key_id=key_id, request=ApiKeyUpdateRequest(expires_at=until)
            )

    return change


@pytest.mark.parametrize("change", [_extend, _edit], ids=["extend", "edit"])
async def test_a_change_during_the_run_does_not_reopen_the_key(
    client, db_container, token, admin_user, change
):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key_id, secret = await create_key(client, token, name="unused", expires_at=future)
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    later = datetime.now(timezone.utc) + timedelta(days=60)

    async with db_container() as job:
        result = await job.api_key_maintenance_service().run_daily_maintenance()
        assert result["auto_expired"] == 1
        # Written, not committed: everyone else still sees an active key.
        assert (await read_key(db_container, key_id)).expires_at == future
        racer = asyncio.create_task(change(db_container, key_id, later)())
        await wait_until_blocked(job.session(), racer)

    with pytest.raises(ApiKeyValidationError) as refused:
        await racer
    assert refused.value.status_code == 400
    key = await read_key(db_container, key_id)
    assert key.state == "expired"
    assert key.expires_at is not None
    assert key.expires_at <= datetime.now(timezone.utc)
    assert await sign_in_status(client, secret) == 401


async def test_a_change_waiting_on_a_run_that_rolls_back_goes_ahead(
    client, db_container, token, admin_user
):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key_id, secret = await create_key(client, token, name="unused", expires_at=future)
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    later = datetime.now(timezone.utc) + timedelta(days=60)

    with pytest.raises(_RollBack):
        async with db_container() as job:
            await job.api_key_maintenance_service().run_daily_maintenance()
            racer = asyncio.create_task(_extend(db_container, key_id, later)())
            await wait_until_blocked(job.session(), racer)
            raise _RollBack

    await racer
    key = await read_key(db_container, key_id)
    assert key.state == "active"
    assert key.expires_at == later
    assert await sign_in_status(client, secret) == 200
