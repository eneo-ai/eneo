from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tests.integration.fixtures.transaction_boundary import (
    request_at_transaction_boundary,
)


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_organization_identical_revision_is_a_noop_http_contract(
    client, admin_token
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    original = {
        "display_name": "Procurement guidance",
        "description": "Answers approved procurement questions.",
        "instructions": "Use approved procurement sources.",
    }

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        create_response = await client.post(
            "/api/v1/skills/organization/",
            json={"slug": f"procurement-{uuid4().hex[:8]}", **original},
            headers=headers,
        )
        assert create_response.status_code == 201, create_response.text
        skill = create_response.json()
        skill_id = skill["id"]
        original_revision_id = skill["current_revision"]["id"]
        audit_count_after_create = enqueue_audit.await_count

        unchanged_response = await client.post(
            f"/api/v1/skills/organization/{skill_id}/revisions/",
            json=original,
            headers=headers,
        )
        assert unchanged_response.status_code == 200, unchanged_response.text
        assert unchanged_response.json()["id"] == original_revision_id
        assert enqueue_audit.await_count == audit_count_after_create

        unchanged_history = await client.get(
            f"/api/v1/skills/organization/{skill_id}/revisions/",
            headers=headers,
        )
        assert unchanged_history.status_code == 200, unchanged_history.text
        assert unchanged_history.json()["total_count"] == 1

        changed_response = await client.post(
            f"/api/v1/skills/organization/{skill_id}/revisions/",
            json={
                **original,
                "instructions": "Use approved and current procurement sources.",
            },
            headers=headers,
        )
        assert changed_response.status_code == 201, changed_response.text
        assert changed_response.json()["revision_number"] == 2
        assert changed_response.json()["id"] != original_revision_id
        assert enqueue_audit.await_count == audit_count_after_create + 1

        changed_history = await client.get(
            f"/api/v1/skills/organization/{skill_id}/revisions/",
            headers=headers,
        )
        assert changed_history.status_code == 200, changed_history.text
        assert changed_history.json()["total_count"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_rejects_a_revision_that_changed_after_preview(
    client, admin_token
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    space_response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"skill-restore-conflict-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]

    create_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={
            "slug": "restore-conflict",
            "display_name": "Restore conflict",
            "description": "Initial content",
            "instructions": "Initial instructions",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill = create_response.json()
    skill_id = skill["id"]
    source_revision_id = skill["current_revision_id"]

    reviewed_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        json={
            "display_name": "Restore conflict",
            "description": "Reviewed content",
            "instructions": "Reviewed instructions",
        },
        headers=headers,
    )
    assert reviewed_response.status_code == 201, reviewed_response.text
    reviewed_current_revision_id = reviewed_response.json()["id"]

    concurrent_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        json={
            "display_name": "Restore conflict",
            "description": "Concurrent content",
            "instructions": "Concurrent instructions",
        },
        headers=headers,
    )
    assert concurrent_response.status_code == 201, concurrent_response.text
    concurrent_revision_id = concurrent_response.json()["id"]

    restore_response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/"
        f"{source_revision_id}/restore/",
        json={"reviewed_current_revision_id": reviewed_current_revision_id},
        headers=headers,
    )

    assert restore_response.status_code == 409, restore_response.text
    current_response = await client.get(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/",
        headers=headers,
    )
    history_response = await client.get(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        headers=headers,
    )
    assert current_response.status_code == 200, current_response.text
    assert current_response.json()["current_revision_id"] == concurrent_revision_id
    assert history_response.status_code == 200, history_response.text
    assert history_response.json()["total_count"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "organization", [False, True], ids=["personal", "organization"]
)
async def test_skill_and_revision_are_committed_before_success_response(
    app, client, admin_token, organization
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    if organization:
        path = "/api/v1/skills/organization/"
    else:
        space = await client.get("/api/v1/spaces/type/personal/", headers=headers)
        assert space.status_code == 200, space.text
        path = f"/api/v1/spaces/{space.json()['id']}/skills/"
    content = {
        "display_name": "Immediately available",
        "description": "The detail page can read a saved Skill immediately.",
        "instructions": "Write clearly.",
    }
    created = await request_at_transaction_boundary(
        app,
        method="POST",
        path=path,
        payload={"slug": f"immediate-{uuid4().hex[:8]}", **content},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill_path = f"{path}{created.json()['id']}/"
    detail = await client.get(skill_path, headers=headers)
    assert detail.status_code == 200, detail.text

    revised = await request_at_transaction_boundary(
        app,
        method="POST",
        path=f"{skill_path}revisions/",
        payload={**content, "instructions": "Write clear, short sentences."},
        headers=headers,
    )
    assert revised.status_code == 201, revised.text
    history = await client.get(f"{skill_path}revisions/", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["id"] == revised.json()["id"]
