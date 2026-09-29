"""API keys are confined to the tenant that issued them.

A key from one tenant must not read, edit, list or move resources that belong
to another tenant's spaces, whatever its scope or permission level. The
foreign ids used here come from fixtures; the tests establish that
authorization holds once an id is known, not that ids are discoverable.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest

from init_db import add_tenant_user

pytestmark = pytest.mark.usefixtures("resource_permissions_enforcement_off")


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        return await container.user_repo().get_user_by_email("test@example.com")


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(default_user)


@pytest.fixture
async def second_tenant_user(db_container, test_settings):
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name="test_tenant_2",
        quota_limit=1000000,
        user_name="test_user_2",
        user_email="test2@example.com",
        user_password="TenantFixturePass123!",
    )
    conn.close()

    async with db_container() as container:
        return await container.user_repo().get_user_by_email("test2@example.com")


@pytest.fixture
async def second_tenant_token(db_container, patch_auth_service_jwt, second_tenant_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(second_tenant_user)


@pytest.fixture
def resource_permissions_enforcement_off(test_settings):
    """Resource-permission overrides are not under test; keep the scope and
    tenant gates as the only thing standing between the key and the space."""
    from dependency_injector import providers

    from eneo.main.config import get_settings, set_settings
    from eneo.main.container.container import Container
    from eneo.settings.encryption_service import EncryptionService

    original_settings = get_settings()
    override = test_settings.model_copy(
        update={"api_key_enforce_resource_permissions": False}
    )
    set_settings(override)
    Container.encryption_service.reset_last_overriding()
    Container.encryption_service.override(
        providers.Object(EncryptionService(override.encryption_key))
    )

    yield

    set_settings(original_settings)
    Container.encryption_service.reset_last_overriding()
    Container.encryption_service.override(
        providers.Object(EncryptionService(original_settings.encryption_key))
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _key(secret: str) -> dict[str, str]:
    return {"X-API-Key": secret}


async def _create_space(client, *, token: str) -> str:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"space-{uuid4().hex[:8]}"},
        headers=_bearer(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_assistant(client, *, token: str, space_id: str) -> str:
    resp = await client.post(
        "/api/v1/assistants/",
        json={"name": f"asst-{uuid4().hex[:8]}", "space_id": space_id},
        headers=_bearer(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_tenant_key(client, *, token: str, permission: str) -> str:
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": permission,
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": "2099-01-01T00:00:00Z",
        },
        headers=_bearer(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


def _error_code(resp) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        return body.get("code") or (body.get("detail") or {}).get("code")
    return None


# ---------------------------------------------------------------------------
# Reads and writes against another tenant's shared space
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("permission", ["read", "write", "admin"])
async def test_tenant_key_cannot_read_foreign_tenant_shared_space(
    client, bearer_token, second_tenant_token, permission
):
    foreign_space = await _create_space(client, token=second_tenant_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission=permission)

    resp = await client.get(f"/api/v1/spaces/{foreign_space}/", headers=_key(secret))

    assert resp.status_code == 403, resp.text
    assert _error_code(resp) == "insufficient_scope"


async def test_tenant_admin_key_cannot_edit_foreign_tenant_shared_space(
    client, bearer_token, second_tenant_token
):
    foreign_space = await _create_space(client, token=second_tenant_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.patch(
        f"/api/v1/spaces/{foreign_space}/",
        json={"name": "renamed-by-foreign-key"},
        headers=_key(secret),
    )

    assert resp.status_code == 403, resp.text
    check = await client.get(
        f"/api/v1/spaces/{foreign_space}/", headers=_bearer(second_tenant_token)
    )
    assert check.status_code == 200
    assert check.json()["name"] != "renamed-by-foreign-key"


async def test_tenant_key_reads_and_edits_own_tenant_shared_space(client, bearer_token):
    own_space = await _create_space(client, token=bearer_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    read = await client.get(f"/api/v1/spaces/{own_space}/", headers=_key(secret))
    assert read.status_code == 200, read.text

    edit = await client.patch(
        f"/api/v1/spaces/{own_space}/",
        json={"name": "renamed-by-own-key"},
        headers=_key(secret),
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["name"] == "renamed-by-own-key"


async def test_tenant_key_space_listing_excludes_foreign_tenant_spaces(
    client, bearer_token, second_tenant_token
):
    foreign_space = await _create_space(client, token=second_tenant_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.get("/api/v1/spaces/", headers=_key(secret))

    assert resp.status_code == 200, resp.text
    listed = {item["id"] for item in resp.json()["items"]}
    assert foreign_space not in listed


async def test_tenant_key_cannot_read_foreign_tenant_assistant(
    client, bearer_token, second_tenant_token
):
    foreign_space = await _create_space(client, token=second_tenant_token)
    foreign_assistant = await _create_assistant(
        client, token=second_tenant_token, space_id=foreign_space
    )
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.get(
        f"/api/v1/assistants/{foreign_assistant}/", headers=_key(secret)
    )

    assert resp.status_code == 403, resp.text
    assert _error_code(resp) == "insufficient_scope"


# ---------------------------------------------------------------------------
# Transfers never cross the tenant boundary
# ---------------------------------------------------------------------------


async def test_tenant_key_cannot_move_foreign_assistant_into_own_tenant(
    client, bearer_token, second_tenant_token
):
    foreign_space = await _create_space(client, token=second_tenant_token)
    foreign_assistant = await _create_assistant(
        client, token=second_tenant_token, space_id=foreign_space
    )
    own_space = await _create_space(client, token=bearer_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.post(
        f"/api/v1/assistants/{foreign_assistant}/transfer/",
        json={"target_space_id": own_space, "move_resources": False},
        headers=_key(secret),
    )

    assert resp.status_code == 403, resp.text
    still_there = await client.get(
        f"/api/v1/assistants/{foreign_assistant}/",
        headers=_bearer(second_tenant_token),
    )
    assert still_there.status_code == 200, still_there.text
    assert still_there.json()["space_id"] == foreign_space


async def test_tenant_key_cannot_move_own_assistant_into_foreign_tenant(
    client, bearer_token, second_tenant_token
):
    own_space = await _create_space(client, token=bearer_token)
    own_assistant = await _create_assistant(
        client, token=bearer_token, space_id=own_space
    )
    foreign_space = await _create_space(client, token=second_tenant_token)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.post(
        f"/api/v1/assistants/{own_assistant}/transfer/",
        json={"target_space_id": foreign_space, "move_resources": False},
        headers=_key(secret),
    )

    assert resp.status_code in (403, 404), resp.text
    still_there = await client.get(
        f"/api/v1/assistants/{own_assistant}/", headers=_bearer(bearer_token)
    )
    assert still_there.status_code == 200, still_there.text
    assert still_there.json()["space_id"] == own_space


async def test_session_user_cannot_move_own_assistant_into_foreign_tenant(
    client, bearer_token, second_tenant_token
):
    own_space = await _create_space(client, token=bearer_token)
    own_assistant = await _create_assistant(
        client, token=bearer_token, space_id=own_space
    )
    foreign_space = await _create_space(client, token=second_tenant_token)

    resp = await client.post(
        f"/api/v1/assistants/{own_assistant}/transfer/",
        json={"target_space_id": foreign_space, "move_resources": False},
        headers=_bearer(bearer_token),
    )

    assert resp.status_code in (403, 404), resp.text
    still_there = await client.get(
        f"/api/v1/assistants/{own_assistant}/", headers=_bearer(bearer_token)
    )
    assert still_there.json()["space_id"] == own_space


async def test_tenant_key_moves_assistant_between_own_tenant_spaces(
    client, bearer_token
):
    source = await _create_space(client, token=bearer_token)
    target = await _create_space(client, token=bearer_token)
    assistant = await _create_assistant(client, token=bearer_token, space_id=source)
    secret = await _create_tenant_key(client, token=bearer_token, permission="admin")

    resp = await client.post(
        f"/api/v1/assistants/{assistant}/transfer/",
        json={"target_space_id": target, "move_resources": False},
        headers=_key(secret),
    )

    assert resp.status_code == 204, resp.text
    moved = await client.get(
        f"/api/v1/assistants/{assistant}/", headers=_bearer(bearer_token)
    )
    assert moved.json()["space_id"] == target


# ---------------------------------------------------------------------------
# Repository lookups resolve within the caller's tenant
# ---------------------------------------------------------------------------


async def test_space_lookups_do_not_resolve_foreign_tenant_spaces(
    client, db_container, second_tenant_token
):
    from eneo.main.exceptions import NotFoundException

    foreign_space = await _create_space(client, token=second_tenant_token)
    foreign_assistant = await _create_assistant(
        client, token=second_tenant_token, space_id=foreign_space
    )

    async with db_container() as container:
        space_repo = container.space_repo()
        assert await space_repo.one_or_none(foreign_space) is None
        with pytest.raises(NotFoundException):
            await space_repo.get_space_by_assistant(foreign_assistant)


async def test_space_lookups_resolve_own_tenant_spaces(
    client, bearer_token, db_container
):
    own_space = await _create_space(client, token=bearer_token)
    own_assistant = await _create_assistant(
        client, token=bearer_token, space_id=own_space
    )

    async with db_container() as container:
        space_repo = container.space_repo()
        space = await space_repo.one_or_none(own_space)
        assert space is not None and str(space.id) == own_space
        via_assistant = await space_repo.get_space_by_assistant(own_assistant)
        assert str(via_assistant.id) == own_space
