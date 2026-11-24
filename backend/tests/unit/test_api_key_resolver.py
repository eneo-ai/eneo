from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.api_key_resolver import (
    ApiKeyAuthResolver,
    ApiKeyValidationError,
)
from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    ServicePrincipalInDB,
    ServicePrincipalState,
)


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
    return ApiKeyAuthResolver(api_key_repo=api_key_repo)


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
@pytest.mark.parametrize("prefix", ["inp_", "ina_"])
async def test_resolve_accepts_migrated_legacy_prefixes(
    resolver: ApiKeyAuthResolver, prefix: str
):
    """Keys migrated from v1 keep their inp_/ina_ prefixes in api_keys_v2
    and must keep resolving through the v2 path."""
    key = _make_v2_key(key_prefix=prefix, key_type=ApiKeyType.SK)
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)

    resolved = await resolver.resolve(f"{prefix}migrated123")

    assert resolved.key.id == key.id
    assert resolved.prefix == prefix


@pytest.mark.asyncio
async def test_resolve_raises_for_unknown_key(resolver: ApiKeyAuthResolver):
    resolver.api_key_repo.get_by_hash = AsyncMock(side_effect=[None, None])

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_unknown")

    assert exc.value.code == "invalid_api_key"


@pytest.mark.asyncio
async def test_resolve_has_no_legacy_table_fallback(resolver: ApiKeyAuthResolver):
    """A v1-prefixed key with no api_keys_v2 record is rejected outright —
    the legacy api_keys table lookup is gone."""
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=None)

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("inp_never_migrated")

    assert exc.value.code == "invalid_api_key"


def _service_key(**overrides: object) -> ApiKeyV2InDB:
    return _make_v2_key(
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        **{"service_principal_id": uuid4(), **overrides},
    )


def _principal(key: ApiKeyV2InDB, *, state: ServicePrincipalState):
    return ServicePrincipalInDB(
        id=key.service_principal_id,
        tenant_id=key.tenant_id,
        display_name=key.name,
        scope_type=key.scope_type,
        state=state,
    )


async def test_resolve_returns_a_service_key_whose_principal_is_active(
    resolver: ApiKeyAuthResolver,
):
    key = _service_key()
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)
    resolver.api_key_repo.get_service_principal = AsyncMock(
        return_value=_principal(key, state=ServicePrincipalState.ACTIVE)
    )

    resolved = await resolver.resolve("sk_abc123")

    assert resolved.key.id == key.id
    resolver.api_key_repo.get_service_principal.assert_awaited_once_with(
        service_principal_id=key.service_principal_id,
        tenant_id=key.tenant_id,
    )


async def test_resolve_refuses_a_service_key_whose_principal_is_disabled(
    resolver: ApiKeyAuthResolver,
):
    key = _service_key()
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)
    resolver.api_key_repo.get_service_principal = AsyncMock(
        return_value=_principal(key, state=ServicePrincipalState.DISABLED)
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_abc123")

    assert exc.value.status_code == 403
    assert exc.value.code == "service_principal_disabled"


async def test_resolve_rejects_a_service_key_whose_principal_is_not_in_its_tenant(
    resolver: ApiKeyAuthResolver,
):
    key = _service_key()
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)
    resolver.api_key_repo.get_service_principal = AsyncMock(return_value=None)

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_abc123")

    assert exc.value.status_code == 401
    assert exc.value.code == "invalid_api_key"


async def test_resolve_rejects_a_service_key_without_a_principal(
    resolver: ApiKeyAuthResolver,
):
    key = _service_key(service_principal_id=None)
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)
    resolver.api_key_repo.get_service_principal = AsyncMock()

    with pytest.raises(ApiKeyValidationError) as exc:
        await resolver.resolve("sk_abc123")

    assert exc.value.status_code == 401
    assert exc.value.code == "invalid_api_key"
    resolver.api_key_repo.get_service_principal.assert_not_awaited()


async def test_resolve_does_not_look_up_a_principal_for_a_user_key(
    resolver: ApiKeyAuthResolver,
):
    key = _make_v2_key()
    resolver.api_key_repo.get_by_hash = AsyncMock(return_value=key)
    resolver.api_key_repo.get_service_principal = AsyncMock()

    await resolver.resolve("sk_abc123")

    resolver.api_key_repo.get_service_principal.assert_not_awaited()
