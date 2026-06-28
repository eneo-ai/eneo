"""Integration tests for the prompt_library admin endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.users.user import UserAdd, UserState


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(user)


@pytest.fixture
async def regular_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        admin = await user_repo.get_user_by_email("test@example.com")
        return await user_repo.add(
            UserAdd(
                email=f"regular-prompt-lib-{uuid4().hex[:8]}@example.com",
                username=f"reg_prompt_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )


@pytest.fixture
async def regular_user_token(db_container, regular_user, patch_auth_service_jwt):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(regular_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_full_crud_round_trip(client, admin_token):
    create_resp = await client.post(
        "/api/v1/admin/prompt-library/",
        json={"name": "My Prompt", "description": "desc", "text": "be nice"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    payload = create_resp.json()
    entry_id = payload["id"]
    assert payload["name"] == "My Prompt"
    assert payload["text"] == "be nice"
    assert payload["current_version"] == 1

    list_resp = await client.get(
        "/api/v1/admin/prompt-library/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    names = [item["name"] for item in list_resp.json()["items"]]
    assert "My Prompt" in names

    get_resp = await client.get(
        f"/api/v1/admin/prompt-library/{entry_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["text"] == "be nice"

    update_resp = await client.put(
        f"/api/v1/admin/prompt-library/{entry_id}/",
        json={"name": "Renamed", "text": "be very nice"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["name"] == "Renamed"
    assert update_resp.json()["text"] == "be very nice"
    assert update_resp.json()["current_version"] == 2

    versions_resp = await client.get(
        f"/api/v1/admin/prompt-library/{entry_id}/versions/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert versions_resp.status_code == 200, versions_resp.text
    versions = versions_resp.json()["items"]
    assert [version["version"] for version in versions] == [2, 1]
    assert versions[0]["text"] == "be very nice"
    assert versions[1]["text"] == "be nice"

    delete_resp = await client.delete(
        f"/api/v1/admin/prompt-library/{entry_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_resp.status_code == 204

    get_after_delete = await client.get(
        f"/api/v1/admin/prompt-library/{entry_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_after_delete.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_admin_gets_403(client, regular_user_token):
    resp = await client.get(
        "/api/v1/admin/prompt-library/",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_name_returns_400(client, admin_token):
    first = await client.post(
        "/api/v1/admin/prompt-library/",
        json={"name": "dup-test-A", "text": "x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/admin/prompt-library/",
        json={"name": "dup-test-A", "text": "y"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second.status_code == 400, second.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_unknown_id_returns_404(client, admin_token):
    resp = await client.get(
        f"/api/v1/admin/prompt-library/{uuid4()}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
