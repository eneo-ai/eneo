"""A flow step runs an assistant its flow owns, and no other.

A flow's own assistants exist only once the flow does, so a new flow is
created empty and its steps are set by an update, which refuses an assistant
the flow does not own. No write can therefore tie an ordinary assistant to a
step, and deleting that assistant never meets a step that still runs it
(eneo-f282: the create path once allowed it, and the delete answered 500).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.flows.conftest import FlowProcessAuthHeaders

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _step(assistant_id: str) -> dict[str, object]:
    return {
        "assistant_id": assistant_id,
        "step_order": 1,
        "user_description": "Sammanfatta",
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }


async def _space_with_user_assistant(
    client: AsyncClient, headers: FlowProcessAuthHeaders
) -> tuple[str, str]:
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-ownership-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": f"egen-assistent-{uuid4().hex[:8]}", "space_id": space_id},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    return space_id, assistant.json()["id"]


async def test_a_new_flow_takes_no_steps(
    client: AsyncClient, flow_process_auth_headers: FlowProcessAuthHeaders
) -> None:
    headers = flow_process_auth_headers
    space_id, assistant_id = await _space_with_user_assistant(client, headers)

    refused = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": "Med steg", "steps": [_step(assistant_id)]},
        headers=headers,
    )

    assert refused.status_code == 422, refused.text
    errors = refused.json()["details"]["errors"]
    assert ["body", "steps"] in [error["location"] for error in errors]
    listed = await client.get(
        "/api/v1/flows/", params={"space_id": space_id}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


async def test_a_step_cannot_run_an_assistant_its_flow_does_not_own(
    client: AsyncClient, flow_process_auth_headers: FlowProcessAuthHeaders
) -> None:
    headers = flow_process_auth_headers
    space_id, assistant_id = await _space_with_user_assistant(client, headers)
    created = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": "Utan steg"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    flow = created.json()
    assert flow["steps"] == []

    refused = await client.patch(
        f"/api/v1/flows/{flow['id']}/",
        json={"steps": [_step(assistant_id)]},
        headers=headers,
    )

    assert refused.status_code == 400, refused.text
    assert "owned by the flow" in refused.json()["message"]
    # No step runs the assistant, so its owner can delete it.
    deleted = await client.delete(
        f"/api/v1/assistants/{assistant_id}/", headers=headers
    )
    assert deleted.status_code == 204, deleted.text
