"""Who may do what with flows over HTTP: a user bearer, a service key in the
flow's space, a service key of another space, a service key on a draft, and
the edit mode a person enters before the panel may save."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tests.integration.flows.conftest import patch_flow

API_KEY_HEADER = "X-API-Key"


async def _service_key(client, bearer, *, space_id, permission="write") -> str:
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"flow-svc-{uuid4().hex[:6]}",
            "key_type": "sk_",
            "permission": permission,
            "scope_type": "space",
            "scope_id": str(space_id),
            "ownership": "service",
            "expires_at": expires,
        },
        headers=bearer,
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


async def test_a_service_key_runs_published_flows_in_its_space_and_sees_its_own_runs(
    client,
    db_container,
    published,
    flows_enabled,
    bearer,
    provider,
):
    secret = await _service_key(client, bearer, space_id=published["space_id"])
    key = {API_KEY_HEADER: secret}
    flow_id = str(published["flow"].id)

    listed = await client.get(
        f"/api/v1/flows/?space_id={published['space_id']}", headers=key
    )
    assert listed.status_code == 200
    # The draft is not a thing a service principal can see.
    assert [f["id"] for f in listed.json()["items"]] == [flow_id]
    assert (
        await client.get(f"/api/v1/flows/{published['draft'].id}/", headers=key)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/flows/{flow_id}/published/", headers=key)
    ).status_code == 200

    run = await client.post(
        f"/api/v1/flows/{flow_id}/runs/", json={"values": {"topic": "x"}}, headers=key
    )
    assert run.status_code == 201, run.text
    assert run.json()["principal_type"] == "service"
    run_id = run.json()["id"]

    # A test run is a person's thing.
    draft_run = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={"values": {"topic": "x"}, "draft": True},
        headers=key,
    )
    assert draft_run.status_code == 403

    # The person who built the flow sees the service's run; the service sees
    # only its own, not the person's.
    own = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={"values": {"topic": "y"}},
        headers=bearer,
    )
    assert own.status_code == 201
    as_user = await client.get(f"/api/v1/flows/{flow_id}/runs/", headers=bearer)
    assert {r["id"] for r in as_user.json()["items"]} == {run_id, own.json()["id"]}
    as_service = await client.get(f"/api/v1/flows/{flow_id}/runs/", headers=key)
    assert [r["id"] for r in as_service.json()["items"]] == [run_id]
    assert (
        await client.get(
            f"/api/v1/flows/{flow_id}/runs/{own.json()['id']}/", headers=key
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/flows/{flow_id}/runs/{run_id}/", headers=key)
    ).status_code == 200

    # Uploads are stored as the author's; the service may bind and delete its own.
    upload = await client.post(
        f"/api/v1/flows/{flow_id}/runtime-files/",
        headers=key,
        files={"upload_file": ("in.txt", b"hello", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]
    # DELETE is an admin-level verb for API keys (platform rule): a write key
    # is refused, an admin key of the same space takes its upload back.
    refused = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{file_id}/", headers=key
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "insufficient_permission"
    admin_key = {
        API_KEY_HEADER: await _service_key(
            client, bearer, space_id=published["space_id"], permission="admin"
        )
    }
    # Another key's upload is not this key's to take back.
    assert (
        await client.delete(
            f"/api/v1/flows/{flow_id}/runtime-files/{file_id}/", headers=admin_key
        )
    ).status_code == 404
    own_upload = await client.post(
        f"/api/v1/flows/{flow_id}/runtime-files/",
        headers=admin_key,
        files={"upload_file": ("mine.txt", b"mine", "text/plain")},
    )
    assert own_upload.status_code == 201, own_upload.text
    deleted = await client.delete(
        f"/api/v1/flows/{flow_id}/runtime-files/{own_upload.json()['id']}/",
        headers=admin_key,
    )
    assert deleted.status_code == 204, deleted.text

    # Authoring is never a service key's: the flow stays as it is.
    assert (
        await client.delete(f"/api/v1/flows/{flow_id}/", headers=key)
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/flows/",
            json={"space_id": str(published["space_id"]), "name": "x"},
            headers=key,
        )
    ).status_code == 403


async def test_a_service_key_of_another_space_sees_nothing(
    client,
    db_container,
    published,
    flows_enabled,
    bearer,
    provider,
):
    secret = await _service_key(client, bearer, space_id=published["other_space_id"])
    key = {API_KEY_HEADER: secret}
    flow_id = str(published["flow"].id)
    assert (await client.get(f"/api/v1/flows/{flow_id}/", headers=key)).status_code in (
        403,
        404,
    )
    assert (
        await client.post(
            f"/api/v1/flows/{flow_id}/runs/",
            json={"values": {"topic": "x"}},
            headers=key,
        )
    ).status_code in (403, 404)
    assert (
        await client.get(
            f"/api/v1/flows/?space_id={published['space_id']}", headers=key
        )
    ).status_code in (403, 404)


# --- Edit mode ---


def _gate_code(payload: dict) -> str | None:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("code")
    return payload.get("code")


async def test_edit_mode_is_entered_and_left_per_user_and_gates_the_panel_save(
    client, published, flows_enabled, bearer
):
    url = f"/api/v1/flows/{published['draft'].id}/"

    # A flow opens in view mode, where the panel cannot save.
    viewed = await client.get(url, headers=bearer)
    assert viewed.json()["editing"] is False
    assert viewed.json()["editors"] == []
    refused = await patch_flow(client, url, json={"name": "Renamed"}, headers=bearer)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "flow_not_in_edit_mode"
    assert refused.json()["message"].startswith("The flow is shown in view mode.")

    entered = await client.post(f"{url}edit-mode/", headers=bearer)
    assert entered.status_code == 200, entered.text
    assert entered.json()["editing"] is True
    assert (await client.get(url, headers=bearer)).json()["editing"] is True
    # Entering again changes nothing.
    assert (await client.post(f"{url}edit-mode/", headers=bearer)).status_code == 200
    saved = await patch_flow(client, url, json={"name": "Renamed"}, headers=bearer)
    assert saved.status_code == 200, saved.text

    left = await client.delete(f"{url}edit-mode/", headers=bearer)
    assert left.status_code == 200, left.text
    assert left.json()["editing"] is False
    assert left.json()["name"] == "Renamed"
    assert (await client.get(url, headers=bearer)).json()["editing"] is False
    # Leaving twice is fine; the save is refused again.
    assert (await client.delete(f"{url}edit-mode/", headers=bearer)).status_code == 200
    assert (
        await patch_flow(client, url, json={"name": "Again"}, headers=bearer)
    ).status_code == 409


async def test_two_users_may_edit_the_same_flow_and_see_each_other(
    client, published, flows_enabled, bearer, second_editor, admin_user
):
    url = f"/api/v1/flows/{published['draft'].id}/"
    other = second_editor["bearer"]

    assert (await client.post(f"{url}edit-mode/", headers=bearer)).status_code == 200
    joined = await client.post(f"{url}edit-mode/", headers=other)
    assert joined.status_code == 200, joined.text

    assert joined.json()["editing"] is True
    assert [e["user_id"] for e in joined.json()["editors"]] == [str(admin_user.id)]
    mine = (await client.get(url, headers=bearer)).json()
    assert mine["editing"] is True
    assert [(e["user_id"], e["username"]) for e in mine["editors"]] == [
        (str(second_editor["user"].id), second_editor["user"].username)
    ]
    assert mine["editors"][0]["started_at"]

    # Both save; each sees the other's save as a revision.
    assert (
        await patch_flow(client, url, json={"name": "By admin"}, headers=bearer)
    ).status_code == 200
    theirs = await patch_flow(client, url, json={"name": "By editor"}, headers=other)
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["revision"] == 3

    # One leaving does not end the other's edit mode.
    assert (await client.delete(f"{url}edit-mode/", headers=other)).status_code == 200
    mine = (await client.get(url, headers=bearer)).json()
    assert mine["editing"] is True and mine["editors"] == []


async def test_a_service_key_cannot_enter_edit_mode(
    client, published, flows_enabled, bearer
):
    secret = await _service_key(client, bearer, space_id=published["space_id"])
    key = {API_KEY_HEADER: secret}
    url = f"/api/v1/flows/{published['flow'].id}/"

    refused = await client.post(f"{url}edit-mode/", headers=key)

    assert refused.status_code == 403, refused.text
    assert _gate_code(refused.json()) == "service_key_cannot_create_resources"
    assert (
        await patch_flow(client, url, json={"name": "x"}, headers=key)
    ).status_code == 403
