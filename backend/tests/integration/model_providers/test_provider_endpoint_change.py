"""Changing where a provider sends its key requires entering that key again."""

from uuid import uuid4

import pytest

from eneo.model_providers.domain.model_provider_service import ModelProviderService

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        return container.auth_service().create_access_token_for_user(admin)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_provider(client, token: str, *, endpoint: str, api_key: str) -> dict:
    response = await client.post(
        "/api/v1/admin/model-providers/",
        json={
            "name": f"provider-{uuid4().hex[:8]}",
            "provider_type": "hosted_vllm",
            "credentials": {"api_key": api_key},
            "config": {"endpoint": endpoint},
            "is_active": True,
        },
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _service(container) -> ModelProviderService:
    return ModelProviderService(
        container.model_provider_repository(), container.encryption_service()
    )


async def _decrypted_api_key(db_container, provider_id: str) -> str | None:
    async with db_container() as container:
        credentials = await _service(container).get_decrypted_credentials(provider_id)
        return credentials.get("api_key")


async def test_endpoint_change_without_a_new_key_is_rejected_and_nothing_changes(
    client, db_container, admin_token
):
    provider = await _create_provider(
        client, admin_token, endpoint="http://vllm-a:8000", api_key="secret-a"
    )

    response = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={"config": {"endpoint": "http://vllm-b:8000"}},
        headers=_auth(admin_token),
    )

    assert response.status_code == 400, response.text
    current = await client.get(
        f"/api/v1/admin/model-providers/{provider['id']}/", headers=_auth(admin_token)
    )
    assert current.json()["config"]["endpoint"] == "http://vllm-a:8000"
    assert await _decrypted_api_key(db_container, provider["id"]) == "secret-a"


async def test_masked_display_value_is_not_accepted_as_a_replacement(
    client, db_container, admin_token
):
    provider = await _create_provider(
        client, admin_token, endpoint="http://vllm-a:8000", api_key="secret-a"
    )

    response = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={
            "config": {"endpoint": "http://vllm-b:8000"},
            "credentials": {"api_key": provider["masked_api_key"]},
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 400, response.text
    assert await _decrypted_api_key(db_container, provider["id"]) == "secret-a"


async def test_endpoint_change_with_a_new_key_stores_it_encrypted(
    client, db_container, admin_token
):
    provider = await _create_provider(
        client, admin_token, endpoint="http://vllm-a:8000", api_key="secret-a"
    )

    response = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={
            "config": {"endpoint": "http://vllm-b:8000"},
            "credentials": {"api_key": "secret-b"},
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["config"]["endpoint"] == "http://vllm-b:8000"
    assert await _decrypted_api_key(db_container, provider["id"]) == "secret-b"
    async with db_container() as container:
        stored = await container.model_provider_repository().get_by_id(provider["id"])
        assert stored.credentials["api_key"] != "secret-b"


async def test_equivalent_endpoint_and_name_only_edits_keep_the_key(
    client, db_container, admin_token
):
    provider = await _create_provider(
        client, admin_token, endpoint="http://vllm-a:8000", api_key="secret-a"
    )

    equivalent = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={"config": {"endpoint": "HTTP://VLLM-A:8000/"}},
        headers=_auth(admin_token),
    )
    assert equivalent.status_code == 200, equivalent.text

    renamed = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={"name": f"renamed-{uuid4().hex[:6]}"},
        headers=_auth(admin_token),
    )
    assert renamed.status_code == 200, renamed.text
    assert await _decrypted_api_key(db_container, provider["id"]) == "secret-a"


async def test_credentialless_internal_provider_may_change_endpoint(
    client, admin_token
):
    provider = await _create_provider(
        client, admin_token, endpoint="http://vllm-a:8000", api_key=""
    )

    response = await client.put(
        f"/api/v1/admin/model-providers/{provider['id']}/",
        json={"config": {"endpoint": "http://vllm-b:8000"}},
        headers=_auth(admin_token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["config"]["endpoint"] == "http://vllm-b:8000"
