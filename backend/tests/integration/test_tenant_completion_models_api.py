from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from eneo.authentication.auth_service import AuthService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.model_providers_table import ModelProviders


@pytest.fixture
async def admin_bearer_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        assert isinstance(auth_service, AuthService)
        return auth_service.create_access_token_for_user(admin_user)


@pytest.mark.integration
async def test_create_tenant_completion_model_uses_split_token_fields(
    client,
    db_container,
    admin_user,
    admin_bearer_token,
):
    provider_name = f"openai-provider-{uuid4()}"

    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=provider_name,
            provider_type="openai",
            credentials={"api_key": "test-openai-key"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()
        provider_id = provider.id
        await session.commit()

    response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={
            "provider_id": str(provider_id),
            "name": "gpt-5.4-mini",
            "display_name": "gpt-5.4-mini",
            "max_input_tokens": 272000,
            "max_output_tokens": 128000,
            "vision": True,
            "reasoning": True,
            "supports_tool_calling": True,
            "hosting": "usa",
            "family": "openai",
            "is_active": True,
            "is_default": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    model_id = UUID(payload["id"])
    assert payload["max_input_tokens"] == 272000
    assert payload["max_output_tokens"] == 128000
    assert payload["token_limit"] == 272000

    async with db_container() as container:
        session = container.session()
        created_model = await session.scalar(
            select(CompletionModels).where(CompletionModels.id == model_id)
        )
        assert created_model is not None
        max_input_tokens = created_model.max_input_tokens
        max_output_tokens = created_model.max_output_tokens
        token_limit_column = await session.scalar(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'completion_models'
                  AND column_name = 'token_limit'
                """
            )
        )

    assert max_input_tokens == 272000
    assert max_output_tokens == 128000
    assert token_limit_column is None


@pytest.mark.integration
async def test_update_tenant_completion_model_keeps_token_limit_as_api_alias(
    client,
    db_container,
    admin_user,
    admin_bearer_token,
):
    provider_name = f"openai-provider-{uuid4()}"

    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=provider_name,
            provider_type="openai",
            credentials={"api_key": "test-openai-key"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()
        provider_id = provider.id
        await session.commit()

    create_response = await client.post(
        "/api/v1/admin/tenant-models/completion/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={
            "provider_id": str(provider_id),
            "name": "gpt-5.4-mini",
            "display_name": "gpt-5.4-mini",
            "max_input_tokens": 272000,
            "max_output_tokens": 128000,
        },
    )
    assert create_response.status_code == 200, create_response.text
    model_id = UUID(create_response.json()["id"])

    update_response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={
            "max_input_tokens": 300000,
            "max_output_tokens": 120000,
        },
    )

    assert update_response.status_code == 200, update_response.text
    update_payload = update_response.json()
    assert update_payload["max_input_tokens"] == 300000
    assert update_payload["max_output_tokens"] == 120000
    assert update_payload["token_limit"] == 300000

    async with db_container() as container:
        session = container.session()
        created_model = await session.scalar(
            select(CompletionModels).where(CompletionModels.id == model_id)
        )
        assert created_model is not None
        assert created_model.max_input_tokens == 300000
        assert created_model.max_output_tokens == 120000
