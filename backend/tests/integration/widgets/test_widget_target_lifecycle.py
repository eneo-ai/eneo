"""Widgets follow their assistant through a move or a deletion."""

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.main.exceptions import ErrorCodes


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


async def _archive_entries() -> list[tuple[str, dict[str, Any]]]:
    """WIDGET_ARCHIVED rows in the audit log: mandatory, so written in the
    request's transaction rather than queued for the worker."""
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.text(
                "SELECT entity_id, metadata FROM audit_logs"
                " WHERE action = 'widget_archived' ORDER BY timestamp, id"
            )
        )
        return [(str(entity_id), metadata) for entity_id, metadata in rows]


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
    assert resp.json()["eneo_error_code"] == ErrorCodes.ASSISTANT_PUBLISHED_AS_WIDGET
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
async def test_moving_an_assistant_archives_its_draft_widgets(client, admin_token):
    source_space = await _space(client, admin_token)
    resp = await client.post(
        f"/api/v1/spaces/{source_space}/applications/assistants/",
        json={"name": "Utkastassistenten"},
        headers=_auth(admin_token),
    )
    assistant_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{source_space}/widgets/",
        json={"target_id": assistant_id, "name": "Provchatt"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    draft = resp.json()
    target_space = await _space(client, admin_token)

    resp = await client.post(
        f"/api/v1/assistants/{assistant_id}/transfer/",
        json={"target_space_id": target_space},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 204, resp.text

    resp = await client.get(
        f"/api/v1/assistants/{assistant_id}/", headers=_auth(admin_token)
    )
    assert resp.json()["space_id"] == target_space
    assert (await _widget(client, admin_token, draft["id"]))["status"] == "archived"
    [(entity_id, metadata)] = await _archive_entries()
    assert entity_id == draft["id"]
    assert metadata["extra"]["reason"] == "assistant_moved"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_an_assistant_archives_its_widgets_and_frees_their_template(
    client, admin_token, active_widget
):
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

    archived_before = await _archive_entries()
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

    entries = (await _archive_entries())[len(archived_before) :]
    assert [entity_id for entity_id, _ in entries] == [widget_id]
    assert entries[0][1]["extra"]["reason"] == "assistant_deleted"

    resp = await client.delete(
        f"/api/v1/admin/widget-templates/{template_id}/", headers=_auth(admin_token)
    )
    assert resp.status_code == 204, resp.text
