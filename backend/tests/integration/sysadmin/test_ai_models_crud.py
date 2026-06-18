"""Integration tests for deprecated sysadmin global model CRUD endpoints."""

from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


COMPLETION_CREATE_PAYLOAD = {
    "name": "gpt-4-test",
    "nickname": "GPT-4 Test",
    "family": "openai",
    "max_input_tokens": 8000,
    "max_output_tokens": 4096,
    "is_deprecated": False,
    "stability": "stable",
    "hosting": "usa",
    "open_source": False,
    "description": "Test model for integration testing",
    "org": "OpenAI",
    "vision": True,
    "reasoning": False,
    "base_url": "https://api.openai.com/v1",
    "litellm_model_name": "gpt-4",
}

EMBEDDING_CREATE_PAYLOAD = {
    "name": "text-embedding-3-small-test",
    "nickname": "Embedding Test",
    "family": "openai",
    "dimensions": 1536,
    "max_input": 8191,
    "is_deprecated": False,
    "stability": "stable",
    "hosting": "usa",
    "open_source": False,
    "description": "Test embedding model",
    "org": "OpenAI",
    "litellm_model_name": "text-embedding-3-small",
}


async def test_completion_model_create_requires_sysadmin_auth(client):
    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        json=COMPLETION_CREATE_PAYLOAD,
    )

    assert response.status_code == 401


async def test_legacy_completion_model_crud_returns_gone(client, super_admin_token):
    model_id = uuid4()
    headers = {"X-API-Key": super_admin_token}

    create_response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers=headers,
        json=COMPLETION_CREATE_PAYLOAD,
    )
    update_response = await client.put(
        f"/api/v1/sysadmin/completion-models/{model_id}/metadata",
        headers=headers,
        json={"nickname": "Updated"},
    )
    delete_response = await client.delete(
        f"/api/v1/sysadmin/completion-models/{model_id}",
        headers=headers,
    )

    assert create_response.status_code == 410
    assert update_response.status_code == 410
    assert delete_response.status_code == 410
    assert "tenant-owned models" in create_response.json()["detail"]


async def test_embedding_model_create_requires_sysadmin_auth(client):
    response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        json=EMBEDDING_CREATE_PAYLOAD,
    )

    assert response.status_code == 401


async def test_legacy_embedding_model_crud_returns_gone(client, super_admin_token):
    model_id = uuid4()
    headers = {"X-API-Key": super_admin_token}

    create_response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        headers=headers,
        json=EMBEDDING_CREATE_PAYLOAD,
    )
    update_response = await client.put(
        f"/api/v1/sysadmin/embedding-models/{model_id}/metadata",
        headers=headers,
        json={"nickname": "Updated"},
    )
    delete_response = await client.delete(
        f"/api/v1/sysadmin/embedding-models/{model_id}",
        headers=headers,
    )

    assert create_response.status_code == 410
    assert update_response.status_code == 410
    assert delete_response.status_code == 410
    assert "tenant-owned models" in create_response.json()["detail"]
