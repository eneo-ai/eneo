"""The nightly API key maintenance, run against a real database.

Every check reads committed rows in a new session. The expiry and race
tests also sign in with the key, because sign-in judges a key by its dates,
never by the stored ``state``; the isolation and limit tests use keys that
cannot sign in and read the stored state.

The last tests pin the lock a change to a key takes, beside the rows that
point to the key.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
    ApiKeyStateReasonCode,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2InDB,
)
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.feature_flag_table import GlobalFeatureFlag
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.main.container.container import Container
from eneo.sessions.session import SessionAdd, SessionInDB
from eneo.tenants.tenant import TenantBase
from tests.integration.fixtures.locks import (
    finishes_beside,
    wait_until_blocked,
    wait_until_blocked_by,
)

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
    assert update_failed, "the job's update raised"
    assert isinstance(failure.value, DBAPIError)
    assert failure.value.connection_invalidated
    assert await expired_ids(db_container, [first, second]) == set()


async def test_an_unreachable_database_fails_the_job():
    async def refuse():
        raise ConnectionRefusedError("connection refused")

    engine = create_async_engine("postgresql+asyncpg://", async_creator=refuse)
    # As the worker opens it: no autobegin, a transaction begun before the run
    # and no statement yet, so the run makes the first connection attempt.
    maker = async_sessionmaker(bind=engine, autobegin=False)
    try:
        with pytest.raises(ConnectionRefusedError):
            async with maker() as session, session.begin():
                container = Container(session=providers.Object(session))
                await container.api_key_maintenance_service().run_daily_maintenance()
    finally:
        await engine.dispose()


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


# Another transaction holding a key the run selected: a revocation, use or
# edit that has not committed yet.


async def run_maintenance_beside_a_lock(db_container) -> dict[str, Any]:
    """Run and commit the job while another transaction holds a key. A job
    that waits for that key gives up after a few seconds and reports it in
    ``errors``, so the test fails instead of hanging."""
    async with db_container() as job:
        await job.session().execute(sa.text("SET LOCAL lock_timeout = '3s'"))
        return await job.api_key_maintenance_service().run_daily_maintenance()


@contextlib.asynccontextmanager
async def holding(db_container, key_id: UUID, tenant_id: UUID) -> AsyncIterator[None]:
    """Hold the key's row lock until the block ends, then release it without
    changing the key."""
    async with db_container() as holder:
        locked = await holder.api_key_v2_repo().get(
            key_id=key_id, tenant_id=tenant_id, for_update=True
        )
        assert locked is not None
        yield


async def test_a_key_another_transaction_holds_is_left_to_the_next_run(
    db_container, admin_user
):
    first, held, last = await insert_due_keys(db_container, admin_user.tenant_id, 3)

    async with holding(db_container, held, admin_user.tenant_id):
        result = await run_maintenance_beside_a_lock(db_container)
        # Committed while the key is still held.
        assert await expired_ids(db_container, [first, held, last]) == {first, last}

    assert result["errors"] == []
    assert result["expired"] == 2
    assert result["selected_unchanged"] == [{"step": "expires_at", "count": 1}]
    assert await audit_rows(db_container, held) == []

    second = await run_maintenance(db_container)

    assert second["errors"] == []
    assert second["expired"] == 1
    assert second["selected_unchanged"] == []
    assert await expired_ids(db_container, [first, held, last]) == {first, held, last}
    assert await audit_actions(db_container, held) == [ActionType.API_KEY_EXPIRED.value]


async def test_a_use_committed_while_the_run_skips_the_key_keeps_it_open(
    db_container, admin_user
):
    """The key can only be selected as unused: it has no end date and no
    grace period, so the use is what keeps it."""
    tenant_id = admin_user.tenant_id
    key_id = await insert_key(
        db_container,
        tenant_id,
        name="unused",
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    await set_unused_days(db_container, tenant_id, 7)

    async with db_container() as using:
        used = await using.api_key_v2_repo().update_last_used_at(
            key_id=key_id,
            tenant_id=tenant_id,
            last_used_at=datetime.now(timezone.utc),
            min_interval_seconds=0,
        )
        assert used is not None
        first = await run_maintenance_beside_a_lock(db_container)

    assert first["errors"] == []
    assert first["auto_expired"] == 0
    assert first["selected_unchanged"] == [
        {"step": "unused", "tenant_id": str(tenant_id), "count": 1}
    ]

    second = await run_maintenance(db_container)

    assert second["errors"] == []
    assert second["auto_expired"] == 0
    assert second["selected_unchanged"] == []
    key = await read_key(db_container, key_id)
    assert key.state == "active"
    assert key.expires_at is None
    assert await audit_rows(db_container, key_id) == []


async def test_an_extension_in_progress_keeps_its_end_date_but_not_an_unused_key(
    client, db_container, token, admin_user
):
    """The run leaves a key being extended alone, so the new end date stands.
    An extension is not a use: the next run still ends the unused key."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key_id, secret = await create_key(
        client, token, name="extending", expires_at=future
    )
    await make_unused(db_container, key_id, days=10)
    await set_unused_days(db_container, admin_user.tenant_id, 7)
    later = datetime.now(timezone.utc) + timedelta(days=60)

    async with db_container() as extending:
        await extending.api_key_lifecycle_service().extend_expiration(
            key_id=key_id, request=ApiKeyExtendRequest(expires_at=later)
        )
        first = await run_maintenance_beside_a_lock(db_container)

    assert first["errors"] == []
    assert first["auto_expired"] == 0
    assert first["selected_unchanged"] == [
        {"step": "unused", "tenant_id": str(admin_user.tenant_id), "count": 1}
    ]
    assert (await read_key(db_container, key_id)).expires_at == later
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, key_id
    )

    second = await run_maintenance(db_container)

    assert second["auto_expired"] == 1
    key = await read_key(db_container, key_id)
    assert key.state == "expired"
    [expired_row] = [
        row
        for row in await audit_rows(db_container, key_id)
        if row.action == ActionType.API_KEY_EXPIRED.value
    ]
    assert expired_row.log_metadata["extra"]["previous_expires_at"] == (
        later.isoformat()
    )
    assert await sign_in_status(client, secret) == 401


async def test_a_held_key_takes_its_place_in_the_selection_limit(
    db_container, admin_user, monkeypatch
):
    """As before, a key the run selects but cannot take counts against the
    selection's limit: the run does not look past the limit for another."""
    monkeypatch.setattr(api_key_maintenance, "API_KEY_MAINTENANCE_BATCH_LIMIT", 2)
    held, taken, beyond = await insert_due_keys(db_container, admin_user.tenant_id, 3)

    async with holding(db_container, held, admin_user.tenant_id):
        result = await run_maintenance_beside_a_lock(db_container)

    assert result["errors"] == []
    assert result["expired"] == 1
    assert result["limit_reached"] == [{"step": "expires_at"}]
    assert result["selected_unchanged"] == [{"step": "expires_at", "count": 1}]
    assert await expired_ids(db_container, [held, taken, beyond]) == {taken}


async def test_keys_left_unchanged_are_counted_apart_from_failures(
    db_container, admin_user, monkeypatch
):
    held, changed, failing, closed = await insert_due_keys(
        db_container, admin_user.tenant_id, 4
    )

    async def revoke_changed() -> None:
        await set_key_columns(
            db_container, changed, revoked_at=datetime.now(timezone.utc)
        )

    after_selection(monkeypatch, changed, revoke_changed)
    fail_with_sql_error(
        monkeypatch, "expire_matching", lambda *_, key, **__: key.id == failing
    )

    async with holding(db_container, held, admin_user.tenant_id):
        result = await run_maintenance_beside_a_lock(db_container)

    assert [error["key_id"] for error in result["errors"]] == [str(failing)]
    # Held and changed together: an update that matches no row cannot tell
    # which of the two it was.
    assert result["selected_unchanged"] == [{"step": "expires_at", "count": 2}]
    assert result["expired"] == 1
    assert await expired_ids(db_container, [held, changed, failing, closed]) == {closed}
    for key_id in (held, changed, failing):
        assert await audit_rows(db_container, key_id) == []
    assert await audit_actions(db_container, closed) == [
        ActionType.API_KEY_EXPIRED.value
    ]


async def test_a_key_that_stopped_matching_is_not_held_until_the_run_commits(
    db_container, admin_user, monkeypatch
):
    """The run locks a key only to change it: a key revoked after selection,
    with the revocation committed before the run's write starts, is left
    unlocked, so its own writers do not wait for the run's commit. A
    revocation committed while the write runs is not covered: Postgres can
    then keep the lock it took before rechecking the row."""
    [key_id] = await insert_due_keys(db_container, admin_user.tenant_id, 1)

    async def revoke() -> None:
        await set_key_columns(
            db_container, key_id, revoked_at=datetime.now(timezone.utc)
        )

    after_selection(monkeypatch, key_id, revoke)
    async with db_container() as job:
        result = await job.api_key_maintenance_service().run_daily_maintenance()
        async with db_container() as writer:
            # Fails at once if the uncommitted run still holds the key.
            await writer.session().execute(
                sa.select(ApiKeysV2.id)
                .where(ApiKeysV2.id == key_id)
                .with_for_update(key_share=True, nowait=True)
            )

    assert result["expired"] == 0
    assert result["errors"] == []


async def test_a_revocation_taking_the_keys_in_the_other_order_does_not_deadlock(
    db_container, admin_user, monkeypatch
):
    """Revoking a scope takes its keys newest first. The run takes keys past
    their end date in an earlier selection than unused keys. With the older
    key past its end date and the newer one unused, the run holds the older
    key when the revocation holds the newer, and each then writes the key the
    other holds."""
    tenant_id = admin_user.tenant_id
    now = datetime.now(timezone.utc)
    assistant_id = uuid4()
    # Used recently, so only its end date selects it.
    older = await insert_key(
        db_container,
        tenant_id,
        name="past-end-date",
        created_at=now - timedelta(days=30),
        expires_at=now - timedelta(days=1),
        last_used_at=now,
    )
    # Never used and without an end date, so only the unused policy selects it.
    newer = await insert_key(
        db_container, tenant_id, name="unused", created_at=now - timedelta(days=20)
    )
    for key_id in (older, newer):
        await set_key_columns(
            db_container,
            key_id,
            scope_type=ApiKeyScopeType.ASSISTANT.value,
            scope_id=assistant_id,
        )
    await set_unused_days(db_container, tenant_id, 7)

    async def revoke_the_assistants_keys(pid: asyncio.Future[int]) -> int:
        async with db_container() as container:
            pid.set_result(
                await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
            )
            return await container.api_key_scope_revoker().revoke_scope(
                scope_type=ApiKeyScopeType.ASSISTANT,
                scope_id=assistant_id,
                reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
            )

    original = ApiKeysV2Repository.list_matching
    revoking: list[asyncio.Task[int]] = []

    async def select_then_let_the_revocation_in(self, *args, **kwargs):
        keys = await original(self, *args, **kwargs)
        if not revoking and any(key.id == newer for key in keys):
            # The run has written the older key. Hand the selection back only
            # once the revocation has written the newer key and waits for the
            # older one, on this run's backend.
            revoker_pid = asyncio.get_running_loop().create_future()
            revoking.append(
                asyncio.create_task(revoke_the_assistants_keys(revoker_pid))
            )
            await wait_until_blocked_by(self.session, revoking[0], revoker_pid)
        return keys

    monkeypatch.setattr(
        ApiKeysV2Repository, "list_matching", select_then_let_the_revocation_in
    )
    result = await run_maintenance_beside_a_lock(db_container)
    [revocation] = revoking

    # The run has committed, so the revocation gets the older key.
    assert await asyncio.wait_for(revocation, timeout=10) == 2
    assert (await read_key(db_container, newer)).revoked_reason_code == (
        ApiKeyStateReasonCode.SCOPE_REMOVED.value
    )
    assert result["errors"] == []
    assert (result["expired"], result["auto_expired"]) == (1, 0)
    assert result["selected_unchanged"] == [
        {"step": "unused", "tenant_id": str(tenant_id), "count": 1}
    ]
    assert ActionType.API_KEY_EXPIRED.value in await audit_actions(db_container, older)
    assert (await read_key(db_container, older)).state == "revoked"

    monkeypatch.setattr(ApiKeysV2Repository, "list_matching", original)
    later = await run_maintenance(db_container)

    assert later["errors"] == []
    assert later["auto_expired"] == 0
    assert later["selected_unchanged"] == []
    newer_key = await read_key(db_container, newer)
    assert newer_key.state == "revoked"
    assert newer_key.revoked_reason_code == ApiKeyStateReasonCode.SCOPE_REMOVED.value
    assert ActionType.API_KEY_EXPIRED.value not in await audit_actions(
        db_container, newer
    )


# A change to a key beside the rows that point to it. Every change reads the
# key locked; a row that points to the key checks it when the row is written.


async def create_conversation(
    db_container, key_id: UUID, pid: asyncio.Future[int]
) -> SessionInDB:
    """Create and commit a conversation the service key owns, as the session
    service does for the key's request."""
    async with db_container() as container:
        pid.set_result(
            await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
        )
        return await container.session_repo().add(
            SessionAdd(name="conversation", api_key_id=key_id)
        )


async def conversation_owner(db_container, conversation_id: UUID) -> UUID | None:
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Sessions.api_key_id).where(Sessions.id == conversation_id)
        )


async def test_a_conversation_is_created_while_its_key_is_renamed(
    db_container, admin_user
):
    """A change that keeps the key's row does not hold back a row that points
    to the key: the conversation commits while the rename is still open."""
    key_id = await insert_key(
        db_container,
        admin_user.tenant_id,
        name="service",
        created_at=datetime.now(timezone.utc),
    )
    pid = asyncio.get_running_loop().create_future()
    creating: asyncio.Task[SessionInDB] | None = None
    try:
        async with db_container() as renaming:
            await renaming.api_key_lifecycle_service().update_key(
                key_id=key_id, request=ApiKeyUpdateRequest(name="renamed")
            )
            creating = asyncio.create_task(
                create_conversation(db_container, key_id, pid)
            )
            conversation = await finishes_beside(renaming.session(), creating, pid)
            assert await conversation_owner(db_container, conversation.id) == key_id
    finally:
        # A failure releases the rename first, so the conversation can finish.
        if creating is not None:
            await asyncio.wait({creating}, timeout=10)

    assert (await read_key(db_container, key_id)).name == "renamed"


async def test_a_rotation_waiting_on_a_revocation_is_refused(db_container, admin_user):
    """Changes of the same key still wait for each other, and the second one
    judges the key as the first one left it."""
    key_id = await insert_key(
        db_container,
        admin_user.tenant_id,
        name="service",
        created_at=datetime.now(timezone.utc),
    )
    pid = asyncio.get_running_loop().create_future()

    async def rotate() -> None:
        async with db_container() as container:
            pid.set_result(
                await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
            )
            await container.api_key_lifecycle_service().rotate_key(key_id=key_id)

    async with db_container() as revoking:
        await revoking.api_key_lifecycle_service().revoke_key(key_id=key_id)
        rotating = asyncio.create_task(rotate())
        await wait_until_blocked_by(revoking.session(), rotating, pid)

    with pytest.raises(ApiKeyValidationError) as refused:
        await rotating
    assert refused.value.status_code == 401
    assert (await read_key(db_container, key_id)).revoked_at is not None
    async with db_container() as container:
        successors = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(ApiKeysV2)
            .where(ApiKeysV2.rotated_from_key_id == key_id)
        )
    assert successors == 0


@pytest.mark.parametrize("committed", [True, False], ids=["committed", "rolled-back"])
async def test_a_conversation_waits_for_its_key_being_deleted(
    db_container, admin_user, monkeypatch, committed
):
    """A conversation for the key, started after the deletion has read the
    key and before it deletes it, waits for the deletion: it fails once the
    key is gone and goes ahead when the deletion rolls back. (A service key
    that already owns a conversation cannot be deleted: the conversation
    would be left without an owner.)"""
    key_id = await insert_key(
        db_container,
        admin_user.tenant_id,
        name="revoked",
        created_at=datetime.now(timezone.utc),
        revoked_at=datetime.now(timezone.utc),
    )
    pid = asyncio.get_running_loop().create_future()
    creating: list[asyncio.Task[SessionInDB]] = []
    delete = ApiKeysV2Repository.delete

    async def delete_once_a_conversation_waits(self, **kwargs):
        creating.append(
            asyncio.create_task(create_conversation(db_container, key_id, pid))
        )
        await wait_until_blocked_by(self.session, creating[0], pid)
        return await delete(self, **kwargs)

    monkeypatch.setattr(ApiKeysV2Repository, "delete", delete_once_a_conversation_waits)
    with contextlib.suppress(_RollBack):
        async with db_container() as deleting:
            await deleting.api_key_lifecycle_service().purge_key(key_id=key_id)
            if not committed:
                raise _RollBack
    [conversation] = creating

    if committed:
        with pytest.raises(IntegrityError, match="violates foreign key constraint"):
            await asyncio.wait_for(conversation, timeout=10)
        async with db_container() as container:
            assert await container.session().get(ApiKeysV2, key_id) is None
    else:
        created = await asyncio.wait_for(conversation, timeout=10)
        assert await conversation_owner(db_container, created.id) == key_id
