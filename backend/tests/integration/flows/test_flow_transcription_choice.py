"""A flow labels speakers only with the service its author chose, and picks it
only from those its space may use."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate
from tests.integration.flows.test_flow_live_transcription_session import _draft_flow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_UNAVAILABLE = "flow_speaker_service_unavailable"
_NOT_CHOSEN = "flow_speaker_service_not_chosen"
_INVALID = "flow_audio_transcription_invalid"


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt):
    """An administrator who connects services and edits flows in shared spaces."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"speaker-service-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ADMIN,
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    return {"Authorization": f"Bearer {token}"}


async def _space(client: AsyncClient, headers) -> str:
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"speakers-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _connection(client: AsyncClient, headers) -> str:
    response = await client.post(
        "/api/v1/admin/transcription-services/",
        json={
            "name": f"vemsa-{uuid4().hex[:8]}",
            "endpoint_url": "https://vemsa.example.se/",
            "api_key": "secret",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _grant(client: AsyncClient, headers, space_id: str, *ids: str) -> None:
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"transcription_services": [{"id": id_} for id_ in ids]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _metadata(service_id: str | None, **wizard: Any) -> dict[str, Any]:
    picked = (
        {}
        if service_id is None
        else {"transcription_speaker_service": {"id": service_id}}
    )
    return {"wizard": {"transcription_enabled": True, **picked, **wizard}}


async def _create(client: AsyncClient, headers, space_id: str, metadata):
    return await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"Protokoll {uuid4().hex[:6]}",
            "steps": [],
            "metadata_json": metadata,
        },
        headers=headers,
    )


def _refusal(response, code: str) -> None:
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == code
    assert body["context"]["issue_code"] == code


async def test_a_flow_picks_only_a_speaker_service_its_space_may_use(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    vemsa = await _connection(client, headers)

    _refusal(await _create(client, headers, space_id, _metadata(vemsa)), _UNAVAILABLE)

    await _grant(client, headers, space_id, vemsa)
    created = await _create(client, headers, space_id, _metadata(vemsa))
    assert created.status_code == 201, created.text
    assert created.json()["metadata_json"]["wizard"][
        "transcription_speaker_service"
    ] == {"id": vemsa}

    # A draft may be saved before the choice is made.
    created = await _create(client, headers, space_id, _metadata(None))
    assert created.status_code == 201, created.text


async def test_a_draft_keeps_a_revoked_pick_but_cannot_publish_it(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    vemsa = await _connection(client, headers)
    await _grant(client, headers, space_id, vemsa)
    created = await _create(client, headers, space_id, _metadata(vemsa))
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    assistant = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"steg-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text

    await _grant(client, headers, space_id)
    # An administrator's later change never blocks unrelated edits.
    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": "Protokoll",
            "steps": [
                {
                    "assistant_id": assistant.json()["id"],
                    "step_order": 1,
                    "user_description": "Sammanfatta",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                }
            ],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    # Resending the stored choice unchanged is not a new pick either.
    resent = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={"metadata_json": _metadata(vemsa)},
        headers=headers,
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["metadata_json"]["wizard"][
        "transcription_speaker_service"
    ] == {"id": vemsa}

    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    _refusal(published, _UNAVAILABLE)

    # A pick that is switched off is not used, so it does not block publishing.
    switched_off = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={"metadata_json": _metadata(vemsa, transcription_diarization=False)},
        headers=headers,
    )
    assert switched_off.status_code == 200, switched_off.text
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    assert published.status_code == 200, published.text


async def _publishable(client: AsyncClient, headers, space_id: str, metadata) -> str:
    """A flow with one text step, so publishing checks only the choice."""
    created = await _create(client, headers, space_id, metadata)
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    assistant = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"steg-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text
    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": f"Protokoll {uuid4().hex[:6]}",
            "steps": [
                {
                    "assistant_id": assistant.json()["id"],
                    "step_order": 1,
                    "user_description": "Sammanfatta",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                }
            ],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    return flow_id


async def test_a_malformed_pick_is_refused_even_without_audio_steps(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)

    refused = await _create(client, headers, space_id, _metadata("not-a-uuid"))

    _refusal(refused, _INVALID)


async def _publish(client: AsyncClient, headers, flow_id: str):
    return await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)


async def test_labels_without_a_chosen_service_publish_only_where_none_can_be_chosen(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    # A space without a service: the flow's own setting labels nothing there.
    simply_transcribes = await _publishable(client, headers, space_id, _metadata(None))
    published = await _publish(client, headers, simply_transcribes)
    assert published.status_code == 200, published.text

    vemsa = await _connection(client, headers)
    await _grant(client, headers, space_id, vemsa)
    # Saving the draft is never refused for a missing choice; publishing is.
    flow_id = await _publishable(client, headers, space_id, _metadata(None))
    _refusal(await _publish(client, headers, flow_id), _NOT_CHOSEN)

    # Nothing is chosen for the flow: its author chooses, or switches labels off.
    switched_off = await _publishable(
        client, headers, space_id, _metadata(None, transcription_diarization=False)
    )
    published = await _publish(client, headers, switched_off)
    assert published.status_code == 200, published.text
    chosen = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={"metadata_json": _metadata(vemsa)},
        headers=headers,
    )
    assert chosen.status_code == 200, chosen.text
    published = await _publish(client, headers, flow_id)
    assert published.status_code == 200, published.text


@pytest.mark.parametrize("space_has_a_service", [False, True])
async def test_a_step_that_maps_speakers_publishes_only_with_a_chosen_service(
    client: AsyncClient,
    flow_process_auth_headers,
    db_container,
    space_has_a_service: bool,
):
    headers = dict(flow_process_auth_headers)
    space_id = await _space(client, headers)
    vemsa = await _connection(client, headers)
    if space_has_a_service:
        await _grant(client, headers, space_id, vemsa)
    # The step needs the labels whatever the flow's own setting says. The draft
    # is saved without a choice.
    flow = await _draft_flow(
        client,
        headers,
        db_container,
        space_id=space_id,
        speaker_mapping=True,
        wizard={"transcription_diarization": False},
    )

    _refusal(await _publish(client, headers, flow.flow_id), _NOT_CHOSEN)

    # The step's need overrides the flow's own setting: a choice that is
    # switched off is the one every run uses, so it must be usable here.
    chosen = await _draft_flow(
        client,
        headers,
        db_container,
        space_id=space_id,
        speaker_mapping=True,
        wizard={
            "transcription_diarization": False,
            "transcription_speaker_service": {"id": vemsa},
        },
    )
    published = await _publish(client, headers, chosen.flow_id)
    if space_has_a_service:
        assert published.status_code == 200, published.text
    else:
        _refusal(published, _UNAVAILABLE)
