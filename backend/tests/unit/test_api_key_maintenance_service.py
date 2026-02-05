from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.api_key_maintenance import ApiKeyMaintenanceService
from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateReasonCode,
    ApiKeyType,
    ApiKeyV2InDB,
)


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    base = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": ApiKeyPermission.WRITE,
        "scope_type": ApiKeyScopeType.TENANT,
        "scope_id": None,
        "allowed_origins": None,
        "allowed_ips": None,
        "state": ApiKeyState.ACTIVE,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "revoked_reason_code": None,
        "revoked_reason_text": None,
        "suspended_at": None,
        "suspended_reason_code": None,
        "suspended_reason_text": None,
        "rotation_grace_until": None,
        "rate_limit": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
        "rotated_from_key_id": None,
        "tenant_id": uuid4(),
        "owner_user_id": uuid4(),
        "created_by_user_id": None,
        "created_by_key_id": None,
        "delegation_depth": 0,
        "key_hash": "hash",
        "hash_version": ApiKeyHashVersion.HMAC_SHA256.value,
    }
    base.update(overrides)
    return ApiKeyV2InDB(**base)


@pytest.mark.asyncio
async def test_run_daily_maintenance_expires_due_keys():
    key = _make_key(expires_at=datetime.now(timezone.utc))
    repo = AsyncMock()
    repo.list_expired_candidates.return_value = [key]
    repo.list_rotation_grace_candidates.return_value = []
    repo.list_unused_before.return_value = []
    repo.update.return_value = key

    tenant_repo = AsyncMock()
    tenant_repo.get_all_tenants.return_value = []
    audit = AsyncMock()

    service = ApiKeyMaintenanceService(repo, tenant_repo, audit)
    result = await service.run_daily_maintenance()

    assert result["expired"] == 1
    assert result["auto_expired"] == 0
    assert result["rotation_revoked"] == 0
    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_EXPIRED


@pytest.mark.asyncio
async def test_auto_expire_unused_keys_uses_tenant_policy():
    key = _make_key()
    repo = AsyncMock()
    repo.list_expired_candidates.return_value = []
    repo.list_rotation_grace_candidates.return_value = []
    repo.list_unused_before.return_value = [key]
    repo.update.return_value = key

    tenant = SimpleNamespace(id=uuid4(), api_key_policy={"auto_expire_unused_days": 7})
    tenant_repo = AsyncMock()
    tenant_repo.get_all_tenants.return_value = [tenant]
    audit = AsyncMock()

    service = ApiKeyMaintenanceService(repo, tenant_repo, audit)
    result = await service.run_daily_maintenance()

    assert result["auto_expired"] == 1
    assert repo.list_unused_before.call_args.kwargs["tenant_id"] == tenant.id
    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_EXPIRED


@pytest.mark.asyncio
async def test_rotation_grace_revocation_sets_reason():
    key = _make_key(rotation_grace_until=datetime.now(timezone.utc))
    repo = AsyncMock()
    repo.list_expired_candidates.return_value = []
    repo.list_rotation_grace_candidates.return_value = [key]
    repo.list_unused_before.return_value = []
    repo.update.return_value = key

    tenant_repo = AsyncMock()
    tenant_repo.get_all_tenants.return_value = []
    audit = AsyncMock()

    service = ApiKeyMaintenanceService(repo, tenant_repo, audit)
    result = await service.run_daily_maintenance()

    assert result["rotation_revoked"] == 1
    assert any(
        call.kwargs.get("revoked_reason_code")
        == ApiKeyStateReasonCode.ROTATION_COMPLETED.value
        for call in repo.update.call_args_list
    )
