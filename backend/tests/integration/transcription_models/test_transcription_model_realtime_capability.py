"""The realtime capability on tenant transcription models.

An admin marks a transcription model as able to transcribe live audio. Eneo's
live preview speaks vLLM's realtime dialect, so only models served by a
vLLM-compatible provider may carry the flag.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.model_providers_table import ModelProviders

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TENANT_TRANSCRIPTION_URL = "/api/v1/admin/tenant-models/transcription/"


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        return await container.user_repo().get_user_by_email("test@example.com")


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(default_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def openai_provider_id(db_container, default_user) -> str:
    """The provider `seed_default_models` creates for the default tenant."""
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(ModelProviders.id).where(
                ModelProviders.tenant_id == default_user.tenant_id,
                ModelProviders.provider_type == "openai",
            )
        )
        return str(result.scalar_one())


@pytest.fixture
async def vllm_provider_id(db_container, default_user) -> str:
    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=default_user.tenant_id,
            name=f"vadsa-{uuid4().hex[:8]}",
            provider_type="vllm",
            credentials={},
            config={"endpoint": "http://vadsa:8000"},
        )
        session.add(provider)
        await session.flush()
        return str(provider.id)


def _payload(provider_id: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "provider_id": provider_id,
        "name": "KlangAI/pianissimo-sv",
        "display_name": f"Pianissimo {uuid4().hex[:8]}",
    }
    body.update(overrides)
    return body


async def _stored_flag(db_container, model_id: str) -> bool:
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(TranscriptionModels.supports_realtime).where(
                TranscriptionModels.id == model_id
            )
        )
        return result.scalar_one()


async def test_a_new_transcription_model_is_not_realtime_by_default(
    client, admin_headers, vllm_provider_id, db_container
):
    response = await client.post(
        TENANT_TRANSCRIPTION_URL, headers=admin_headers, json=_payload(vllm_provider_id)
    )

    assert response.status_code == 200, response.text
    assert response.json()["supports_realtime"] is False
    assert await _stored_flag(db_container, response.json()["id"]) is False


async def test_admin_marks_a_vllm_served_model_as_realtime(
    client, admin_headers, vllm_provider_id, db_container
):
    response = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(vllm_provider_id, supports_realtime=True),
    )

    assert response.status_code == 200, response.text
    assert response.json()["supports_realtime"] is True
    assert await _stored_flag(db_container, response.json()["id"]) is True


async def test_realtime_is_refused_for_a_provider_without_the_vllm_dialect(
    client, admin_headers, openai_provider_id
):
    response = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(openai_provider_id, supports_realtime=True),
    )

    assert response.status_code == 400, response.text


async def test_update_turns_realtime_on_and_off_and_keeps_the_provider_rule(
    client, admin_headers, vllm_provider_id, openai_provider_id, db_container
):
    created = await client.post(
        TENANT_TRANSCRIPTION_URL, headers=admin_headers, json=_payload(vllm_provider_id)
    )
    model_id = created.json()["id"]

    turned_on = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": True},
    )
    assert turned_on.status_code == 200, turned_on.text
    assert await _stored_flag(db_container, model_id) is True

    turned_off = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": False},
    )
    assert turned_off.status_code == 200, turned_off.text
    assert await _stored_flag(db_container, model_id) is False

    openai_model = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(openai_provider_id),
    )
    refused = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{openai_model.json()['id']}/",
        headers=admin_headers,
        json={"supports_realtime": True},
    )
    assert refused.status_code == 400, refused.text


async def test_the_model_list_reports_the_realtime_capability(
    client, admin_headers, vllm_provider_id
):
    created = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(vllm_provider_id, supports_realtime=True),
    )

    listed = await client.get("/api/v1/transcription-models/", headers=admin_headers)

    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    match = next(item for item in items if item["id"] == created.json()["id"])
    assert match["supports_realtime"] is True
