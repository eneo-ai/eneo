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
    assert widget["texts"]["subtitle"]
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
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "allowed_origins": ["https://www.kommun.se/", "https://*.kommun.se"],
            "theme": {"primary_color": "#005a9c"},
            "texts": {
                "title": "Fråga kommunen",
                # The editor's limit: four questions must save.
                "suggested_questions": ["Öppettider?", "Bygglov", "Skola", "Avfall"],
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
    assert updated["texts"]["suggested_questions"] == [
        "Öppettider?",
        "Bygglov",
        "Skola",
        "Avfall",
    ]
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
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "name": "x",
        },
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
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "allowed_origins": ["www.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422, resp.text

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "limits": {"daily_token_budget": 5_000_000},
        },
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
    assert resp.json()["max_daily_token_budget"] == 2_000_000

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"max_daily_token_budget": 500_000, "max_retention_days": 90},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_daily_token_budget"] == 500_000
    assert resp.json()["max_retention_days"] == 90

    resp = await client.get("/api/v1/admin/widget-policy/", headers=_auth(admin_token))
    assert resp.json()["max_daily_token_budget"] == 500_000

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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_templates(
    client, admin_token, regular_user_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant

    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": "Kommunblå", "is_default": True},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    template = resp.json()
    assert template["is_default"] is True

    resp = await client.patch(
        f"/api/v1/admin/widget-templates/{template['id']}/",
        json={
            "description": "Husstil",
            "theme": {**template["theme"], "primary_color": "#123456", "radius": 4},
            "texts": {**template["texts"], "title": "Fråga oss"},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"]["primary_color"] == "#123456"

    # Editors can list but not write.
    resp = await client.get(
        "/api/v1/widget-templates/", headers=_auth(regular_user_token)
    )
    assert resp.status_code == 403
    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": "Nej"},
        headers=_auth(regular_user_token),
    )
    assert resp.status_code == 403
    resp = await client.get("/api/v1/widget-templates/", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert [t["name"] for t in resp.json()["items"]] == ["Kommunblå"]

    # Nothing follows a template until it is published.
    assert template["published_at"] is None
    assert template["has_unpublished_changes"] is True
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={
            "target_id": assistant_id,
            "name": "Chatt",
            "template_id": template["id"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "template_not_published"

    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template['id']}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    published = resp.json()
    assert published["published_at"] is not None
    assert published["has_unpublished_changes"] is False
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template['id']}/publish/",
        headers=_auth(regular_user_token),
    )
    assert resp.status_code == 403

    # A widget created from a published template follows it: appearance and
    # language are locked by default, wording and legal texts are copied once.
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={
            "target_id": assistant_id,
            "name": "Chatt",
            "template_id": template["id"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    widget = resp.json()
    assert widget["theme"]["primary_color"] == "#123456"
    assert widget["texts"]["title"] == "Fråga oss"
    assert widget["template"] == {
        "id": template["id"],
        "name": "Kommunblå",
        "locked_groups": ["appearance", "language"],
    }

    async def revision(widget_id: str) -> int:
        current = await client.get(
            f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
        )
        return current.json()["revision"]

    # Saving the template edits its draft only.
    resp = await client.patch(
        f"/api/v1/admin/widget-templates/{template['id']}/",
        json={"theme": {**template["theme"], "primary_color": "#654321"}},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_unpublished_changes"] is True
    assert resp.json()["linked_widgets"] == 1
    resp = await client.get(
        f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
    )
    assert resp.json()["theme"]["primary_color"] == "#123456"

    # Publishing writes the locked groups onto the follower in the same request.
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template['id']}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get(
        f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
    )
    assert resp.json()["theme"]["primary_color"] == "#654321"

    # Locked parts are refused on the widget, unlocked parts still save.
    resp = await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={
            "revision": await revision(widget["id"]),
            "theme": {**widget["theme"], "primary_color": "#000000"},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "field_locked_by_template"
    resp = await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={
            "revision": await revision(widget["id"]),
            "texts": {**widget["texts"], "title": "Egen titel"},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["texts"]["title"] == "Egen titel"
    assert resp.json()["theme"]["primary_color"] == "#654321"

    # The list shows how many widgets follow each template.
    resp = await client.get("/api/v1/widget-templates/", headers=_auth(admin_token))
    assert resp.json()["items"][0]["linked_widgets"] == 1

    # A followed template cannot be deleted.
    resp = await client.delete(
        f"/api/v1/admin/widget-templates/{template['id']}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "template_in_use"

    # Detaching keeps the values and frees every part.
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/detach-template/",
        json={"revision": await revision(widget["id"])},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["template"] is None
    assert resp.json()["theme"]["primary_color"] == "#654321"
    resp = await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={
            "revision": await revision(widget["id"]),
            "theme": {**widget["theme"], "primary_color": "#000000"},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    # Linking again takes the published release back.
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/link-template/",
        json={"revision": await revision(widget["id"]), "template_id": template["id"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"]["primary_color"] == "#654321"
    assert resp.json()["template"]["id"] == template["id"]

    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/detach-template/",
        json={"revision": await revision(widget["id"])},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(
        f"/api/v1/admin/widget-templates/{template['id']}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 204
    resp = await client.get(
        f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/link-template/",
        json={"revision": await revision(widget["id"]), "template_id": template["id"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_overview(
    client, admin_token, regular_user_token, space_with_assistant, db_container
):
    from datetime import date, timedelta

    from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl

    space_id, assistant_id = space_with_assistant
    await _publish(client, admin_token, assistant_id)
    created = []
    for name in ("Översikt A", "Översikt B"):
        resp = await client.post(
            f"/api/v1/spaces/{space_id}/widgets/",
            json={"target_id": assistant_id, "name": name},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 201, resp.text
        created.append(resp.json())
    await client.patch(
        f"/api/v1/widgets/{created[0]['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{created[0]['id']}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "allowed_origins": ["https://www.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    resp = await client.post(
        f"/api/v1/widgets/{created[0]['id']}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text

    async with db_container() as container:
        usage = WidgetUsageRepoImpl(container.session())
        today = date.today()
        await usage.record(
            created[0]["id"], today, questions=3, input_tokens=30, output_tokens=12
        )
        await usage.record(
            created[0]["id"],
            today - timedelta(days=10),
            questions=5,
            input_tokens=50,
            output_tokens=20,
            blocked_rate=2,
        )
        await usage.record(created[0]["id"], today - timedelta(days=40), questions=9)
        await container.session().commit()

    resp = await client.get("/api/v1/admin/widgets/", headers=_auth(regular_user_token))
    assert resp.status_code == 403

    resp = await client.get("/api/v1/admin/widgets/", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_name = {item["name"]: item for item in body["items"]}
    active = by_name["Översikt A"]
    assert active["status"] == "active"
    assert active["assistant_name"] == "Kommunassistenten"
    assert active["space_name"]
    assert active["questions_7d"] == 3
    assert active["questions_30d"] == 8
    assert active["input_tokens_30d"] == 80
    assert active["output_tokens_30d"] == 32
    assert active["blocked_30d"] == 2
    assert active["last_activity"] == today.isoformat()
    assert active["daily_token_budget"] == 500_000
    draft = by_name["Översikt B"]
    assert draft["status"] == "draft"
    assert draft["questions_30d"] == 0
    assert draft["last_activity"] is None
    # Active widgets sort first.
    assert body["items"][0]["status"] == "active"
    assert body["totals"]["active"] >= 1
    assert body["totals"]["questions_30d"] >= 8
