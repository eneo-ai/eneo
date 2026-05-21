"""Unit tests for AuthService._create_v2_legacy_record_for_user.

The v2 mirror written when a v1 user key is created must record the owner's
current trust level (ADMIN if the owner has Permission.ADMIN, else WRITE) so
that the runtime gate in user_service._resolve_api_key treats admin and
non-admin owners consistently with api_key_resolver._migrate_legacy_key.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.auth_models import (
    ApiKeyCreated,
    ApiKeyPermission,
    ApiKeyScopeType,
)
from intric.authentication.auth_service import AuthService


def _build_auth_service(*, has_admin: bool, tenant_id) -> AuthService:
    """Build an AuthService whose session returns has_admin for the role query
    and tenant_id for the tenant lookup. Order-sensitive: tenant query runs first."""
    api_key_repo = AsyncMock()
    api_key_v2_repo = AsyncMock()

    class _TenantRow:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

    class _TenantResult:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

    api_key_repo.session.execute = AsyncMock(
        return_value=_TenantResult(_TenantRow(tenant_id))
    )
    api_key_repo.session.scalar = AsyncMock(return_value=1 if has_admin else None)

    return AuthService(api_key_repo=api_key_repo, api_key_v2_repo=api_key_v2_repo)


@pytest.mark.asyncio
async def test_legacy_v2_mirror_uses_admin_when_owner_is_admin():
    tenant_id = uuid4()
    user_id = uuid4()
    svc = _build_auth_service(has_admin=True, tenant_id=tenant_id)

    api_key = ApiKeyCreated(
        key="inp_secret",
        hashed_key="hashed",
        truncated_key="cret",
    )

    await svc._create_v2_legacy_record_for_user(
        api_key=api_key, prefix="inp", user_id=user_id
    )

    create_kwargs = svc.api_key_v2_repo.create.await_args.kwargs
    assert create_kwargs["permission"] == ApiKeyPermission.ADMIN.value
    assert create_kwargs["scope_type"] == ApiKeyScopeType.TENANT.value
    assert create_kwargs["owner_user_id"] == user_id


@pytest.mark.asyncio
async def test_legacy_v2_mirror_uses_write_when_owner_is_not_admin():
    tenant_id = uuid4()
    user_id = uuid4()
    svc = _build_auth_service(has_admin=False, tenant_id=tenant_id)

    api_key = ApiKeyCreated(
        key="inp_secret",
        hashed_key="hashed",
        truncated_key="cret",
    )

    await svc._create_v2_legacy_record_for_user(
        api_key=api_key, prefix="inp", user_id=user_id
    )

    create_kwargs = svc.api_key_v2_repo.create.await_args.kwargs
    assert create_kwargs["permission"] == ApiKeyPermission.WRITE.value
    assert create_kwargs["scope_type"] == ApiKeyScopeType.TENANT.value
    assert create_kwargs["owner_user_id"] == user_id
