"""A flow picks a speaker identification service only from those its space may use."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_UNAVAILABLE = "flow_speaker_service_unavailable"
_CHOICE_REQUIRED = "flow_speaker_service_choice_required"
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

    # Without a pick the space's only speaker service is used when a run starts.
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


async def test_labels_without_a_pick_publish_only_when_the_space_has_one_service(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    first = await _connection(client, headers)
    second = await _connection(client, headers)
    await _grant(client, headers, space_id, first)
    one_service = await _publishable(client, headers, space_id, _metadata(None))
    published = await client.post(
        f"/api/v1/flows/{one_service}/publish/", headers=headers
    )
    assert published.status_code == 200, published.text

    await _grant(client, headers, space_id, first, second)
    several = await _publishable(client, headers, space_id, _metadata(None))
    published = await client.post(f"/api/v1/flows/{several}/publish/", headers=headers)
    _refusal(published, _CHOICE_REQUIRED)

    picked = await client.patch(
        f"/api/v1/flows/{several}/",
        json={"metadata_json": _metadata(second)},
        headers=headers,
    )
    assert picked.status_code == 200, picked.text
    published = await client.post(f"/api/v1/flows/{several}/publish/", headers=headers)
    assert published.status_code == 200, published.text
