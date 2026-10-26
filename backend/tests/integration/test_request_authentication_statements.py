"""Statements that authenticating a request sends, beyond what the route reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.main.config import get_settings

pytestmark = pytest.mark.integration


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


async def _last_used_at(db_container, key_id) -> datetime | None:
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(ApiKeysV2.last_used_at).where(ApiKeysV2.id == key_id)
        )


async def test_a_recently_used_api_key_is_not_written_again(
    client, db_container, admin_user_api_key
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    first = await client.get("/api/v1/jobs/", headers=headers)
    assert first.status_code == 200, first.text
    recorded = await _last_used_at(db_container, admin_user_api_key.id)
    assert recorded is not None

    with _statements() as sent:
        second = await client.get("/api/v1/jobs/", headers=headers)

    assert second.status_code == 200, second.text
    assert not [s for s in sent if s.lstrip().upper().startswith("UPDATE API_KEYS_V2")]
    assert await _last_used_at(db_container, admin_user_api_key.id) == recorded


async def test_a_due_api_key_records_its_use(
    client, db_container, admin_user_api_key
) -> None:
    interval = get_settings().api_key_last_used_min_interval_seconds
    stale = datetime.now(timezone.utc) - timedelta(seconds=interval + 60)
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == admin_user_api_key.id)
            .values(last_used_at=stale)
        )

    response = await client.get(
        "/api/v1/jobs/", headers={"X-API-Key": admin_user_api_key.key}
    )

    assert response.status_code == 200, response.text
    recorded = await _last_used_at(db_container, admin_user_api_key.id)
    assert recorded is not None
    assert recorded > stale + timedelta(seconds=interval)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def test_the_profile_read_loads_its_caller_once(client, admin_token: str) -> None:
    with _statements() as sent:
        response = await client.get(
            "/api/v1/users/me/", headers={"Authorization": f"Bearer {admin_token}"}
        )

    assert response.status_code == 200, response.text
    principal_reads = [s for s in sent if "\nFROM users \n" in s]
    assert len(principal_reads) == 1, principal_reads
