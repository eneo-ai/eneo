"""Who may do what with flows over HTTP: a user bearer, a service key in the
flow's space, a service key of another space, and a service key on a draft."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from eneo.flows.definition import FlowDefinition, LlmStep
from tests.integration.flows.conftest import topic_field

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


def _definition(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="p",
                input="{{form.topic}}",
                model_id=model_id,
            )
        ],
    )


@pytest.fixture
async def published(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "authz-model")
        space = await member_space(session, "Authz Space", [model.id])
        other = await member_space(session, "Other Space", [model.id])
        flow = await publish_flow(container, space, _definition(model.id))
        draft = await container.flow_service().create_flow(
            space_id=space.id,
            name="Draft",
            description=None,
            definition=_definition(model.id),
        )
        # Read inside the session: the rows detach when it closes.
        ids = {"space_id": space.id, "other_space_id": other.id}
    return {"flow": flow, "draft": draft, **ids}


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
