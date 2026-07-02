from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.ai_models.ai_models_service import AIModelsService
from eneo.main.config import get_settings
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.user_groups.user_group import UserGroupInDB
from eneo.users.user import UserInDB
from tests.fixtures import (
    TEST_EMBEDDING_MODEL,
    TEST_EMBEDDING_MODEL_ADA,
    TEST_MODEL_AZURE,
    TEST_MODEL_CHATGPT,
    TEST_MODEL_GPT4,
    TEST_TENANT,
)

TEST_ADMIN_ROLE = RoleInDB(
    id=uuid4(),
    name="God",
    permissions=[Permission.ADMIN],
    tenant_id=TEST_TENANT.id,
)

TEST_NO_ADMIN_ROLE = RoleInDB(
    id=uuid4(),
    name="God",
    permissions=[],
    tenant_id=TEST_TENANT.id,
)

TEST_ADMIN_USER = UserInDB(
    id=uuid4(),
    username="test_user",
    email="test@user.com",
    salt="test_salt",
    password="test_pass",
    used_tokens=0,
    tenant_id=TEST_TENANT.id,
    quota_limit=20000,
    tenant=TEST_TENANT,
    user_groups=[],
    roles=[TEST_ADMIN_ROLE],
    state="active",
)
TEST_NO_ADMIN_USER = UserInDB(
    id=uuid4(),
    username="test_user_2",
    email="test_2@user.com",
    salt="test_salt",
    password="test_pass",
    used_tokens=0,
    tenant_id=TEST_TENANT.id,
    quota_limit=20000,
    tenant=TEST_TENANT,
    user_groups=[],
    roles=[TEST_NO_ADMIN_ROLE],
    state="active",
)
TEST_USER_GROUP = UserGroupInDB(id=uuid4(), name="test name", tenant_id=TEST_TENANT.id)


@pytest.fixture(name="service")
def service_with_mocks():
    return AIModelsService(
        user=TEST_ADMIN_USER,
        embedding_model_repo=AsyncMock(),
        completion_model_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
    )


async def test_user_can_not_access_embedding_models(service: AIModelsService):
    service.user = TEST_NO_ADMIN_USER

    service.embedding_model_repo.get_models.return_value = [
        TEST_EMBEDDING_MODEL,
        TEST_EMBEDDING_MODEL_ADA,
    ]

    models = await service.get_embedding_models()

    for model in models:
        assert not model.can_access


async def test_user_can_not_access_completion_models(service: AIModelsService):
    service.user = TEST_NO_ADMIN_USER

    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_CHATGPT,
        TEST_MODEL_GPT4,
    ]

    models = await service.get_completion_models()

    for model in models:
        assert not model.can_access


async def test_completion_models_keep_litellm_deprecation_advisory(
    service: AIModelsService,
):
    service.user = TEST_ADMIN_USER
    model = TEST_MODEL_CHATGPT.model_copy(
        update={
            "name": "gpt-4-0613",
            "is_org_enabled": True,
            "is_deprecated": False,
            "provider_type": "openai",
        }
    )
    service.completion_model_repo.get_models.return_value = [model]

    with patch(
        "litellm.model_cost",
        {"openai/gpt-4-0613": {"deprecation_date": "2025-06-13"}},
    ):
        models = await service.get_completion_models()

    assert models[0].is_deprecated is False
    assert models[0].can_access is True


async def test_embedding_models_keep_litellm_deprecation_advisory(
    service: AIModelsService,
):
    service.user = TEST_ADMIN_USER
    model = TEST_EMBEDDING_MODEL.model_copy(
        update={
            "name": "text-embedding-ada-002",
            "is_org_enabled": True,
            "is_deprecated": False,
        }
    )
    service.embedding_model_repo.get_models.return_value = [model]

    with patch(
        "litellm.model_cost",
        {"text-embedding-ada-002": {"deprecation_date": "2025-06-13"}},
    ):
        models = await service.get_embedding_models()

    assert models[0].is_deprecated is False
    assert models[0].can_access is True


async def test_completion_models_flags_settings_not_exists(service: AIModelsService):
    service.user = TEST_NO_ADMIN_USER

    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_GPT4,
        TEST_MODEL_CHATGPT,
    ]

    models = await service.get_completion_models()

    for model in models:
        if model.id == TEST_MODEL_GPT4.id:
            assert not model.is_org_enabled


async def test_embedding_models_flags_settings_not_exists(service: AIModelsService):
    service.user = TEST_NO_ADMIN_USER
    service.user.user_groups = [TEST_USER_GROUP]

    service.embedding_model_repo.get_models.return_value = [
        TEST_EMBEDDING_MODEL,
        TEST_EMBEDDING_MODEL_ADA,
    ]

    models = await service.get_embedding_models()

    for model in models:
        if model.id == TEST_MODEL_GPT4.id:
            assert not model.is_org_enabled


async def test_azure_models_with_feature_flag_off(service: AIModelsService):
    get_settings().using_azure_models = False
    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_GPT4,
        TEST_MODEL_CHATGPT,
        TEST_MODEL_AZURE,
    ]

    models = await service.get_completion_models()

    assert len(models) == 2
    assert "azure" not in [model.family for model in models]


async def test_azure_models_with_feature_flag_on(service: AIModelsService):
    get_settings().using_azure_models = True
    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_GPT4,
        TEST_MODEL_CHATGPT,
        TEST_MODEL_AZURE,
    ]

    models = await service.get_completion_models()

    assert len(models) == 3
    assert "azure" in [model.family for model in models]


async def test_tenant_azure_models_shown_when_flag_off(service: AIModelsService):
    # A tenant that explicitly configures an Azure provider gets family="azure"
    # on its completion models. Those are deliberate config and must stay
    # visible even when the global `using_azure_models` flag (which only gates
    # the predefined global Azure models) is off. Regression for Azure
    # completion models 200-ing on create yet never appearing in the admin
    # list / chat picker.
    get_settings().using_azure_models = False
    tenant_azure = TEST_MODEL_AZURE.model_copy(update={"tenant_id": TEST_TENANT.id})
    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_GPT4,
        TEST_MODEL_AZURE,  # global → hidden
        tenant_azure,  # tenant-owned → shown
    ]

    models = await service.get_completion_models()

    families = [model.family for model in models]
    assert families.count("azure") == 1
    assert any(model.tenant_id == TEST_TENANT.id for model in models)


def test_get_latest_available_model_handles_missing_created_at(
    service: AIModelsService,
):
    latest = service._get_latest_available_model(
        [
            TEST_MODEL_CHATGPT.model_copy(
                update={"created_at": None, "can_access": True}
            ),
            TEST_MODEL_GPT4.model_copy(
                update={
                    "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "can_access": True,
                }
            ),
        ]
    )

    assert latest is not None
    assert latest.id == TEST_MODEL_GPT4.id
