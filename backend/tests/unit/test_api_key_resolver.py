from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.api_key_resolver import (
    ApiKeyAuthResolver,
    ApiKeyValidationError,
)
from sqlalchemy.exc import IntegrityError

from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)


@dataclass
class _Row:
    tenant_id: object
    id: object
    user_id: object


class _Result:
    def __init__(self, row: _Row):
        self._row = row

    def first(self):
        return self._row


def _make_v2_key(**overrides: object) -> ApiKeyV2InDB:
    base = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Resolver Key",
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
        "created_at": None,
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


@pytest.fixture()
def resolver():
    api_key_repo = AsyncMock()
    legacy_repo = AsyncMock()
    legacy_repo.session = AsyncMock()
    audit_service = AsyncMock()
    return ApiKeyAuthResolver(
        api_key_repo=api_key_repo,
        legacy_repo=legacy_repo,
        audit_service=audit_service,
    )


@pytest.mark.asyncio
async def test_resolve_rejects_missing_api_key(resolver: ApiKeyAuthResolver):
    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("")
    assert exc.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_prefix(resolver: ApiKeyAuthResolver):
    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("invalid-prefix")
    assert exc.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_resolve_returns_v2_hmac_match(resolver: ApiKeyAuthResolver):
    key = _make_v2_key(key_prefix=ApiKeyType.SK.value, key_type=ApiKeyType.SK)
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)

    resolved = await resolver.resolve("sk_abc123")

    assert resolved.key.id == key.id
    assert resolved.prefix == ApiKeyType.SK.value


@pytest.mark.asyncio
async def test_resolve_passes_expected_tenant_to_lookup(resolver: ApiKeyAuthResolver):
    tenant_id = uuid4()
    key = _make_v2_key(
        key_prefix=ApiKeyType.SK.value,
        key_type=ApiKeyType.SK,
        tenant_id=tenant_id,
    )
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)

    await resolver.resolve("sk_abc123", expected_tenant_id=tenant_id)

    assert resolver.api_key_repo.get_by_hash.await_count == 1
    first_call = resolver.api_key_repo.get_by_hash.await_args_list[0]
    assert first_call.kwargs["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_resolve_rejects_v2_key_outside_expected_tenant(
    resolver: ApiKeyAuthResolver,
):
    resolver.api_key_repo.get_by_hash = AsyncMock(
        return_value=_make_v2_key(tenant_id=uuid4())
    )
    resolver.legacy_repo.get = AsyncMock(return_value=None)

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_abc123", expected_tenant_id=uuid4())

    assert exc.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_resolve_migrates_sha_record_to_hmac(resolver: ApiKeyAuthResolver):
    key = _make_v2_key(
        hash_version=ApiKeyHashVersion.SHA256.value,
        key_prefix=ApiKeyType.SK.value,
        key_type=ApiKeyType.SK,
    )
    resolver.api_key_repo.get_by_hash = AsyncMock(side_effect=[None, key])
    resolver.api_key_repo.update = AsyncMock()
    resolver.api_key_repo.get = AsyncMock(return_value=key)

    resolved = await resolver.resolve("sk_abc123")

    assert resolved.key.id == key.id
    resolver.api_key_repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_falls_back_to_legacy_and_migrates(resolver: ApiKeyAuthResolver):
    key = _make_v2_key(key_prefix="inp_", key_type=ApiKeyType.SK)
    resolver.api_key_repo.get_by_hash = AsyncMock(side_effect=[None, None])
    resolver.legacy_repo.get = AsyncMock(
        return_value=SimpleNamespace(user_id=uuid4(), assistant_id=None)
    )
    resolver._migrate_legacy_key = AsyncMock(return_value=key)

    resolved = await resolver.resolve("inp_legacy")

    assert resolved.key.id == key.id
    resolver._migrate_legacy_key.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_raises_for_unknown_key(resolver: ApiKeyAuthResolver):
    resolver.api_key_repo.get_by_hash = AsyncMock(side_effect=[None, None])
    resolver.legacy_repo.get = AsyncMock(return_value=None)

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_unknown")

    assert exc.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_legacy_migration_logs_audit_event(resolver: ApiKeyAuthResolver):
    tenant_id = uuid4()
    owner_user_id = uuid4()
    key = _make_v2_key(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        key_prefix="inp_",
        key_type=ApiKeyType.SK,
        hash_version=ApiKeyHashVersion.SHA256.value,
    )
    resolver.api_key_repo.create = AsyncMock(return_value=key)
    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_Result(
            _Row(tenant_id=tenant_id, id=owner_user_id, user_id=owner_user_id)
        )
    )

    await resolver._migrate_legacy_key(
        plain_key="inp_legacy",
        legacy_record=SimpleNamespace(user_id=owner_user_id, assistant_id=None),
        prefix="inp_",
    )

    resolver.audit_service.log_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Concurrent migration race tests (Phase 7M)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_migration_handles_integrity_error_with_sha256_fallback(
    resolver: ApiKeyAuthResolver,
):
    """IntegrityError during migration → falls back to SHA256 get_by_hash."""
    tenant_id = uuid4()
    owner_user_id = uuid4()
    existing_key = _make_v2_key(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        key_prefix="inp_",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.ADMIN,
    )

    resolver.api_key_repo.create = AsyncMock(
        side_effect=IntegrityError("duplicate", {}, None),
    )
    # SHA256 fallback finds the concurrent record
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=existing_key)

    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_Result(
            _Row(tenant_id=tenant_id, id=owner_user_id, user_id=owner_user_id)
        )
    )

    migrated = await resolver._migrate_legacy_key(
        plain_key="inp_concurrent",
        legacy_record=SimpleNamespace(user_id=owner_user_id, assistant_id=None),
        prefix="inp_",
    )

    assert migrated.id == existing_key.id
    assert migrated.permission == ApiKeyPermission.ADMIN


@pytest.mark.asyncio
async def test_legacy_migration_handles_integrity_error_with_hmac_fallback(
    resolver: ApiKeyAuthResolver,
):
    """IntegrityError + SHA256 returns None → tries HMAC_SHA256 fallback."""
    tenant_id = uuid4()
    owner_user_id = uuid4()
    existing_key = _make_v2_key(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        key_prefix="inp_",
        key_type=ApiKeyType.SK,
        hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
    )

    resolver.api_key_repo.create = AsyncMock(
        side_effect=IntegrityError("duplicate", {}, None),
    )
    # SHA256 miss, HMAC hit
    resolver.api_key_repo.get_by_hash = AsyncMock(
        side_effect=[None, existing_key],
    )

    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_Result(
            _Row(tenant_id=tenant_id, id=owner_user_id, user_id=owner_user_id)
        )
    )

    migrated = await resolver._migrate_legacy_key(
        plain_key="inp_concurrent",
        legacy_record=SimpleNamespace(user_id=owner_user_id, assistant_id=None),
        prefix="inp_",
    )

    assert migrated.id == existing_key.id
    # Verify it tried both hash lookups
    assert resolver.api_key_repo.get_by_hash.await_count == 2


@pytest.mark.asyncio
async def test_legacy_migration_integrity_error_both_fallbacks_fail(
    resolver: ApiKeyAuthResolver,
):
    """IntegrityError + both fallbacks return None → raises 500."""
    tenant_id = uuid4()
    owner_user_id = uuid4()

    resolver.api_key_repo.create = AsyncMock(
        side_effect=IntegrityError("duplicate", {}, None),
    )
    # Both fallbacks miss
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=None)

    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_Result(
            _Row(tenant_id=tenant_id, id=owner_user_id, user_id=owner_user_id)
        )
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver._migrate_legacy_key(
            plain_key="inp_orphan",
            legacy_record=SimpleNamespace(user_id=owner_user_id, assistant_id=None),
            prefix="inp_",
        )

    assert exc.value.status_code == 500
    assert exc.value.code == "migration_error"


# ---------------------------------------------------------------------------
# Legacy migration permission tests (Phase 7M)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_key_migration_creates_admin_permission(
    resolver: ApiKeyAuthResolver,
):
    """User key (user_id set) → migrates with ADMIN permission."""
    tenant_id = uuid4()
    owner_user_id = uuid4()
    key = _make_v2_key(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        key_prefix="inp_",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.ADMIN,
    )
    resolver.api_key_repo.create = AsyncMock(return_value=key)
    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_Result(
            _Row(tenant_id=tenant_id, id=owner_user_id, user_id=owner_user_id)
        )
    )

    await resolver._migrate_legacy_key(
        plain_key="inp_user_key",
        legacy_record=SimpleNamespace(user_id=owner_user_id, assistant_id=None),
        prefix="inp_",
    )

    # Verify create was called with ADMIN permission
    create_kwargs = resolver.api_key_repo.create.await_args.kwargs
    assert create_kwargs["permission"] == ApiKeyPermission.ADMIN.value


@pytest.mark.asyncio
async def test_assistant_key_migration_creates_read_permission(
    resolver: ApiKeyAuthResolver,
):
    """Assistant key (assistant_id set) → migrates with READ permission."""
    tenant_id = uuid4()
    owner_user_id = uuid4()
    assistant_id = uuid4()
    key = _make_v2_key(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        key_prefix="ina_",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
    )
    resolver.api_key_repo.create = AsyncMock(return_value=key)

    # _get_assistant_context query
    @dataclass
    class _AssistantRow:
        user_id: object
        space_id: object
        tenant_id: object

    class _AssistantResult:
        def first(self):
            return _AssistantRow(
                user_id=owner_user_id,
                space_id=uuid4(),
                tenant_id=tenant_id,
            )

    resolver.legacy_repo.session.execute = AsyncMock(
        return_value=_AssistantResult()
    )

    await resolver._migrate_legacy_key(
        plain_key="ina_assistant_key",
        legacy_record=SimpleNamespace(user_id=None, assistant_id=assistant_id),
        prefix="ina_",
    )

    create_kwargs = resolver.api_key_repo.create.await_args.kwargs
    assert create_kwargs["permission"] == ApiKeyPermission.READ.value
    assert create_kwargs["scope_type"] == ApiKeyScopeType.ASSISTANT.value
