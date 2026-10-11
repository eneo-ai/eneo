"""A flow labels speakers only with the service its author chose, and picks it
only from those its space may use. A draft that asks for labels without a
choice is written with the organisation's default, when an administrator
marked one the space may use."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.flow_tables import FlowVersions
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


_SERVICES = "/api/v1/admin/transcription-services/"


async def _mark_default(client: AsyncClient, headers, service_id: str) -> None:
    response = await client.patch(
        f"{_SERVICES}{service_id}/", json={"is_default": True}, headers=headers
    )
    assert response.status_code == 200, response.text


def _chosen(response) -> dict[str, Any] | None:
    assert response.status_code in (200, 201), response.text
    wizard = (response.json()["metadata_json"] or {}).get("wizard", {})
    return wizard.get("transcription_speaker_service")


async def _save(client: AsyncClient, headers, flow_id: str, **body: Any):
    return await client.patch(f"/api/v1/flows/{flow_id}/", json=body, headers=headers)


async def test_a_draft_that_asks_for_labels_without_a_choice_gets_the_default(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    vemsa, other = (
        await _connection(client, headers),
        await _connection(client, headers),
    )
    await _grant(client, headers, space_id, vemsa, other)
    await _mark_default(client, headers, vemsa)

    created = await _create(client, headers, space_id, _metadata(None))
    assert _chosen(created) == {"id": vemsa}
    flow_id = created.json()["id"]
    stored = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert _chosen(stored) == {"id": vemsa}

    # A choice is never replaced, and a flow that does not ask gets none.
    kept = await _create(client, headers, space_id, _metadata(other))
    assert _chosen(kept) == {"id": other}
    labels_off = _metadata(None, transcription_diarization=False)
    assert _chosen(await _create(client, headers, space_id, labels_off)) is None
    no_audio = {"wizard": {"transcription_enabled": False}}
    assert _chosen(await _create(client, headers, space_id, no_audio)) is None

    # The editor clears the choice when labels are switched off; switching
    # them on again asks again, so the default is written again.
    off = await _save(client, headers, flow_id, metadata_json=labels_off)
    assert _chosen(off) is None
    on = await _save(client, headers, flow_id, metadata_json=_metadata(None))
    assert _chosen(on) == {"id": vemsa}


@pytest.mark.parametrize("default", ["none_marked", "not_granted", "switched_off"])
async def test_nothing_is_filled_without_a_default_the_space_may_use(
    client: AsyncClient, headers, default: str
):
    space_id = await _space(client, headers)
    vemsa, other = (
        await _connection(client, headers),
        await _connection(client, headers),
    )
    # The space has a service to use in every case: none is chosen for the flow.
    await _grant(
        client,
        headers,
        space_id,
        *([other] if default == "not_granted" else [vemsa, other]),
    )
    if default != "none_marked":
        await _mark_default(client, headers, vemsa)
    if default == "switched_off":
        switched_off = await client.patch(
            f"{_SERVICES}{vemsa}/", json={"is_enabled": False}, headers=headers
        )
        assert switched_off.status_code == 200, switched_off.text

    created = await _create(client, headers, space_id, _metadata(None))

    assert _chosen(created) is None
    saved = await _save(
        client, headers, created.json()["id"], metadata_json=_metadata(None)
    )
    assert _chosen(saved) is None


async def test_steps_that_start_naming_speakers_get_the_default_without_a_metadata_write(
    client: AsyncClient, headers
):
    space_id = await _space(client, headers)
    vemsa, other = (
        await _connection(client, headers),
        await _connection(client, headers),
    )
    await _grant(client, headers, space_id, vemsa)
    await _mark_default(client, headers, vemsa)
    labels_off = {
        "transcription_diarization": False,
        "transcription_model": {"id": str(uuid4())},
    }
    form = {
        "form_schema": {
            "fields": [{"name": "deltagare", "type": "list", "label": "Deltagare"}]
        }
    }

    async def saved_with_a_step_that_names_speakers(service_id: str | None):
        created = await _create(
            client, headers, space_id, _metadata(service_id, **labels_off) | form
        )
        # The flow's own setting is off, so nothing is asked of it yet.
        assert _chosen(created) == (None if service_id is None else {"id": service_id})
        flow_id = created.json()["id"]
        assistant = await client.post(
            f"/api/v1/flows/{flow_id}/assistants/",
            json={"name": f"steg-{uuid4().hex[:6]}"},
            headers=headers,
        )
        assert assistant.status_code == 201, assistant.text
        step = {"assistant_id": assistant.json()["id"], "output_type": "text"}
        return await _save(
            client,
            headers,
            flow_id,
            steps=[
                step
                | {
                    "step_order": 1,
                    "user_description": "Transkribera",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                },
                step
                | {
                    "step_order": 2,
                    "user_description": "Vem är vem?",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_mode": "speaker_mapping",
                    "output_type": "json",
                    "output_config": {
                        "speaker_mapping": {"participants_field": "deltagare"}
                    },
                    "review_policy": {"mode": "edit"},
                },
            ],
        )

    # The write names no metadata; the flow it ends with asks for labels.
    assert _chosen(await saved_with_a_step_that_names_speakers(None)) == {"id": vemsa}
    # A choice stays, also one the space may not use: publishing refuses it.
    assert _chosen(await saved_with_a_step_that_names_speakers(other)) == {"id": other}


async def test_publishing_fills_nothing_and_a_published_version_keeps_its_service(
    client: AsyncClient, headers, db_container
):
    space_id = await _space(client, headers)
    vemsa, other = (
        await _connection(client, headers),
        await _connection(client, headers),
    )
    await _grant(client, headers, space_id, vemsa, other)
    # Saved before any default was marked: it asks for labels and chose none.
    flow_id = await _publishable(client, headers, space_id, _metadata(None))
    await _mark_default(client, headers, vemsa)

    _refusal(await _publish(client, headers, flow_id), _NOT_CHOSEN)
    stored = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert _chosen(stored) is None

    # One save writes the default as the flow's choice, and it publishes.
    saved = await _save(client, headers, flow_id, metadata_json=_metadata(None))
    assert _chosen(saved) == {"id": vemsa}
    assert _chosen(await _publish(client, headers, flow_id)) == {"id": vemsa}

    await _mark_default(client, headers, other)
    stored = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert _chosen(stored) == {"id": vemsa}
    async with db_container() as container:
        [definition] = await container.session().scalars(
            sa.select(FlowVersions.definition_json).where(
                FlowVersions.flow_id == UUID(flow_id)
            )
        )
    assert definition["metadata_json"]["wizard"]["transcription_speaker_service"] == {
        "id": vemsa
    }
