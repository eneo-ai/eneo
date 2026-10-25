"""An active flow name is unique within its space.

The partial unique index `uq_flows_space_id_name_active` is the only arbiter:
a second create, a rename and the loser of two concurrent requests all fail at
the same statement, so the sequential cases below cover the race as well.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import ErrorCodes
from tests.integration.flows.conftest import FlowProcessAuthHeaders

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _space(client: AsyncClient, headers: FlowProcessAuthHeaders) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-name-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create(
    client: AsyncClient, headers: FlowProcessAuthHeaders, space_id: str, name: str
) -> Response:
    return await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": name},
        headers=headers,
    )


def _assert_name_taken(response: Response) -> None:
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == FlowApiErrorCode.FLOW_NAME_TAKEN.value
    assert body["eneo_error_code"] == ErrorCodes.CONFLICT


async def test_a_second_flow_with_an_active_name_of_the_space_is_refused(
    client: AsyncClient, flow_process_auth_headers: FlowProcessAuthHeaders
) -> None:
    # Kills the mutant that lets the unique-index violation leave
    # FlowRepository.create untranslated (HTTP 500).
    headers = flow_process_auth_headers
    space_id = await _space(client, headers)
    first = await _create(client, headers, space_id, "Samma namn")
    assert first.status_code == 201, first.text

    _assert_name_taken(await _create(client, headers, space_id, "Samma namn"))

    # The name is taken per space and only while its flow is active.
    other_space = await _create(
        client, headers, await _space(client, headers), "Samma namn"
    )
    assert other_space.status_code == 201, other_space.text
    deleted = await client.delete(
        f"/api/v1/flows/{first.json()['id']}/", headers=headers
    )
    assert deleted.status_code == 204, deleted.text
    again = await _create(client, headers, space_id, "Samma namn")
    assert again.status_code == 201, again.text


async def test_a_rename_onto_an_active_name_is_refused_and_changes_nothing(
    client: AsyncClient, flow_process_auth_headers: FlowProcessAuthHeaders
) -> None:
    # Kills the same mutant in FlowRepository._advance_draft, and the one that
    # commits the half-applied update: the draft keeps its name and revision.
    headers = flow_process_auth_headers
    space_id = await _space(client, headers)
    taken = await _create(client, headers, space_id, "Upptaget namn")
    other = await _create(client, headers, space_id, "Annat namn")
    assert taken.status_code == 201 and other.status_code == 201
    flow_url = f"/api/v1/flows/{other.json()['id']}/"

    _assert_name_taken(
        await client.patch(flow_url, json={"name": "Upptaget namn"}, headers=headers)
    )

    after = (await client.get(flow_url, headers=headers)).json()
    assert (after["name"], after["draft_revision"]) == (
        "Annat namn",
        other.json()["draft_revision"],
    )
