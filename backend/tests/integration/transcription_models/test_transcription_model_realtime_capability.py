"""Live text on tenant transcription models.

An admin marks a transcription model as able to stream live text. Eneo's live
client speaks vLLM's realtime API, so the mark can be turned on only for a
provider that can carry it (``realtime.py``): vLLM with an endpoint, or OpenAI
with the endpoint of a gateway, and no outbound headers. The saved mark stays
when the provider changes later; ``streams_live`` says whether it applies now.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.model_providers_table import ModelProviders

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TENANT_TRANSCRIPTION_URL = "/api/v1/admin/tenant-models/transcription/"
PROVIDERS_URL = "/api/v1/admin/model-providers/"
GATEWAY = "https://gateway.example.se/v1"
HEADERS = [{"id": str(uuid4()), "name": "X-Org-Unit", "value": "unit"}]


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


async def _provider(
    db_container,
    tenant_id,
    *,
    provider_type: str = "openai",
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    outbound_headers: list[dict[str, Any]] | None = None,
) -> str:
    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=tenant_id,
            name=f"{provider_type}-{uuid4().hex[:8]}",
            provider_type=provider_type,
            credentials=credentials or {},
            config=config or {},
            outbound_headers=outbound_headers,
        )
        session.add(provider)
        await session.flush()
        return str(provider.id)


async def _change_provider(db_container, provider_id: str, **values: Any) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(ModelProviders)
            .where(ModelProviders.id == provider_id)
            .values(**values)
        )


@pytest.fixture
async def gateway_provider_id(db_container, default_user) -> str:
    """An OpenAI provider whose endpoint is a gateway serving vLLM's API."""
    return await _provider(
        db_container, default_user.tenant_id, config={"endpoint": GATEWAY}
    )


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


async def _listed(client, admin_headers, model_id: str) -> dict[str, Any]:
    listed = await client.get("/api/v1/transcription-models/", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    return next(item for item in listed.json()["items"] if item["id"] == model_id)


async def test_a_gateway_registered_as_openai_carries_live_text(
    client, admin_headers, gateway_provider_id, db_container
):
    created = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(gateway_provider_id, supports_realtime=True),
    )
    assert created.status_code == 200, created.text
    assert created.json()["streams_live"] is True

    existing = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(gateway_provider_id),
    )
    model_id = existing.json()["id"]
    assert existing.json()["streams_live"] is False

    turned_on = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": True},
    )

    assert turned_on.status_code == 200, turned_on.text
    assert await _stored_flag(db_container, model_id) is True
    assert (await _listed(client, admin_headers, model_id))["streams_live"] is True


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ({"config": {}}, "endpoint"),
        ({"config": {"endpoint": "https://api.openai.com"}}, "endpoint"),
        ({"config": {"endpoint": "https://api.openai.com/v1/"}}, "endpoint"),
        ({"config": {"endpoint": "HTTPS://API.OPENAI.COM:443/v1"}}, "endpoint"),
        ({"config": {"endpoint": "https://eu.api.openai.com/v1"}}, "endpoint"),
        (
            {"config": {"endpoint": GATEWAY}, "credentials": {"endpoint": ""}},
            "endpoint",
        ),
        (
            {
                "provider_type": "azure",
                "config": {"endpoint": GATEWAY, "api_version": "2024-06-01"},
            },
            "Choose such a provider",
        ),
        (
            {"provider_type": "anthropic", "config": {"endpoint": GATEWAY}},
            "Choose such a provider",
        ),
        (
            {
                "provider_type": "vllm",
                "config": {"endpoint": "http://vadsa:8000"},
                "outbound_headers": HEADERS,
            },
            "outbound headers",
        ),
    ],
)
async def test_turning_live_text_on_is_refused_with_what_to_do(
    client, admin_headers, default_user, db_container, provider, message
):
    provider_id = await _provider(db_container, default_user.tenant_id, **provider)

    on_create = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(provider_id, supports_realtime=True),
    )
    assert on_create.status_code == 400, on_create.text
    assert message in on_create.text

    created = await client.post(
        TENANT_TRANSCRIPTION_URL, headers=admin_headers, json=_payload(provider_id)
    )
    on_update = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{created.json()['id']}/",
        headers=admin_headers,
        json={"supports_realtime": True},
    )
    assert on_update.status_code == 400, on_update.text
    assert message in on_update.text
    assert await _stored_flag(db_container, created.json()["id"]) is False


@pytest.mark.parametrize(
    "change",
    [
        {"config": {}},
        {"credentials": {"endpoint": ""}},
        {"outbound_headers": HEADERS},
    ],
    ids=["endpoint removed", "endpoint shadowed", "headers added"],
)
async def test_a_saved_mark_stays_when_the_provider_stops_qualifying(
    client, admin_headers, gateway_provider_id, db_container, change
):
    created = await client.post(
        TENANT_TRANSCRIPTION_URL,
        headers=admin_headers,
        json=_payload(gateway_provider_id, supports_realtime=True),
    )
    model_id = created.json()["id"]

    await _change_provider(db_container, gateway_provider_id, **change)

    listed = await _listed(client, admin_headers, model_id)
    assert listed["supports_realtime"] is True
    assert listed["streams_live"] is False

    # Editors resend the saved mark with every change: that is not turning it
    # on, so it is accepted and the other field is saved.
    edited = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": True, "description": "Kept"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["description"] == "Kept"
    assert edited.json()["supports_realtime"] is True
    assert edited.json()["streams_live"] is False

    turned_off = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": False},
    )
    assert turned_off.status_code == 200, turned_off.text
    assert await _stored_flag(db_container, model_id) is False

    turned_on_again = await client.put(
        f"{TENANT_TRANSCRIPTION_URL}{model_id}/",
        headers=admin_headers,
        json={"supports_realtime": True},
    )
    assert turned_on_again.status_code == 400, turned_on_again.text


async def test_the_provider_list_says_whether_each_provider_carries_live_text(
    client, admin_headers, default_user, gateway_provider_id, db_container
):
    without_endpoint = await _provider(db_container, default_user.tenant_id)
    with_headers = await _provider(
        db_container,
        default_user.tenant_id,
        provider_type="vllm",
        config={"endpoint": "http://vadsa:8000"},
        outbound_headers=HEADERS,
    )
    azure = await _provider(
        db_container,
        default_user.tenant_id,
        provider_type="azure",
        config={"endpoint": GATEWAY},
    )

    listed = await client.get(PROVIDERS_URL, headers=admin_headers)

    assert listed.status_code == 200, listed.text
    eligibility = {item["id"]: item["realtime_eligibility"] for item in listed.json()}
    assert eligibility[gateway_provider_id] == "eligible"
    assert eligibility[without_endpoint] == "endpoint_required"
    assert eligibility[with_headers] == "outbound_headers_configured"
    assert eligibility[azure] == "unsupported_provider"
