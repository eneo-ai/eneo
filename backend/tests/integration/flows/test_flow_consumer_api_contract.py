from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.flow_tables import FlowStepResults


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


async def _create_space(client, *, token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-consumer-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_published_flow(client, *, token: str, space_id: str) -> dict:
    create_response = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"consumer-flow-{uuid4().hex[:8]}",
            "description": "Runtime API consumer contract flow",
            "steps": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201, create_response.text
    flow_id = create_response.json()["id"]

    assistant_response = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"consumer-assistant-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert assistant_response.status_code == 201, assistant_response.text
    assistant_id = assistant_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": "Consumer API Flow",
            "description": "Runtime API consumer contract flow",
            "steps": [
                {
                    "assistant_id": assistant_id,
                    "step_order": 1,
                    "user_description": "Produce the consumer-visible result",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_response.status_code == 200, update_response.text
    flow = update_response.json()

    publish_response = await client.post(
        f"/api/v1/flows/{flow_id}/publish/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    flow["published_version"] = publish_response.json()["published_version"]
    return flow


async def _mark_first_step_completed(
    *,
    db_container,
    run_id: str,
    flow_id: str,
    tenant_id: str,
) -> None:
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == UUID(run_id))
            .where(FlowStepResults.flow_id == UUID(flow_id))
            .where(FlowStepResults.tenant_id == UUID(tenant_id))
            .values(
                status="completed",
                input_payload_json={"text": "hello"},
                output_payload_json={"answer": "consumer-visible"},
                num_tokens_input=3,
                num_tokens_output=5,
            )
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps(
    client,
    db_container,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    flow_id = flow["id"]

    published_response = await client.get(
        f"/api/v1/flows/{flow_id}/published/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert published_response.status_code == 200, published_response.text
    published_payload = published_response.json()
    assert published_payload["id"] == flow_id
    assert published_payload["runtime_paths"]["create_run"].endswith(
        f"/flows/{flow_id}/runs/"
    )

    run_payload = {
        "expected_flow_version": flow["published_version"],
        "input_payload_json": {"text": "hello"},
        "step_inputs": {},
    }
    idempotency_key = f"flow-run:{uuid4().hex}"
    first_run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=run_payload,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert first_run_response.status_code == 201, first_run_response.text
    first_run = first_run_response.json()

    replay_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=run_payload,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert replay_response.status_code == 201, replay_response.text
    assert replay_response.json()["id"] == first_run["id"]

    conflict_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            **run_payload,
            "input_payload_json": {"text": "different"},
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Idempotency-Key": idempotency_key,
        },
    )
    assert conflict_response.status_code == 400, conflict_response.text
    assert conflict_response.json()["code"] == "flow_run_idempotency_conflict"

    second_run_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "second"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second_run_response.status_code == 201, second_run_response.text

    list_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/?limit=1&offset=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert len(list_payload["items"]) == 1
    assert list_payload["has_more"] is True

    poll_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/{first_run['id']}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert poll_response.status_code == 200, poll_response.text
    assert poll_response.json()["id"] == first_run["id"]
    assert poll_response.json()["flow_id"] == flow_id

    await _mark_first_step_completed(
        db_container=db_container,
        run_id=first_run["id"],
        flow_id=flow_id,
        tenant_id=first_run["tenant_id"],
    )
    steps_response = await client.get(
        f"/api/v1/flows/{flow_id}/runs/{first_run['id']}/steps/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert steps_response.status_code == 200, steps_response.text
    steps = steps_response.json()
    assert len(steps) == 1
    assert steps[0]["status"] == "completed"
    assert steps[0]["output_payload_json"] == {"answer": "consumer-visible"}
