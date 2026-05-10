from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.flow_tables import (
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepResults,
)
from intric.database.tables.roles_table import Roles
from intric.database.tables.users_table import users_roles_table
from intric.flows.enums import FlowRunReviewCheckpointState
from intric.roles.permissions import Permission


async def _noop_dispatch_flow_run_after_commit(**kwargs: object) -> None:
    _ = kwargs


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        session = container.session()
        user_repo = container.user_repo()
        auth_service = container.auth_service()

        role = Roles(
            name=f"Flow Consumer Test {uuid4().hex[:8]}",
            permissions=[Permission.FLOWS_MANAGE.value, Permission.FLOWS_RUN.value],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=admin_user.id, role_id=role.id)
        )
        await session.flush()

        refreshed_user = await user_repo.get_user_by_email(admin_user.email)
        return auth_service.create_access_token_for_user(refreshed_user)


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


async def _create_published_required_runtime_input_flow(
    client, *, token: str, space_id: str
) -> dict:
    create_response = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"required-runtime-input-flow-{uuid4().hex[:8]}",
            "description": "Runtime input required API contract flow",
            "steps": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_response.status_code == 201, create_response.text
    flow_id = create_response.json()["id"]

    assistant_response = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"required-runtime-input-assistant-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert assistant_response.status_code == 201, assistant_response.text
    assistant_id = assistant_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": "Required Runtime Input Flow",
            "description": "Runtime input required API contract flow",
            "steps": [
                {
                    "assistant_id": assistant_id,
                    "step_order": 1,
                    "user_description": "Use the uploaded document to produce a result",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": {
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "max_files": 1,
                            "input_format": "document",
                            "label": "Source document",
                            "description": "Upload the source document before starting the run.",
                        }
                    },
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


async def _open_first_step_review_checkpoint(
    *,
    db_container,
    run: dict,
    flow: dict,
    output_contract: dict[str, object],
    current_payload_json: dict[str, object],
) -> str:
    step = flow["steps"][0]
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(run["id"]))
            .values(status="awaiting_review")
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == UUID(run["id"]))
            .where(FlowStepResults.step_id == UUID(step["id"]))
            .values(
                status="completed",
                input_payload_json={"text": "hello"},
                output_payload_json=current_payload_json,
                num_tokens_input=3,
                num_tokens_output=5,
            )
        )
        checkpoint = FlowRunReviewCheckpoints(
            tenant_id=UUID(run["tenant_id"]),
            flow_id=UUID(flow["id"]),
            flow_run_id=UUID(run["id"]),
            step_id=UUID(step["id"]),
            step_order=1,
            attempt_no=1,
            state=FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
            revision=1,
            schema_version=1,
            original_payload_json=current_payload_json,
            current_payload_json=current_payload_json,
            step_label=step["user_description"],
            review_mode="view",
            output_type="json",
            output_contract_json=output_contract,
            requester_principal_type="user",
            requester_user_id=UUID(run["user_id"]) if run.get("user_id") else None,
        )
        session.add(checkpoint)
        await session.flush()
        return str(checkpoint.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        "intric.flows.api.flow_router_common.dispatch_flow_run_after_commit",
        _noop_dispatch_flow_run_after_commit,
    )

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_removed_top_level_file_ids_before_body_shape_errors(
    client,
    admin_token,
):
    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)

    response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": "not-an-int",
            "file_ids": [str(uuid4())],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["code"] == "flow_run_top_level_file_ids_not_supported"
    assert "step_inputs[step_id].file_ids" in payload["message"]
    assert payload["context"] == {
        "invalid_field": "file_ids",
        "expected_field": "step_inputs[step_id].file_ids",
        "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_create_rejects_missing_required_runtime_step_inputs(
    client,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        "intric.flows.api.flow_router_common.dispatch_flow_run_after_commit",
        _noop_dispatch_flow_run_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_required_runtime_input_flow(
        client,
        token=admin_token,
        space_id=space_id,
    )
    flow_id = flow["id"]

    contract_response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert contract_response.status_code == 200, contract_response.text
    contract = contract_response.json()
    required_step = contract["steps_requiring_input"][0]
    assert required_step["required"] is True

    base_payload = {
        "expected_flow_version": flow["published_version"],
        "input_payload_json": {"text": "hello"},
    }
    expected_context = {"step_ids": [required_step["step_id"]]}

    omitted_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json=base_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert omitted_response.status_code == 400, omitted_response.text
    omitted_payload = omitted_response.json()
    assert omitted_payload["code"] == "flow_run_required_step_input_missing"
    assert omitted_payload["message"] == "Required runtime input files are missing."
    assert omitted_payload["context"] == expected_context

    empty_response = await client.post(
        f"/api/v1/flows/{flow_id}/runs/",
        json={**base_payload, "step_inputs": {}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert empty_response.status_code == 400, empty_response.text
    empty_payload = empty_response.json()
    assert empty_payload["code"] == "flow_run_required_step_input_missing"
    assert empty_payload["message"] == omitted_payload["message"]
    assert empty_payload["context"] == expected_context


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_review_edit_returns_typed_contract_error_for_invalid_payload(
    client,
    db_container,
    admin_token,
    monkeypatch,
):
    monkeypatch.setattr(
        "intric.flows.api.flow_router_common.dispatch_flow_run_after_commit",
        _noop_dispatch_flow_run_after_commit,
    )

    space_id = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space_id)
    run_response = await client.post(
        f"/api/v1/flows/{flow['id']}/runs/",
        json={
            "expected_flow_version": flow["published_version"],
            "input_payload_json": {"text": "hello"},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    checkpoint_id = await _open_first_step_review_checkpoint(
        db_container=db_container,
        run=run,
        flow=flow,
        output_contract=output_contract,
        current_payload_json={
            "text": '{"summary":"Original."}',
            "structured": {"summary": "Original."},
            "webhook_delivered": False,
        },
    )

    response = await client.patch(
        f"/api/v1/flows/{flow['id']}/runs/{run['id']}/review-checkpoints/{checkpoint_id}/",
        json={
            "expected_checkpoint_revision": 1,
            "current_payload_json": {
                "text": '{"wrong":"shape"}',
                "structured": {"wrong": "shape"},
                "webhook_delivered": False,
            },
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["code"] == "typed_io_contract_violation"
    assert "Review checkpoint step 1 output" in payload["message"]
    assert payload["context"] == {
        "checkpoint_id": checkpoint_id,
        "step_id": flow["steps"][0]["id"],
        "step_order": 1,
        "payload_field": "structured",
    }
