"""Published audio flows that chose a speaker service, set up as an
administrator would: the service, its grants and its switch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.spaces_table import Spaces, SpacesTranscriptionModels
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.transcription_services_table import (
    TranscriptionServiceConnections,
)

Headers = Mapping[str, str]
SERVICES = "/api/v1/admin/transcription-services/"


async def shared_space(client: AsyncClient, headers: Headers) -> str:
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"speakers-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def personal_space(db_container, user_id: UUID, tenant_id: UUID) -> str:
    """The user's personal space, made when they have none yet."""
    async with db_container() as container:
        session = container.session()
        space_id = await session.scalar(
            sa.select(Spaces.id).where(Spaces.user_id == user_id)
        )
        if space_id is None:
            space = Spaces(name="Personal", tenant_id=tenant_id, user_id=user_id)
            session.add(space)
            await session.flush()
            space_id = space.id
    return str(space_id)


async def speaker_service(client: AsyncClient, headers: Headers) -> str:
    response = await client.post(
        SERVICES,
        json={
            "name": f"vemsa-{uuid4().hex[:8]}",
            "endpoint_url": "https://vemsa.example.se/",
            "api_key": "secret",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def grant(
    client: AsyncClient, headers: Headers, space_id: str, *service_ids: str
) -> None:
    """Give the space exactly these speaker services."""
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"transcription_services": [{"id": id_} for id_ in service_ids]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def switch_off(client: AsyncClient, headers: Headers, service_id: str) -> None:
    response = await client.patch(
        f"{SERVICES}{service_id}/", json={"is_enabled": False}, headers=headers
    )
    assert response.status_code == 200, response.text


async def classify_below(
    db_container,
    *,
    tenant_id: UUID,
    space_id: str,
    service_id: str,
    kept: Sequence[str] = (),
) -> None:
    """Classify the space above ``service_id`` and the ``kept`` services at
    its level, with classifications on: the service stays linked but the space
    may no longer use it."""
    async with db_container() as container:
        session = container.session()
        low, high = (
            SecurityClassifications(
                tenant_id=tenant_id,
                name=f"{name}-{uuid4().hex[:6]}",
                security_level=level,
            )
            for name, level in (("low", 1), ("high", 20))
        )
        session.add_all([low, high])
        await session.flush()
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == UUID(space_id))
            .values(security_classification_id=high.id)
        )
        for level, ids in ((low, [service_id]), (high, kept)):
            await session.execute(
                sa.update(TranscriptionServiceConnections)
                .where(
                    TranscriptionServiceConnections.id.in_([UUID(id_) for id_ in ids])
                )
                .values(security_classification_id=level.id)
            )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(security_enabled=True)
        )


async def published_speaker_flow(
    client: AsyncClient,
    headers: Headers,
    db_container,
    *,
    space_id: str,
    service_id: str,
) -> str:
    """A published flow in ``space_id`` that transcribes a recording, which a
    run may leave out, and chose ``service_id`` to label its speakers."""
    provider = await client.post(
        "/api/v1/admin/model-providers/",
        json={
            "name": f"vadsa-{uuid4().hex[:8]}",
            "provider_type": "vllm",
            "credentials": {"api_key": "provider-secret"},
            "config": {"endpoint": "http://127.0.0.1:9/v1"},
        },
        headers=headers,
    )
    assert provider.status_code == 200, provider.text
    model = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        json={
            "provider_id": provider.json()["id"],
            "name": f"asr-{uuid4().hex[:6]}",
            "display_name": f"ASR {uuid4().hex[:8]}",
        },
        headers=headers,
    )
    assert model.status_code == 200, model.text
    model_id = model.json()["id"]
    async with db_container() as container:
        container.session().add(
            SpacesTranscriptionModels(
                space_id=UUID(space_id), transcription_model_id=UUID(model_id)
            )
        )
    created = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": f"Protokoll {uuid4().hex[:8]}"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    assistant = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"speakers-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text
    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": f"Protokoll {flow_id[:8]}",
            "description": None,
            "steps": [
                {
                    "assistant_id": assistant.json()["id"],
                    "step_order": 1,
                    "user_description": "Transkribera mötet",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                    "output_type": "text",
                    "input_config": {
                        "runtime_input": {
                            "enabled": True,
                            "required": False,
                            "input_format": "audio",
                            "description": "Spela in mötet.",
                        }
                    },
                }
            ],
            "metadata_json": {
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": model_id},
                    "transcription_language": "sv",
                    "transcription_speaker_service": {"id": service_id},
                }
            },
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    assert published.status_code == 200, published.text
    return flow_id
