"""Integration tests for the widget admin endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.audit.application import audit_service as audit_service_module
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import ModelId
from eneo.mcp_servers.application.capability_resolver import general_servers_for_space
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
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


@pytest.fixture
async def widget_editor(db_container, patch_auth_service_jwt):
    """A user who manages widgets but is not a tenant admin: token and id.

    Managing a space's widgets needs edit rights on its assistants, which the
    space actor grants a member only with the tenant's assistants permission.
    """
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"widget-editor-{uuid4().hex[:8]}",
                permissions=[Permission.WIDGETS, Permission.ASSISTANTS],
                tenant_id=admin.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"widget-editor-{uuid4().hex[:8]}@example.com",
                username=f"widget_editor_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        return SimpleNamespace(
            token=container.auth_service().create_access_token_for_user(user),
            id=user.id,
        )


@pytest.fixture
def widget_editor_token(widget_editor):
    return widget_editor.token


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
async def test_widget_editors_read_the_policy_but_cannot_change_it(
    client, admin_token, widget_editor_token
):
    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"max_daily_token_budget": 300_000, "max_retention_days": 120},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        "/api/v1/admin/widget-policy/", headers=_auth(widget_editor_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "max_daily_token_budget": 300_000,
        "allow_bot_protection_none": False,
        "min_retention_days": 0,
        "max_retention_days": 120,
        "allow_external_tools": True,
    }

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"max_daily_token_budget": 5_000_000},
        headers=_auth(widget_editor_token),
    )
    assert resp.status_code == 403, resp.text
    resp = await client.get("/api/v1/admin/widget-policy/", headers=_auth(admin_token))
    assert resp.json()["max_daily_token_budget"] == 300_000


async def _revision(client, token, widget_id) -> int:
    resp = await client.get(f"/api/v1/widgets/{widget_id}/", headers=_auth(token))
    return resp.json()["revision"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rule_errors_carry_their_codes(client, admin_token, space_with_assistant):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget_id = resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": await _revision(client, admin_token, widget_id),
            "limits": {"daily_token_budget": 5_000_000},
            "privacy": {"retention_days": 400},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "widget_policy_violation"
    assert detail["violations"] == [
        "daily_token_budget_exceeds_policy",
        "retention_above_policy_maximum",
    ]
    assert detail["message"]

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "widget_serving_blocked"
    assert detail["blockers"] == ["allowed_origins_empty", "target_not_published"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_active_widget_keeps_its_disclosure_and_origins(
    client, admin_token, active_widget
):
    widget_id = active_widget["id"]
    texts = {**active_widget["texts"], "subtitle": ""}
    for change, blocker in [
        ({"texts": texts}, "subtitle_empty"),
        ({"allowed_origins": []}, "allowed_origins_empty"),
    ]:
        resp = await client.patch(
            f"/api/v1/widgets/{widget_id}/",
            json={
                "revision": await _revision(client, admin_token, widget_id),
                **change,
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]["code"] == "widget_serving_blocked"
        assert resp.json()["detail"]["blockers"] == [blocker]

    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": f"Utan upplysning {uuid4().hex[:6]}"},
        headers=_auth(admin_token),
    )
    template_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/admin/widget-templates/{template_id}/",
        json={"texts": {"subtitle": ""}, "locked_groups": ["appearance"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template_id}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/link-template/",
        json={
            "template_id": template_id,
            "revision": await _revision(client, admin_token, widget_id),
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["blockers"] == ["subtitle_empty"]

    stored = (
        await client.get(f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token))
    ).json()
    assert stored["status"] == "active"
    assert stored["texts"]["subtitle"] == active_widget["texts"]["subtitle"]
    assert stored["allowed_origins"] == ["https://www.kommun.se"]
    assert stored["template"] is None


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
    template = resp.json()
    assert template["theme"]["primary_color"] == "#123456"

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
    assert template["published"] is None
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
    assert published["published"] == {
        "texts": template["texts"],
        "theme": template["theme"],
        "persona": template["persona"],
        "language": template["language"],
        "locked_groups": template["locked_groups"],
    }
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
    # The release pickers show is the one widgets get, not the edited draft.
    assert resp.json()["published"]["theme"]["primary_color"] == "#123456"
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
async def test_null_fields_are_refused_on_a_template_linked_widget(
    client, admin_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": "Kommunblå"},
        headers=_auth(admin_token),
    )
    template_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template_id}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Chatt", "template_id": template_id},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    widget = resp.json()

    for field in ["texts", "theme", "language", "limits", "name"]:
        resp = await client.patch(
            f"/api/v1/widgets/{widget['id']}/",
            json={"revision": widget["revision"], field: None},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422, (field, resp.text)
    resp = await client.get(
        f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
    )
    assert resp.json()["revision"] == widget["revision"]
    assert resp.json()["texts"] == widget["texts"]


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
    assert active["activation_blockers"] == []
    assert by_name["Översikt B"]["activation_blockers"] == ["allowed_origins_empty"]
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


# A valid 1x1 PNG; the icon endpoint only checks the declared type and size.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _upload_icon(client, token) -> str:
    resp = await client.post(
        "/api/v1/icons/",
        files={"file": ("avatar.png", _PNG, "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_widget(client, token, space_id, assistant_id, **body):
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Chatt", **body},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _patch(client, token, widget, **changes):
    resp = await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={"revision": widget["revision"], **changes},
        headers=_auth(token),
    )
    return resp


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persona_avatar_is_the_callers_upload_and_lives_while_shown(
    client, admin_token, widget_editor_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    widget = await _create_widget(client, admin_token, space_id, assistant_id)
    assert widget["persona"] == {
        "name": "",
        "avatar_icon_id": None,
        "avatar_in_launcher": False,
    }
    own = await _upload_icon(client, admin_token)
    someone_elses = await _upload_icon(client, widget_editor_token)

    # The id is public, so only the caller's own upload may become the avatar.
    resp = await _patch(
        client,
        admin_token,
        widget,
        persona={"name": "Sigge", "avatar_icon_id": someone_elses},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["eneo_error_code"] == ErrorCodes.ICON_NOT_ATTACHABLE

    resp = await _patch(
        client, admin_token, widget, persona={"name": "Sigge", "avatar_icon_id": own}
    )
    assert resp.status_code == 200, resp.text
    widget = resp.json()
    assert widget["persona"] == {
        "name": "Sigge",
        "avatar_icon_id": own,
        "avatar_in_launcher": False,
    }

    # Shown by the widget, the icon cannot be deleted on its own.
    resp = await client.delete(f"/api/v1/icons/{own}/", headers=_auth(admin_token))
    assert resp.status_code == 409, resp.text
    assert resp.json()["eneo_error_code"] == ErrorCodes.ICON_IN_USE

    # The launcher only ever shows an uploaded image.
    resp = await _patch(
        client,
        admin_token,
        widget,
        persona={"name": "Sigge", "avatar_icon_id": None, "avatar_in_launcher": True},
    )
    assert resp.status_code == 422, resp.text

    # Clearing the avatar releases the icon: nothing shows it any more.
    resp = await _patch(client, admin_token, widget, persona={"name": "Sigge"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["persona"]["avatar_icon_id"] is None
    resp = await client.get(f"/api/v1/icons/{own}/")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_templated_persona_keeps_its_icon_for_every_follower(
    client, admin_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    avatar = await _upload_icon(client, admin_token)
    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": "Husstil"},
        headers=_auth(admin_token),
    )
    template = resp.json()
    resp = await client.patch(
        f"/api/v1/admin/widget-templates/{template['id']}/",
        json={
            "persona": {"name": "Sigge", "avatar_icon_id": avatar},
            "locked_groups": ["persona"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template['id']}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["published"]["persona"]["avatar_icon_id"] == avatar

    first = await _create_widget(
        client, admin_token, space_id, assistant_id, template_id=template["id"]
    )
    second = await _create_widget(
        client, admin_token, space_id, assistant_id, template_id=template["id"]
    )
    assert first["persona"]["name"] == "Sigge"
    assert first["persona"]["avatar_icon_id"] == avatar
    assert first["template"]["locked_groups"] == ["persona"]

    # A locked persona cannot be changed on a follower.
    resp = await _patch(client, admin_token, first, persona={"name": "Annan"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "field_locked_by_template"

    # One follower letting go of the template must not take the icon from
    # the other follower or from the template.
    resp = await client.post(
        f"/api/v1/widgets/{first['id']}/detach-template/",
        json={"revision": first["revision"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    resp = await _patch(client, admin_token, first, persona={"name": "Egen"})
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"/api/v1/icons/{avatar}/")
    assert resp.status_code == 200
    resp = await client.get(
        f"/api/v1/widgets/{second['id']}/", headers=_auth(admin_token)
    )
    assert resp.json()["persona"]["avatar_icon_id"] == avatar

    # The public configuration carries the persona for the embed page.
    resp = await _patch(
        client, admin_token, resp.json(), allowed_origins=["https://www.kommun.se"]
    )
    assert resp.status_code == 200, resp.text
    await _publish(client, admin_token, assistant_id)
    resp = await client.post(
        f"/api/v1/widgets/{second['id']}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"/api/v1/widgets/{second['public_id']}/config/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["persona"] == {
        "name": "Sigge",
        "avatar_icon_id": avatar,
        "avatar_in_launcher": False,
    }


# --- security audit follow-ups ---------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_preview_token_is_minted_for_drafts_and_active_widgets_only(
    client, admin_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/preview-token/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    minted = resp.json()
    assert minted["token"] and minted["public_id"].startswith("wgt_")
    # A bearer in the admin page's DOM lives no longer than a visitor token.
    assert 0 < minted["expires_in"] <= 900

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": await _revision(client, admin_token, widget_id),
            "allowed_origins": ["https://www.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    await _publish(client, admin_token, assistant_id)
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/preview-token/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/pause/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/preview-token/", headers=_auth(admin_token)
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "preview_unavailable_while_paused"


async def _attach_external_server(db_container, space_id, assistant_id):
    """An MCP server outside Eneo on the assistant, as an admin sets one up:
    two tools on the server, only the first switched on for the assistant."""
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        session = container.session()
        server = MCPServers(
            tenant_id=admin.tenant_id,
            name=f"Ärendesystemet {uuid4().hex[:6]}",
            description="Kommunens ärenden",
            http_url="https://cases.example.test/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
        )
        session.add(server)
        await session.flush()
        search, create = (
            MCPServerTools(
                mcp_server_id=server.id,
                name=name,
                title=title,
                description=title,
                input_schema={"type": "object", "properties": {}},
                is_enabled_by_default=True,
                requires_approval=False,
                removed_from_remote=False,
            )
            for name, title in (
                ("search_cases", "Sök ärende"),
                ("create_case", "Skapa ärende"),
            )
        )
        session.add_all([search, create])
        await session.flush()
        session.add_all(
            [
                SpacesMCPServers(space_id=space_id, mcp_server_id=server.id),
                AssistantMCPServers(assistant_id=assistant_id, mcp_server_id=server.id),
                AssistantMCPServerTools(
                    assistant_id=assistant_id,
                    mcp_server_tool_id=search.id,
                    is_enabled=True,
                ),
            ]
        )
        return SimpleNamespace(
            id=str(server.id),
            name=server.name,
            search=str(search.id),
            create=str(create.id),
        )


async def _switch_on(db_container, assistant_id, tool_id):
    async with db_container() as container:
        container.session().add(
            AssistantMCPServerTools(
                assistant_id=assistant_id, mcp_server_tool_id=tool_id, is_enabled=True
            )
        )


async def _draft_for(client, token, space_id, assistant_id):
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(token),
    )
    widget = resp.json()
    resp = await _patch(
        client, token, widget, allowed_origins=["https://www.kommun.se"]
    )
    assert resp.status_code == 200, resp.text
    await _publish(client, token, assistant_id)
    resp = await client.get(f"/api/v1/widgets/{widget['id']}/", headers=_auth(token))
    return resp.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_external_tools_are_acknowledged_against_the_assistants_servers(
    client, admin_token, space_with_assistant, db_container, monkeypatch
):
    space_id, assistant_id = space_with_assistant
    server = await _attach_external_server(db_container, space_id, assistant_id)
    widget = await _draft_for(client, admin_token, space_id, assistant_id)
    widget_id = widget["id"]
    audit = AsyncMock()
    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", audit)

    listed = {
        "id": server.id,
        "name": server.name,
        "tools": [{"id": server.search, "name": "Sök ärende"}],
    }
    assert widget["external_tools"] == [listed]
    assert widget["external_tools_acknowledged"] is False
    assert widget["activation_blockers"] == []

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "external_tools_unacknowledged"
    assert resp.json()["detail"]["servers"] == [listed]

    # Only what the dialog showed is acknowledged: a stale list is refused.
    url = f"/api/v1/widgets/{widget_id}/acknowledge-external-tools/"
    resp = await client.post(url, json={"servers": []}, headers=_auth(admin_token))
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "external_tools_changed"
    assert resp.json()["detail"]["servers"] == [listed]

    shown = {"servers": [{"id": server.id, "tool_ids": [server.search]}]}
    resp = await client.post(url, json=shown, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["external_tools_acknowledged"] is True
    entry = audit.await_args.args[2]
    assert entry["action"] == "widget_external_tools_acknowledged"
    assert entry["entity_id"] == widget_id
    assert entry["metadata"]["extra"]["external_tools"] == [listed]

    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    # A tool switched on after the acknowledgement waits for a new one; the
    # widget keeps serving meanwhile.
    await _switch_on(db_container, assistant_id, server.create)
    live = (
        await client.get(f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token))
    ).json()
    assert live["status"] == "active"
    assert live["external_tools_acknowledged"] is False
    assert live["activation_blockers"] == ["external_tools_unacknowledged"]
    resp = await client.get("/api/v1/admin/widgets/", headers=_auth(admin_token))
    [item] = [i for i in resp.json()["items"] if i["id"] == widget_id]
    assert item["external_tools"] == [server.name]
    assert item["external_tools_acknowledged"] is False

    shown = {"servers": [{"id": server.id, "tool_ids": [server.create, server.search]}]}
    resp = await client.post(url, json=shown, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["activation_blockers"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_visitor_reaches_only_the_acknowledged_tools_of_the_servers(
    client, admin_token, space_with_assistant, db_container
):
    space_id, assistant_id = space_with_assistant
    server = await _attach_external_server(db_container, space_id, assistant_id)
    widget = await _draft_for(client, admin_token, space_id, assistant_id)
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/acknowledge-external-tools/",
        json={"servers": [{"id": server.id, "tool_ids": [server.search]}]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    await _switch_on(db_container, assistant_id, server.create)

    async with db_container() as container:
        stored = await container.widget_repo().get(UUID(widget["id"]))
        assert stored is not None
        visitor = await container.widget_authentication_service().resolve_user(
            stored, uuid4(), preview=True
        )
        # The servers a turn of the assistant is handed, read as it reads them.
        space = await container.space_service().get_space(UUID(space_id))
        attached = space.get_assistant(UUID(assistant_id)).mcp_servers
        servers = general_servers_for_space(attached, space.security_classification)

    assert visitor.active_widget is not None
    (reached,) = visitor.active_widget.reachable_servers(servers)
    assert {tool.name: tool.is_enabled for tool in reached.tools} == {
        "search_cases": True,
        "create_case": False,
    }
    # The assistant's own entities keep the tool switched on for staff.
    (own,) = [s for s in attached if str(s.id) == server.id]
    assert {tool.name: tool.is_enabled for tool in own.tools} == {
        "search_cases": True,
        "create_case": True,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_widget_policy_governs_servers_outside_eneo(client, admin_token):
    resp = await client.get("/api/v1/admin/widget-policy/", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["allow_external_tools"] is True
    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"allow_external_tools": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allow_external_tools"] is False
    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"allow_external_tools": True},
        headers=_auth(admin_token),
    )
    assert resp.json()["allow_external_tools"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_wildcard_over_a_top_level_domain_is_refused(
    client, admin_token, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": await _revision(client, admin_token, widget_id),
            "allowed_origins": ["https://*.se"],
        },
        headers=_auth(admin_token),
    )
    # Refused before the save, at the field; the API sanitises the reason.
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", "allowed_origins"]
    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": await _revision(client, admin_token, widget_id),
            "allowed_origins": ["https://*.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_origins"] == ["https://*.kommun.se"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_editor_changes_governed_settings_only_while_the_widget_is_paused(
    client, admin_token, widget_editor, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": str(widget_editor.id), "role": "editor"},
        headers=_auth(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    editor = _auth(widget_editor.token)

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=editor,
    )
    assert resp.status_code == 201, resp.text
    widget_id = resp.json()["id"]

    async def patch(headers, **changes):
        return await client.patch(
            f"/api/v1/widgets/{widget_id}/",
            json={
                "revision": await _revision(client, admin_token, widget_id),
                **changes,
            },
            headers=headers,
        )

    # A draft's rules are the editor's to set.
    resp = await patch(editor, allowed_origins=["https://www.kommun.se"])
    assert resp.status_code == 200, resp.text
    await _publish(client, admin_token, assistant_id)
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text

    # Live, the settings the admin reviewed are the admin's.
    resp = await patch(editor, allowed_origins=["https://*.kommun.se"])
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "admin_required_while_active"
    assert resp.json()["detail"]["fields"] == ["allowed_origins"]
    resp = await patch(
        editor, privacy={"retention_days": 7, "store_feedback_text": False}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["fields"] == ["privacy"]
    # The same value again is no change; the rest of the widget stays the editor's.
    resp = await patch(
        editor, allowed_origins=["https://www.kommun.se/"], name="Chatten"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Chatten"
    resp = await patch(_auth(admin_token), allowed_origins=["https://*.kommun.se"])
    assert resp.status_code == 200, resp.text

    # Paused, the rules are the editor's again, and the admin reviews them at
    # the next activation.
    resp = await client.post(f"/api/v1/widgets/{widget_id}/pause/", headers=editor)
    assert resp.status_code == 200, resp.text
    resp = await patch(editor, allowed_origins=["https://a.kommun.se"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_origins"] == ["https://a.kommun.se"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_editor_switches_a_live_widgets_template_only_while_it_is_paused(
    client, admin_token, widget_editor, space_with_assistant
):
    space_id, assistant_id = space_with_assistant
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": str(widget_editor.id), "role": "editor"},
        headers=_auth(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    editor = _auth(widget_editor.token)
    admin = _auth(admin_token)

    async def template(name, locked_groups):
        resp = await client.post(
            "/api/v1/admin/widget-templates/",
            json={"name": f"{name} {uuid4().hex[:6]}"},
            headers=admin,
        )
        assert resp.status_code == 201, resp.text
        template_id = resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/admin/widget-templates/{template_id}/",
            json={"locked_groups": locked_groups},
            headers=admin,
        )
        assert resp.status_code == 200, resp.text
        resp = await client.post(
            f"/api/v1/admin/widget-templates/{template_id}/publish/", headers=admin
        )
        assert resp.status_code == 200, resp.text
        return template_id

    locking = await template("Låst juridik", ["legal_texts"])
    unlocked = await template("Fri", [])

    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt", "template_id": locking},
        headers=editor,
    )
    assert resp.status_code == 201, resp.text
    widget_id = resp.json()["id"]

    async def link(headers, template_id):
        return await client.post(
            f"/api/v1/widgets/{widget_id}/link-template/",
            json={
                "template_id": template_id,
                "revision": await _revision(client, admin_token, widget_id),
            },
            headers=headers,
        )

    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={
            "revision": await _revision(client, admin_token, widget_id),
            "allowed_origins": ["https://www.kommun.se"],
        },
        headers=editor,
    )
    assert resp.status_code == 200, resp.text
    await _publish(client, admin_token, assistant_id)
    resp = await client.post(f"/api/v1/widgets/{widget_id}/activate/", headers=admin)
    assert resp.status_code == 200, resp.text

    # Live, leaving the template would drop its lock on the legal texts.
    resp = await link(editor, unlocked)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "admin_required_while_active"
    assert resp.json()["detail"]["fields"] == ["template"]
    # Applying the same template again only adds; the admin switches.
    resp = await link(editor, locking)
    assert resp.status_code == 200, resp.text
    resp = await link(admin, unlocked)
    assert resp.status_code == 200, resp.text
    assert resp.json()["template"]["id"] == unlocked

    # Paused, the template is the editor's again.
    resp = await client.post(f"/api/v1/widgets/{widget_id}/pause/", headers=editor)
    assert resp.status_code == 200, resp.text
    resp = await link(editor, locking)
    assert resp.status_code == 200, resp.text
    assert resp.json()["template"]["id"] == locking
