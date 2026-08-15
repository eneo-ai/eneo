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
async def test_strict_tool_schema_support_is_off_until_an_admin_declares_it(
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
            "name": "gpt-5.6-luna",
            "display_name": "gpt-5.6-luna",
            "max_input_tokens": 272000,
            "max_output_tokens": 128000,
            "supports_tool_calling": True,
        },
    )
    assert create_response.status_code == 200, create_response.text
    model_id = UUID(create_response.json()["id"])
    assert create_response.json()["supports_strict_tool_schema"] is False

    declare_response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={"supports_strict_tool_schema": True},
    )
    assert declare_response.status_code == 200, declare_response.text
    assert declare_response.json()["supports_strict_tool_schema"] is True

    unrelated_response = await client.put(
        f"/api/v1/admin/tenant-models/completion/{model_id}/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={"description": "Measured strict-tool route"},
    )
    assert unrelated_response.status_code == 200, unrelated_response.text
    assert unrelated_response.json()["supports_strict_tool_schema"] is True

    async with db_container() as container:
        session = container.session()
        stored_model = await session.scalar(
            select(CompletionModels).where(CompletionModels.id == model_id)
        )
        assert stored_model is not None
        assert stored_model.supports_strict_tool_schema is True


@pytest.mark.integration
async def test_moving_a_provider_endpoint_withdraws_its_strict_declarations(
    client,
    db_container,
    admin_user,
    admin_bearer_token,
):
    async with db_container() as container:
        session = container.session()
        moved_provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=f"gateway-{uuid4()}",
            provider_type="openai",
            credentials={"api_key": "test-openai-key"},
            config={"endpoint": "https://gateway.invalid/v1"},
            is_active=True,
        )
        untouched_provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=f"stable-{uuid4()}",
            provider_type="openai",
            credentials={"api_key": "test-openai-key"},
            config={"endpoint": "https://stable.invalid/v1"},
            is_active=True,
        )
        session.add_all([moved_provider, untouched_provider])
        await session.flush()
        moved_provider_id = moved_provider.id
        untouched_provider_id = untouched_provider.id
        await session.commit()

    model_ids: dict[UUID, UUID] = {}
    for provider_id in (moved_provider_id, untouched_provider_id):
        response = await client.post(
            "/api/v1/admin/tenant-models/completion/",
            headers={"Authorization": f"Bearer {admin_bearer_token}"},
            json={
                "provider_id": str(provider_id),
                "name": f"gpt-5.6-luna-{provider_id}",
                "display_name": f"Luna via {provider_id}",
                "max_input_tokens": 272000,
                "max_output_tokens": 128000,
                "supports_tool_calling": True,
                "supports_strict_tool_schema": True,
            },
        )
        assert response.status_code == 200, response.text
        model_ids[provider_id] = UUID(response.json()["id"])

    move_response = await client.put(
        f"/api/v1/admin/model-providers/{moved_provider_id}/",
        headers={"Authorization": f"Bearer {admin_bearer_token}"},
        json={"config": {"endpoint": "https://moved-gateway.invalid/v1"}},
    )

    assert move_response.status_code == 200, move_response.text

    async with db_container() as container:
        session = container.session()
        moved_model = await session.scalar(
            select(CompletionModels).where(
                CompletionModels.id == model_ids[moved_provider_id]
            )
        )
        untouched_model = await session.scalar(
            select(CompletionModels).where(
                CompletionModels.id == model_ids[untouched_provider_id]
            )
        )
        assert moved_model is not None and untouched_model is not None
        assert moved_model.supports_strict_tool_schema is False
        assert untouched_model.supports_strict_tool_schema is True


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
