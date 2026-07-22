from uuid import uuid4

import pytest


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_identical_revision_returns_ok_and_changed_revision_returns_created(
    client, admin_token
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    space_response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"skill-revision-contract-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]

    original = {
        "display_name": "Budget support",
        "description": "Answers approved budget questions.",
        "instructions": "Use approved budget sources.",
    }
    create_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={"slug": "budget-support", **original},
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill = create_response.json()
    skill_id = skill["id"]
    original_revision_id = skill["current_revision_id"]

    unchanged_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        json=original,
        headers=headers,
    )
    assert unchanged_response.status_code == 200, unchanged_response.text
    assert unchanged_response.json()["id"] == original_revision_id

    unchanged_history = await client.get(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        headers=headers,
    )
    assert unchanged_history.status_code == 200, unchanged_history.text
    assert unchanged_history.json()["total_count"] == 1

    changed_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        json={**original, "instructions": "Use approved and current budget sources."},
        headers=headers,
    )
    assert changed_response.status_code == 201, changed_response.text
    assert changed_response.json()["revision_number"] == 2
    assert changed_response.json()["id"] != original_revision_id

    changed_history = await client.get(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        headers=headers,
    )
    assert changed_history.status_code == 200, changed_history.text
    assert changed_history.json()["total_count"] == 2
