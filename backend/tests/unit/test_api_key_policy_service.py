from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.authentication.api_key_policy import ApiKeyPolicyService
from eneo.authentication.api_key_request_context import resolve_client_ip
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.roles.permissions import Permission


class DummySpaceService:
    pass


def _service(*, user: object | None = None) -> ApiKeyPolicyService:
    return ApiKeyPolicyService(
        space_service=DummySpaceService(),
        user=user,
    )


def _service_with_user(
    *, permissions: list[object] | None = None
) -> ApiKeyPolicyService:
    tenant = SimpleNamespace(api_key_policy={})
    user = SimpleNamespace(tenant=tenant, permissions=permissions or [])
    return _service(user=user)


_UNSET = object()


def _make_pk_key(*, tenant_id=None, allowed_origins=_UNSET):
    """Build a minimal pk_ key-like object for _validate_origin tests."""
    if allowed_origins is _UNSET:
        allowed_origins = ["http://localhost:3000"]
    return SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        allowed_origins=allowed_origins,
        allowed_ips=None,
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
        tenant_id=tenant_id or uuid4(),
    )


# ---------------------------------------------------------------------------
# _origin_matches: pattern matching (host, wildcard, scheme, port)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_origin_matches_single_label_wildcard():
    service = _service()

    assert service._origin_matches("https://app.example.com", "https://*.example.com")
    assert not service._origin_matches(
        "https://a.b.example.com", "https://*.example.com"
    )


@pytest.mark.asyncio
async def test_origin_matches_host_only_patterns():
    service = _service()

    assert service._origin_matches("https://example.com", "example.com")
    assert service._origin_matches("http://example.com:80", "example.com")
    assert not service._origin_matches("https://sub.example.com", "example.com")


@pytest.mark.asyncio
async def test_origin_matches_host_only_wildcard():
    service = _service()

    assert service._origin_matches("https://app.example.com", "*.example.com")
    assert service._origin_matches("http://app.example.com", "*.example.com")
    assert not service._origin_matches("https://a.b.example.com", "*.example.com")


@pytest.mark.asyncio
async def test_origin_matches_default_ports():
    service = _service()

    assert service._origin_matches("https://example.com:443", "https://example.com")
    assert service._origin_matches("http://example.com:80", "http://example.com")


@pytest.mark.asyncio
async def test_origin_matches_case_insensitive_scheme():
    service = _service()

    assert service._origin_matches("HTTPS://Example.Com", "https://example.com")


# ---------------------------------------------------------------------------
# Per-key allowed_origins: create + update validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_request_rejects_empty_allowed_origins_for_pk():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=[],
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "at least one allowed origin" in exc.value.message


@pytest.mark.asyncio
async def test_update_request_rejects_empty_allowed_origins_for_pk():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"allowed_origins": []},
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "at least one allowed origin" in exc.value.message


@pytest.mark.asyncio
async def test_update_request_rejects_null_allowed_origins_for_pk():
    """An explicit `allowed_origins: None` PATCH for a pk_ key would land a row
    that the fail-closed _validate_origin check then rejects on every request.
    Block it at the update boundary so the key never gets into that state."""
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"allowed_origins": None},
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "at least one allowed origin" in exc.value.message


@pytest.mark.asyncio
async def test_update_request_rejects_non_read_permission_for_pk():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )

    for perm in (ApiKeyPermission.WRITE, ApiKeyPermission.ADMIN):
        with pytest.raises(ApiKeyValidationError) as exc:
            await service.validate_update_request(
                key=key,
                updates={"permission": perm.value},
            )

        assert exc.value.status_code == 400
        assert exc.value.code == "invalid_request"
        assert "can only have read permission" in exc.value.message


@pytest.mark.asyncio
async def test_create_pk_defaults_to_safe_public_resource_permissions():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["http://localhost:3000"],
    )

    await service.validate_create_request(request=request)

    assert request.resource_permissions == ResourcePermissions(
        assistants=ResourcePermissionLevel.READ,
        apps=ResourcePermissionLevel.READ,
    )


@pytest.mark.asyncio
async def test_create_pk_assistant_scope_does_not_default_resource_permissions(
    monkeypatch,
):
    service = _service_with_user(permissions=[Permission.ADMIN])

    async def allow_creator_authorized(*, scope_type, scope_id):
        return None

    monkeypatch.setattr(
        service,
        "ensure_creator_authorized",
        allow_creator_authorized,
    )

    request = ApiKeyCreateRequest(
        name="Public assistant key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        allowed_origins=["http://localhost:3000"],
    )

    await service.validate_create_request(request=request)

    assert request.resource_permissions is None


@pytest.mark.asyncio
async def test_create_pk_assistant_scope_allows_scoped_resource_permissions(
    monkeypatch,
):
    service = _service_with_user(permissions=[Permission.ADMIN])

    async def allow_creator_authorized(*, scope_type, scope_id):
        return None

    monkeypatch.setattr(
        service,
        "ensure_creator_authorized",
        allow_creator_authorized,
    )

    request = ApiKeyCreateRequest(
        name="Public assistant key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(
            assistants=ResourcePermissionLevel.READ
        ),
    )

    await service.validate_create_request(request=request)

    assert request.resource_permissions == ResourcePermissions(
        assistants=ResourcePermissionLevel.READ
    )


@pytest.mark.asyncio
async def test_create_pk_assistant_scope_rejects_unreachable_resource_permissions():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public assistant key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "assistant-scoped keys do not support" in exc.value.message
    assert "apps" in exc.value.message


@pytest.mark.asyncio
async def test_create_pk_assistant_scope_rejects_missing_assistant_permission():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public assistant key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(files=ResourcePermissionLevel.READ),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "require 'assistants' resource permission" in exc.value.message


@pytest.mark.asyncio
async def test_create_pk_rejects_write_resource_permissions():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(files=ResourcePermissionLevel.WRITE),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "pk_ keys only support" in exc.value.message


@pytest.mark.asyncio
async def test_create_pk_rejects_jobs_resource_permission():
    """jobs is on the pk_ denylist regardless of level — even read is too much."""
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(jobs=ResourcePermissionLevel.READ),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "jobs" in exc.value.message


@pytest.mark.asyncio
async def test_create_pk_rejects_prompts_resource_permission():
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["http://localhost:3000"],
        resource_permissions=ResourcePermissions(prompts=ResourcePermissionLevel.READ),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "prompts" in exc.value.message


@pytest.mark.asyncio
async def test_update_pk_rejects_jobs_resource_permission():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        scope_type=ApiKeyScopeType.TENANT.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"resource_permissions": {"jobs": "read"}},
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "jobs" in exc.value.message


@pytest.mark.asyncio
async def test_update_pk_null_resource_permissions_normalizes_to_public_default():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        scope_type=ApiKeyScopeType.TENANT.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )
    updates = {"resource_permissions": None}

    await service.validate_update_request(key=key, updates=updates)  # type: ignore[arg-type]

    assert updates["resource_permissions"] == {
        "assistants": "read",
        "apps": "read",
        "spaces": "none",
        "knowledge": "none",
        "conversations": "none",
        "files": "none",
        "jobs": "none",
        "prompts": "none",
    }


@pytest.mark.asyncio
async def test_update_pk_assistant_scope_allows_scoped_resource_permissions():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        scope_type=ApiKeyScopeType.ASSISTANT.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )
    updates = {"resource_permissions": {"assistants": "read", "files": "read"}}

    await service.validate_update_request(key=key, updates=updates)

    assert updates["resource_permissions"] == {
        "assistants": "read",
        "apps": "none",
        "spaces": "none",
        "knowledge": "none",
        "conversations": "none",
        "files": "read",
        "jobs": "none",
        "prompts": "none",
    }


@pytest.mark.asyncio
async def test_update_sk_app_scope_rejects_unreachable_resource_permissions():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.SK.value,
        scope_type=ApiKeyScopeType.APP.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.WRITE.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"resource_permissions": {"apps": "read", "conversations": "read"}},
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "app-scoped keys do not support" in exc.value.message
    assert "conversations" in exc.value.message


@pytest.mark.asyncio
async def test_update_sk_app_scope_rejects_missing_app_permission():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.SK.value,
        scope_type=ApiKeyScopeType.APP.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.WRITE.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"resource_permissions": {"apps": "none", "files": "read"}},
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "require 'apps' resource permission" in exc.value.message


@pytest.mark.asyncio
async def test_update_pk_assistant_scope_allows_clearing_resource_permissions():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        scope_type=ApiKeyScopeType.ASSISTANT.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions={"assistants": "read"},
    )
    updates = {"resource_permissions": None}

    await service.validate_update_request(key=key, updates=updates)  # type: ignore[arg-type]

    assert updates["resource_permissions"] is None


# ---------------------------------------------------------------------------
# Origin format validation (sanity check on per-key entries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rejects_origin_without_scheme():
    """Bare hostnames (no scheme) are rejected with a clear 400."""
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["example.com"],
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "scheme" in exc.value.message


@pytest.mark.asyncio
async def test_create_rejects_origin_with_non_http_scheme():
    """Schemes other than http/https are rejected."""
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["ftp://example.com"],
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_create_accepts_https_origin_without_consulting_tenant_allowlist():
    """No central allowlist gate — any well-formed origin the user lists is accepted."""
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["https://mrp.sundsvall.dev", "http://localhost:5173"],
    )

    # Should NOT raise — well-formed origins, no tenant allowlist consulted.
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_update_rejects_origin_without_scheme():
    service = _service()
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        tenant_id=uuid4(),
        permission=ApiKeyPermission.READ.value,
        resource_permissions=None,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_update_request(
            key=key,
            updates={"allowed_origins": ["bare-hostname"]},
        )
    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_create_accepts_port_wildcard():
    """``http://localhost:*`` is a valid pattern for dev iteration."""
    service = _service_with_user(permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Public key",
        key_type=ApiKeyType.PK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=["http://localhost:*", "https://*.example.com:*"],
    )

    # Should NOT raise — wildcards in port and subdomain are accepted.
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_pk_port_wildcard_matches_any_port_at_request_time():
    """Pattern ``http://localhost:*`` permits any port on localhost."""
    service = _service()
    key = _make_pk_key(allowed_origins=["http://localhost:*"])

    await service._validate_origin(key=key, origin="http://localhost:5173")
    await service._validate_origin(key=key, origin="http://localhost:6006")

    # Different host → still rejected.
    with pytest.raises(ApiKeyValidationError):
        await service._validate_origin(key=key, origin="http://evil.local:5173")


# ---------------------------------------------------------------------------
# _validate_origin: request-time check against per-key allowed_origins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pk_key_missing_origin_header_rejected():
    """pk_ key with NO Origin header → 403 origin_not_allowed."""
    service = _service()
    key = _make_pk_key(allowed_origins=["https://example.com"])

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_origin(key=key, origin=None)

    assert exc.value.status_code == 403
    assert exc.value.code == "origin_not_allowed"


@pytest.mark.asyncio
async def test_pk_origin_matched_against_per_key_list():
    """Origin in the key's allowed_origins → permitted."""
    service = _service()
    key = _make_pk_key(allowed_origins=["https://app.example.com"])

    await service._validate_origin(key=key, origin="https://app.example.com")


@pytest.mark.asyncio
async def test_pk_origin_not_in_per_key_list_rejected():
    """Origin not in the key's allowed_origins → 403."""
    service = _service()
    key = _make_pk_key(allowed_origins=["https://app.example.com"])

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_origin(key=key, origin="https://evil.example")

    assert exc.value.status_code == 403
    assert exc.value.code == "origin_not_allowed"


@pytest.mark.asyncio
async def test_pk_localhost_permitted_when_listed_on_key():
    """No env-flag bypass — localhost works iff the key explicitly lists it."""
    service = _service()
    key = _make_pk_key(allowed_origins=["http://localhost:5173"])

    await service._validate_origin(key=key, origin="http://localhost:5173")


@pytest.mark.asyncio
async def test_pk_localhost_rejected_when_not_listed_on_key():
    """localhost is not magic — if the key didn't list it, it's denied."""
    service = _service()
    key = _make_pk_key(allowed_origins=["https://app.example.com"])

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_origin(key=key, origin="http://localhost:5173")
    assert exc.value.code == "origin_not_allowed"


@pytest.mark.asyncio
async def test_pk_empty_allowed_origins_blocks_all():
    """An empty list is treated as 'block everything'."""
    service = _service()
    key = _make_pk_key(allowed_origins=[])

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_origin(key=key, origin="https://app.example.com")
    assert exc.value.code == "origin_not_allowed"


@pytest.mark.asyncio
async def test_pk_null_allowed_origins_blocks_all():
    """A pk_ key without an allowed_origins list (NULL) is misconfigured —
    earlier behaviour was to silently permit every origin, which let any
    legacy row missing the column bypass CORS-style origin enforcement.
    Fail closed: NULL and empty list both return origin_not_allowed."""
    service = _service()
    key = _make_pk_key(allowed_origins=None)

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_origin(key=key, origin="https://anything.example")
    assert exc.value.code == "origin_not_allowed"


# ---------------------------------------------------------------------------
# IP allowlist (sk_ keys)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ip_allowlist_allows_matching_ip():
    service = _service()
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    service._validate_ip(key=key, client_ip="10.0.0.5")


@pytest.mark.asyncio
async def test_ip_allowlist_rejects_non_matching_ip():
    service = _service()
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError):
        service._validate_ip(key=key, client_ip="192.168.1.10")


@pytest.mark.asyncio
async def test_ip_allowlist_requires_client_ip():
    service = _service()
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError):
        service._validate_ip(key=key, client_ip=None)


@pytest.mark.asyncio
async def test_ip_allowlist_rejects_malformed_client_ip():
    service = _service()
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError) as exc:
        service._validate_ip(key=key, client_ip="not-an-ip")
    assert exc.value.code == "ip_not_allowed"


@pytest.mark.asyncio
async def test_ip_allowlist_none_skips_check():
    """Key with allowed_ips=None → IP check is skipped entirely."""
    service = _service()
    key = SimpleNamespace(allowed_ips=None)
    # Should NOT raise — no IP restriction
    service._validate_ip(key=key, client_ip="anything")


@pytest.mark.asyncio
async def test_ip_allowlist_empty_list_rejects_all():
    """Key with allowed_ips=[] → rejects all IPs (no entries match)."""
    service = _service()
    key = SimpleNamespace(allowed_ips=[])
    with pytest.raises(ApiKeyValidationError) as exc:
        service._validate_ip(key=key, client_ip="10.0.0.1")
    assert exc.value.code == "ip_not_allowed"


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_zero_rejected():
    service = _service_with_user()

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(0)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_max_rate_limit_override_blocks_unlimited_rate_limit():
    """max_rate_limit_override blocks rate_limit=-1 on create/update."""
    service = _service_with_user()
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 100}

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(-1)

    assert exc.value.status_code == 400
    assert "not allowed" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_max_rate_limit_override_blocks_exceeding_value():
    """max_rate_limit_override blocks rate_limit exceeding the cap."""
    service = _service_with_user()
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 100}

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(200)

    assert exc.value.status_code == 400
    assert "exceeds" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_rate_limit_negative_one_is_unlimited_without_cap_requires_admin():
    """rate_limit=-1 (unlimited) without cap → requires admin permission."""
    # Non-admin user → rejected
    service = _service_with_user(permissions=[])
    service.user.tenant.api_key_policy = {}
    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(-1)
    assert exc.value.code == "insufficient_permission"

    # Admin user → allowed
    admin_service = _service_with_user(permissions=[Permission.ADMIN])
    admin_service.user.tenant.api_key_policy = {}
    await admin_service._validate_rate_limit(-1)


@pytest.mark.asyncio
async def test_rate_limit_positive_value_always_valid():
    """Positive rate_limit is always valid regardless of cap."""
    service = _service_with_user()
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 1000}
    await service._validate_rate_limit(500)


@pytest.mark.asyncio
async def test_rate_limit_at_cap_boundary_valid():
    """rate_limit exactly at the cap boundary → valid."""
    service = _service_with_user()
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 100}
    await service._validate_rate_limit(100)


# ---------------------------------------------------------------------------
# Reverse-proxy IP resolution
# ---------------------------------------------------------------------------


def test_reverse_proxy_ip_resolution_extracts_leftmost_untrusted():
    """X-Forwarded-For with trusted_proxy_count=1 extracts the leftmost untrusted hop."""
    request = SimpleNamespace(
        headers={
            "x-forwarded-for": "203.0.113.50, 10.0.0.1",
        },
        client=SimpleNamespace(host="10.0.0.1"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=1,
        trusted_proxy_headers=[],
    )
    assert ip == "203.0.113.50"


def test_reverse_proxy_ip_resolution_with_multiple_proxies():
    """X-Forwarded-For with trusted_proxy_count=2 skips 2 rightmost hops."""
    request = SimpleNamespace(
        headers={
            "x-forwarded-for": "203.0.113.50, 10.0.0.2, 10.0.0.1",
        },
        client=SimpleNamespace(host="10.0.0.1"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=2,
        trusted_proxy_headers=[],
    )
    assert ip == "203.0.113.50"


def test_reverse_proxy_ip_resolution_falls_back_to_client_host():
    """No X-Forwarded-For + trusted_proxy_count=0 → uses request.client.host."""
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="192.168.1.1"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=0,
        trusted_proxy_headers=[],
    )
    assert ip == "192.168.1.1"


def test_resolve_client_ip_returns_none_for_non_ip_client_host():
    """A non-IP request.client.host (e.g. Starlette TestClient's "testclient")
    must not propagate downstream — audit INET column would crash and IP
    allow-list parsing would silently fail."""
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="testclient"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=0,
        trusted_proxy_headers=[],
    )
    assert ip is None


def test_resolve_client_ip_returns_none_for_non_ip_in_forwarded_for():
    """A proxy that injects garbage in X-Forwarded-For must not bypass
    validation — extracted hop is validated before being returned."""
    request = SimpleNamespace(
        headers={"x-forwarded-for": "not-an-ip, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=1,
        trusted_proxy_headers=[],
    )
    assert ip is None


def test_resolve_client_ip_accepts_ipv6():
    """IPv6 addresses pass validation."""
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="2001:db8::1"),
    )

    ip = resolve_client_ip(
        request,
        trusted_proxy_count=0,
        trusted_proxy_headers=[],
    )
    assert ip == "2001:db8::1"
