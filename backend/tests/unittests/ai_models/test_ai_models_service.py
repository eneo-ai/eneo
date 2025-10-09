from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.ai_models.ai_models_service import AIModelsService
from intric.ai_models.completion_models.completion_model import CompletionModelFamily
from intric.main.config import get_settings
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB
from intric.user_groups.user_group import UserGroupInDB
from intric.users.user import UserInDB
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
    assert CompletionModelFamily.AZURE not in [model.family for model in models]


async def test_azure_models_with_feature_flag_on(service: AIModelsService):
    get_settings().using_azure_models = True
    service.completion_model_repo.get_models.return_value = [
        TEST_MODEL_GPT4,
        TEST_MODEL_CHATGPT,
        TEST_MODEL_AZURE,
    ]

    models = await service.get_completion_models()

    assert len(models) == 3
    assert CompletionModelFamily.AZURE in [model.family for model in models]
