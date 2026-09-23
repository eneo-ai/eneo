"""Widgets follow their assistant through a move or a deletion."""

from uuid import uuid4

import pytest

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _space(client, token) -> str:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"widget-target-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _widget(client, token, widget_id) -> dict:
    resp = await client.get(f"/api/v1/widgets/{widget_id}/", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_assistant_with_a_live_widget_stays_in_its_space(
    client, admin_token, active_widget
):
    assistant_id = active_widget["target_id"]
    target_space = await _space(client, admin_token)

    resp = await client.post(
        f"/api/v1/assistants/{assistant_id}/transfer/",
        json={"target_space_id": target_space},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert "Archive the Assistant's web widget" in resp.text
    resp = await client.get(
        f"/api/v1/assistants/{assistant_id}/", headers=_auth(admin_token)
    )
    assert resp.json()["space_id"] == active_widget["space_id"]
    resp = await client.get(f"/api/v1/widgets/{active_widget['public_id']}/config/")
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"/api/v1/widgets/{active_widget['id']}/archive/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/assistants/{assistant_id}/transfer/",
        json={"target_space_id": target_space},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 204, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_an_assistant_archives_its_widgets_and_frees_their_template(
    client, admin_token, active_widget, monkeypatch
):
    audited: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        audited.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)

    resp = await client.post(
        "/api/v1/admin/widget-templates/",
        json={"name": f"Kommunblå {uuid4().hex[:6]}"},
        headers=_auth(admin_token),
    )
    template_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/admin/widget-templates/{template_id}/publish/",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    widget_id = active_widget["id"]
    resp = await client.post(
        f"/api/v1/widgets/{widget_id}/link-template/",
        json={
            "template_id": template_id,
            "revision": (await _widget(client, admin_token, widget_id))["revision"],
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(
        f"/api/v1/admin/widget-templates/{template_id}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 409, resp.text

    # A widget of another assistant in the same space is left alone.
    resp = await client.post(
        f"/api/v1/spaces/{active_widget['space_id']}/applications/assistants/",
        json={"name": "Grannen"},
        headers=_auth(admin_token),
    )
    neighbour_assistant = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{active_widget['space_id']}/widgets/",
        json={"target_id": neighbour_assistant, "name": "Grannens chatt"},
        headers=_auth(admin_token),
    )
    neighbour = resp.json()

    audited.clear()
    resp = await client.delete(
        f"/api/v1/assistants/{active_widget['target_id']}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 204, resp.text

    archived = await _widget(client, admin_token, widget_id)
    assert archived["status"] == "archived"
    assert archived["token_generation"] > active_widget["token_generation"]
    resp = await client.get(f"/api/v1/widgets/{active_widget['public_id']}/config/")
    assert resp.status_code == 404
    assert (await _widget(client, admin_token, neighbour["id"]))["status"] == "draft"

    entries = [
        entry for entry in audited if entry["action"] == ActionType.WIDGET_ARCHIVED
    ]
    assert [str(entry["entity_id"]) for entry in entries] == [widget_id]
    assert entries[0]["metadata"]["extra"]["reason"] == "assistant_deleted"

    resp = await client.delete(
        f"/api/v1/admin/widget-templates/{template_id}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 204, resp.text
