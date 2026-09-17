"""Integration tests for the widget admin endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.users.user import UserAdd, UserState


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
                email=f"regular-widget-{uuid4().hex[:8]}@example.com",
                username=f"reg_widget_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )
        return container.auth_service().create_access_token_for_user(user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def space_with_assistant(client, admin_token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"widget-space-{uuid4().hex[:8]}"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    space_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Kommunassistenten"},
        headers=_auth(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    assistant_id = resp.json()["id"]
    return space_id, assistant_id


async def _publish(client, token, assistant_id, published=True):
    resp = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/",
        params={"published": str(published).lower()},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_lifecycle(client, admin_token, space_with_assistant):
    space_id, assistant_id = space_with_assistant

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt", "language": "sv"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    widget = resp.json()
    widget_id = widget["id"]
    assert widget["public_id"].startswith("wgt_")
    assert widget["status"] == "draft"
    assert widget["texts"]["ai_disclosure"]
    assert set(widget["activation_blockers"]) == {
        "allowed_origins_empty",
        "target_not_published",
    }

    resp = await client.get(
        f"/api/v1/spaces/{space_id}/widgets/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert [w["id"] for w in resp.json()["items"]] == [widget_id]

    # Draft cannot be activated while blockers remain.
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 400, resp.text
    assert "allowed_origins_empty" in resp.text

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "allowed_origins": ["https://www.kommun.se/", "https://*.kommun.se"],
            "theme": {"primary_color": "#005a9c"},
            "texts": {
                "title": "Fråga kommunen",
                "suggested_questions": ["Öppettider?"],
            },
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["allowed_origins"] == [
        "https://www.kommun.se",
        "https://*.kommun.se",
    ]
    assert updated["theme"]["primary_color"] == "#005A9C"
    assert updated["token_generation"] == 1
    assert updated["activation_blockers"] == ["target_not_published"]

    await _publish(client, admin_token, assistant_id)

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["activation_blockers"] == []

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/pause/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paused"
    assert resp.json()["token_generation"] == 2

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/archive/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "archived"

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={"name": "x"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_validation_errors(client, admin_token, space_with_assistant):
    space_id, assistant_id = space_with_assistant

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": str(uuid4()), "name": "Okänd assistent"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404, resp.text

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget_id = resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={"allowed_origins": ["www.kommun.se"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422, resp.text

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={"limits": {"daily_token_budget": 5_000_000}},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert "daily_token_budget_exceeds_policy" in resp.text

    resp = await client.get(f"/api/v1/widgets/{uuid4()}/", headers=_auth(admin_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_permissions(
    client, admin_token, regular_user_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant

    # A user outside the space cannot see or create its widgets.
    resp = await client.get(
        f"/api/v1/spaces/{space_id}/widgets/", headers=_auth(regular_user_token)
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(regular_user_token),
    )
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(regular_user_token)
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_policy_endpoints(client, admin_token, regular_user_token):
    resp = await client.get("/api/v1/admin/widget-policy/", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_active_widgets"] == 5

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"max_active_widgets": 2, "max_retention_days": 90},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_active_widgets"] == 2
    assert resp.json()["max_retention_days"] == 90

    resp = await client.get("/api/v1/admin/widget-policy/", headers=_auth(admin_token))
    assert resp.json()["max_active_widgets"] == 2

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"min_retention_days": 100},
        headers=_auth(admin_token),
    )
    assert resp.status_code in (400, 422), resp.text

    resp = await client.get(
        "/api/v1/admin/widget-policy/", headers=_auth(regular_user_token)
    )
    assert resp.status_code == 403, resp.text
