"""Connection checks and key expiry on model providers, against a real database."""

from collections.abc import Callable
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.model_providers_table import ModelProviders
from eneo.model_providers.domain.connection_check import ConnectionCheck
from eneo.model_providers.infrastructure import provider_connection_probe
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from eneo.users.user import UserAdd, UserState

KEY = "sk-live-secret-1234"
PROVIDERS = "/api/v1/admin/model-providers/"


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("test@example.com")
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def regular_user_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user_repo = container.user_repo()
        admin = await user_repo.get_user_by_email("test@example.com")
        user = await user_repo.add(
            UserAdd(
                email=f"regular-provider-{uuid4().hex[:8]}@example.com",
                username=f"reg_provider_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
def provider_answers(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Make the provider API answer every connection check with a status."""

    def answer(status_code: int) -> None:
        body = {"error": {"message": f"Incorrect API key provided: {KEY}"}}
        monkeypatch.setattr(
            provider_connection_probe,
            "_http_client",
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(status_code, json=body)
                )
            ),
        )

    return answer


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_provider(client, token: str, **extra: object) -> dict:
    response = await client.post(
        PROVIDERS,
        headers=_auth(token),
        json={
            "name": f"OpenAI {uuid4().hex[:6]}",
            "provider_type": "openai",
            "credentials": {"api_key": KEY},
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _listed(client, token: str, provider_id: str) -> dict:
    response = await client.get(PROVIDERS, headers=_auth(token))
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["id"] == provider_id)


async def _row(db_session, provider_id: str) -> sa.Row:
    """The stored connection columns and credentials, read after commit."""
    async with db_session() as session:
        return (
            await session.execute(
                sa.select(
                    ModelProviders.connection_status,
                    ModelProviders.connection_error,
                    ModelProviders.connection_checked_at,
                    ModelProviders.credentials,
                ).where(ModelProviders.id == UUID(provider_id))
            )
        ).one()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_key_expiry_round_trips_through_create_update_and_list(
    client, admin_token
):
    created = await _create_provider(client, admin_token, key_expires_on="2026-10-12")

    assert created["key_expires_on"] == "2026-10-12"
    assert created["connection_check"] is None
    assert created["connection_check_supported"] is True
    assert (await _listed(client, admin_token, created["id"]))["key_expires_on"] == (
        "2026-10-12"
    )

    path = f"{PROVIDERS}{created['id']}/"
    renamed = await client.put(path, headers=_auth(admin_token), json={"name": "Byt"})
    assert renamed.json()["key_expires_on"] == "2026-10-12"

    moved = await client.put(
        path, headers=_auth(admin_token), json={"key_expires_on": "2027-01-31"}
    )
    assert moved.json()["key_expires_on"] == "2027-01-31"

    cleared = await client.put(
        path, headers=_auth(admin_token), json={"key_expires_on": None}
    )
    assert cleared.json()["key_expires_on"] is None
    assert (await _listed(client, admin_token, created["id"]))["key_expires_on"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_result_is_stored_without_secrets_and_cleared_by_a_new_key(
    client, admin_token, db_session, provider_answers
):
    created = await _create_provider(client, admin_token)
    check_path = f"{PROVIDERS}{created['id']}/connection-check/"

    provider_answers(401)
    response = await client.post(check_path, headers=_auth(admin_token))

    assert response.status_code == 200, response.text
    failed = response.json()["connection_check"]
    assert failed["status"] == "failed"
    assert failed["error"] == "authentication_failed"
    assert failed["checked_at"]
    assert KEY not in response.text
    assert "Incorrect API key" not in response.text
    assert (await _listed(client, admin_token, created["id"]))["connection_check"] == (
        failed
    )
    row = await _row(db_session, created["id"])
    assert (row.connection_status, row.connection_error) == (
        "failed",
        "authentication_failed",
    )
    assert KEY not in str(row.credentials)

    # An edit that keeps the key keeps the result; a new key clears it.
    provider_answers(200)
    await client.post(check_path, headers=_auth(admin_token))
    path = f"{PROVIDERS}{created['id']}/"
    renamed = await client.put(path, headers=_auth(admin_token), json={"name": "Byt"})
    assert renamed.json()["connection_check"]["status"] == "ok"

    rekeyed = await client.put(
        path,
        headers=_auth(admin_token),
        json={"credentials": {"api_key": "sk-new-key-5678"}},
    )
    assert rekeyed.json()["connection_check"] is None
    row = await _row(db_session, created["id"])
    assert row.connection_status is None and row.connection_checked_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_admins_can_run_a_check(
    client, admin_token, regular_user_token, db_session, provider_answers
):
    created = await _create_provider(client, admin_token)
    provider_answers(200)

    for action in ("connection-check", "test"):
        response = await client.post(
            f"{PROVIDERS}{created['id']}/{action}/",
            headers=_auth(regular_user_token),
        )
        assert response.status_code == 403, response.text

    assert (await _row(db_session, created["id"])).connection_status is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_result_for_replaced_credentials_is_dropped(
    client, admin_token, db_session, admin_user
):
    created = await _create_provider(client, admin_token)
    provider_id = UUID(created["id"])

    async with db_session() as session:
        repository = ModelProviderRepository(session, admin_user.tenant_id)
        tested = await repository.get_by_id(provider_id)
        # Another admin saves a new key while the check is running.
        await session.execute(
            sa.update(ModelProviders)
            .where(ModelProviders.id == provider_id)
            .values(credentials={"api_key": "replaced"})
        )

        stored = await repository.record_connection_check(tested, ConnectionCheck.ok())

    assert stored.connection_check is None
    assert (await _row(db_session, created["id"])).connection_status is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_database_refuses_a_status_without_its_time(
    client, admin_token, db_session
):
    created = await _create_provider(client, admin_token)

    with pytest.raises(IntegrityError):
        async with db_session() as session:
            await session.execute(
                sa.update(ModelProviders)
                .where(ModelProviders.id == UUID(created["id"]))
                .values(connection_status="failed")
            )
