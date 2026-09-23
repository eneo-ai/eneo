"""Widgets stay with their assistant."""

from uuid import uuid4

import pytest


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
