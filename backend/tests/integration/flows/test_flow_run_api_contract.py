"""The run-side HTTP contract: every path ``/published/`` advertises is served.

External consumers integrate against these paths, so they are exercised
over HTTP with a user bearer, in the order a client follows them.
"""

from eneo.flows.definition import FlowDefinition, FormField, LlmStep
from tests.integration.flows.conftest import topic_field


def _definition(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[
            topic_field(),
            FormField(key="attachment", label="Bilaga", type="file", required=False),
        ],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="draft",
                input="{{form.topic}}",
                model_id=model_id,
            )
        ],
    )


async def test_run_side_paths_are_served_as_advertised(
    client,
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    flows_enabled,
    bearer,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "contract-model")
        space = await member_space(session, "Contract Space", [model.id])
        flow = await publish_flow(container, space, _definition(model.id))
    flow_id = str(flow.id)

    published = await client.get(f"/api/v1/flows/{flow_id}/published/", headers=bearer)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["id"] == flow_id and body["published_version"] == 1
    paths = body["runtime_paths"]
    assert paths["create_run"] == f"/api/v1/flows/{flow_id}/runs/"

    contract = await client.get(paths["run_contract"], headers=bearer)
    assert contract.status_code == 200
    assert [f["key"] for f in contract.json()["form_fields"]] == ["topic", "attachment"]

    upload = await client.post(
        paths["upload_runtime_file"],
        headers=bearer,
        files={"upload_file": ("bilaga.txt", b"hello from the api", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    # An unused upload can be taken back; afterwards it is gone.
    second = await client.post(
        paths["upload_runtime_file"],
        headers=bearer,
        files={"upload_file": ("unused.txt", b"never used", "text/plain")},
    )
    unused_id = second.json()["id"]
    delete_path = paths["delete_runtime_file_template"]
    assert (
        await client.delete(delete_path.replace("{file_id}", unused_id), headers=bearer)
    ).status_code == 204
    assert (
        await client.delete(delete_path.replace("{file_id}", unused_id), headers=bearer)
    ).status_code == 404

    run_body = {
        "values": {"topic": "hamnar"},
        "files": {"attachment": [file_id]},
        "run_label": "via api",
        "expected_flow_version": 1,
    }
    headers = {**bearer, "Idempotency-Key": "contract-key-1"}
    first = await client.post(paths["create_run"], json=run_body, headers=headers)
    assert first.status_code == 201, first.text
    replay = await client.post(paths["create_run"], json=run_body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    run_id = first.json()["id"]
    assert first.json()["status"] == "queued"
    assert [f["name"] for f in first.json()["input_files"]] == ["bilaga.txt"]

    # The upload now belongs to the run.
    assert (
        await client.delete(delete_path.replace("{file_id}", file_id), headers=bearer)
    ).status_code == 409

    def fill(template: str) -> str:
        return template.replace("{run_id}", run_id).replace("{file_id}", file_id)

    status = await client.get(fill(paths["get_run_status_template"]), headers=bearer)
    assert status.status_code == 200 and status.json()["status"] == "queued"
    assert "input_files" not in status.json()

    detail = await client.get(fill(paths["get_run_template"]), headers=bearer)
    assert detail.status_code == 200
    assert detail.json()["input_payload_json"] == {"topic": "hamnar"}

    steps = await client.get(fill(paths["list_steps_template"]), headers=bearer)
    assert steps.status_code == 200
    assert [s["key"] for s in steps.json()] == ["draft"]

    listed = await client.get(paths["list_runs"], headers=bearer)
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()["items"]] == [run_id]

    active = await client.get(
        fill(paths["review_checkpoints"]["active_template"]), headers=bearer
    )
    assert active.status_code == 200 and active.json() is None

    signed = await client.post(
        fill(paths["input_file_signed_url_template"]),
        json={"expires_in": 60},
        headers=bearer,
    )
    assert signed.status_code == 200, signed.text
    assert f"/api/v1/files/{file_id}/original/download/?token=" in signed.json()["url"]
    # The input is not an artifact: the artifact link says so.
    artifact = await client.post(
        fill(paths["artifact_signed_url_template"]), json={}, headers=bearer
    )
    assert artifact.status_code == 404

    cancelled = await client.post(fill(paths["cancel_run_template"]), headers=bearer)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_published_view_needs_a_published_flow(
    client,
    db_container,
    member_space,
    completion_model_factory,
    provider,
    flows_enabled,
    bearer,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "draft-model")
        space = await member_space(session, "Draft Space", [model.id])
        draft = await container.flow_service().create_flow(
            space_id=space.id,
            name="Draft",
            description=None,
            definition=_definition(model.id),
        )
    response = await client.get(f"/api/v1/flows/{draft.id}/published/", headers=bearer)
    assert response.status_code == 404
