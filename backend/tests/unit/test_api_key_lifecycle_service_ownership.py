from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.api_key_lifecycle import ApiKeyLifecycleService
from eneo.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
)
from tests.unit.api_key_test_utils import make_api_key


def _make_key(**overrides: object):
    return make_api_key(
        default_permission=ApiKeyPermission.WRITE,
        **overrides,
    )


@pytest.fixture()
def user():
    return SimpleNamespace(id=uuid4(), email="user@example.com", tenant_id=uuid4())


@pytest.mark.asyncio
async def test_create_service_key_sets_null_owner(user):
    """When ownership=SERVICE, repo.create should receive owner_user_id=None."""
    key = _make_key(tenant_id=user.tenant_id, owner_user_id=None)
    repo = AsyncMock()
    repo.create.return_value = key
    policy = SimpleNamespace(validate_create_request=AsyncMock(return_value=None))
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    request = ApiKeyCreateRequest(
        name="Service Key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        ownership=ApiKeyOwnership.SERVICE,
    )

    await service.create_key(request)

    repo.create.assert_awaited_once()
    assert repo.create.call_args.kwargs["owner_user_id"] is None


@pytest.mark.asyncio
async def test_create_user_key_sets_owner(user):
    """When ownership=USER (default), repo.create should receive owner_user_id=user.id."""
    key = _make_key(tenant_id=user.tenant_id, owner_user_id=user.id)
    repo = AsyncMock()
    repo.create.return_value = key
    policy = SimpleNamespace(validate_create_request=AsyncMock(return_value=None))
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    request = ApiKeyCreateRequest(
        name="User Key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        ownership=ApiKeyOwnership.USER,
    )

    await service.create_key(request)

    repo.create.assert_awaited_once()
    assert repo.create.call_args.kwargs["owner_user_id"] == user.id
