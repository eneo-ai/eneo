"""Statements that authenticating a request sends, beyond what the route reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.main.config import get_settings

pytestmark = pytest.mark.integration

ME = "/api/v1/users/me/"


@contextmanager
def _statements() -> Iterator[list[str]]:
    sent: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany) -> None:
        sent.append(statement)

    sa.event.listen(Engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        sa.event.remove(Engine, "before_cursor_execute", record)


def _minted(key) -> sa.ColumnElement[bool]:
    return ApiKeysV2.key_suffix == key.truncated_key


async def _last_used_at(db_container, key) -> datetime | None:
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(ApiKeysV2.last_used_at).where(_minted(key))
        )


async def test_a_recently_used_api_key_is_not_written_again(
    client, db_container, admin_user_api_key
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    first = await client.get("/api/v1/jobs/", headers=headers)
    assert first.status_code == 200, first.text
    recorded = await _last_used_at(db_container, admin_user_api_key)
    assert recorded is not None

    with _statements() as sent:
        second = await client.get("/api/v1/jobs/", headers=headers)

    assert second.status_code == 200, second.text
    assert not [s for s in sent if s.lstrip().upper().startswith("UPDATE API_KEYS_V2")]
    assert await _last_used_at(db_container, admin_user_api_key) == recorded


async def test_a_due_api_key_records_its_use(
    client, db_container, admin_user_api_key
) -> None:
    interval = get_settings().api_key_last_used_min_interval_seconds
    stale = datetime.now(timezone.utc) - timedelta(seconds=interval + 60)
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2)
            .where(_minted(admin_user_api_key))
            .values(last_used_at=stale)
        )

    response = await client.get(
        "/api/v1/jobs/", headers={"X-API-Key": admin_user_api_key.key}
    )

    assert response.status_code == 200, response.text
    recorded = await _last_used_at(db_container, admin_user_api_key)
    assert recorded is not None
    assert recorded > stale + timedelta(seconds=interval)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def test_the_profile_read_loads_its_caller_once(client, admin_token: str) -> None:
    with _statements() as sent:
        response = await client.get(
            ME, headers={"Authorization": f"Bearer {admin_token}"}
        )

    assert response.status_code == 200, response.text
    principal_reads = [s for s in sent if "\nFROM users \n" in s]
    assert len(principal_reads) == 1, principal_reads


async def _service_key_secret(client, admin_token: str) -> str:
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    created = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"svc-key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "admin",
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": expires,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    return created.json()["secret"]


async def test_the_profile_read_refuses_each_principal_as_before(
    client, admin_token: str, admin_user, admin_user_api_key
) -> None:
    service_secret = await _service_key_secret(client, admin_token)

    bearer = await client.get(ME, headers={"Authorization": f"Bearer {admin_token}"})
    user_key = await client.get(ME, headers={"X-API-Key": admin_user_api_key.key})
    service_key = await client.get(ME, headers={"X-API-Key": service_secret})
    unknown_key = await client.get(ME, headers={"X-API-Key": "sk_" + "0" * 48})
    anonymous = await client.get(ME)

    assert bearer.status_code == 200, bearer.text
    assert bearer.json()["id"] == str(admin_user.id)
    assert user_key.status_code == 200, user_key.text
    assert user_key.json()["id"] == str(admin_user.id)
    assert service_key.status_code == 403, service_key.text
    assert service_key.json()["detail"]["code"] == "user_identity_required"
    assert unknown_key.status_code == 401, unknown_key.text
    assert anonymous.status_code == 401, anonymous.text
