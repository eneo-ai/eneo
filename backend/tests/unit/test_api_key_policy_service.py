import pytest
from uuid import uuid4
from types import SimpleNamespace

from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_request_context import resolve_client_ip
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyType


class DummyOrigin:
    def __init__(self, url: str):
        self.url = url


class DummyOriginRepo:
    def __init__(self, patterns: list[str]):
        self.patterns = patterns
        self.calls = 0

    async def get_by_tenant(self, tenant_id):
        self.calls += 1
        return [DummyOrigin(url) for url in self.patterns]


class DummySpaceService:
    pass


def _service_with_user(patterns: list[str], *, permissions: list[object] | None = None):
    tenant = SimpleNamespace(api_key_policy={})
    user = SimpleNamespace(tenant=tenant, permissions=permissions or [])
    return ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(patterns),
        space_service=DummySpaceService(),
        user=user,
    )


@pytest.mark.asyncio
async def test_origin_matches_single_label_wildcard():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )

    assert service._origin_matches("https://app.example.com", "https://*.example.com")
    assert not service._origin_matches(
        "https://a.b.example.com", "https://*.example.com"
    )


@pytest.mark.asyncio
async def test_origin_matches_host_only_patterns():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )

    assert service._origin_matches("https://example.com", "example.com")
    assert service._origin_matches("http://example.com:80", "example.com")
    assert not service._origin_matches("https://sub.example.com", "example.com")


@pytest.mark.asyncio
async def test_origin_matches_host_only_wildcard():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )

    assert service._origin_matches("https://app.example.com", "*.example.com")
    assert service._origin_matches("http://app.example.com", "*.example.com")
    assert not service._origin_matches("https://a.b.example.com", "*.example.com")


@pytest.mark.asyncio
async def test_origin_matches_default_ports():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )

    assert service._origin_matches("https://example.com:443", "https://example.com")
    assert service._origin_matches("http://example.com:80", "http://example.com")


@pytest.mark.asyncio
async def test_allowed_origins_subset_with_tenant_wildcard():
    tenant_id = uuid4()
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["https://*.example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )

    await service.validate_allowed_origins_subset(
        allowed_origins=["https://app.example.com"], tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_allowed_origins_subset_rejects_unlisted_wildcard():
    tenant_id = uuid4()
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["https://app.example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )

    with pytest.raises(ApiKeyValidationError):
        await service.validate_allowed_origins_subset(
            allowed_origins=["https://*.example.com"], tenant_id=tenant_id
        )


@pytest.mark.asyncio
async def test_allowed_origins_subset_with_host_only_tenant_entry():
    tenant_id = uuid4()
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )

    await service.validate_allowed_origins_subset(
        allowed_origins=["https://example.com"], tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_allowed_origins_subset_accepts_host_only_wildcard():
    tenant_id = uuid4()
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["*.example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )

    await service.validate_allowed_origins_subset(
        allowed_origins=["https://*.example.com"], tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_allowed_origins_subset_allows_empty_list():
    tenant_id = uuid4()
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["https://example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )

    await service.validate_allowed_origins_subset(
        allowed_origins=[], tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_ip_allowlist_allows_matching_ip():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    service._validate_ip(key=key, client_ip="10.0.0.5")


@pytest.mark.asyncio
async def test_ip_allowlist_rejects_non_matching_ip():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError):
        service._validate_ip(key=key, client_ip="192.168.1.10")


@pytest.mark.asyncio
async def test_ip_allowlist_requires_client_ip():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError):
        service._validate_ip(key=key, client_ip=None)


@pytest.mark.asyncio
async def test_ip_allowlist_rejects_malformed_client_ip():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )
    key = SimpleNamespace(allowed_ips=["10.0.0.0/24"])

    with pytest.raises(ApiKeyValidationError) as exc:
        service._validate_ip(key=key, client_ip="not-an-ip")
    assert exc.value.code == "ip_not_allowed"


@pytest.mark.asyncio
async def test_localhost_origin_supports_ipv6_loopback():
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo([]),
        space_service=DummySpaceService(),
        user=None,
    )

    assert service._is_localhost_origin("http://[::1]:5173")


@pytest.mark.asyncio
async def test_rate_limit_zero_rejected():
    service = _service_with_user([])

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(0)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_tenant_origin_cache_reuses_patterns_within_ttl():
    tenant_id = uuid4()
    repo = DummyOriginRepo(["https://example.com"])
    service = ApiKeyPolicyService(
        allowed_origin_repo=repo,
        space_service=DummySpaceService(),
        user=None,
    )
    service._tenant_origin_cache_ttl_seconds = 60

    await service.validate_allowed_origins_subset(
        allowed_origins=["https://example.com"], tenant_id=tenant_id
    )
    await service.validate_allowed_origins_subset(
        allowed_origins=["https://example.com"], tenant_id=tenant_id
    )

    assert repo.calls == 1


@pytest.mark.asyncio
async def test_tenant_origin_cache_invalidate_forces_reload():
    tenant_id = uuid4()
    repo = DummyOriginRepo(["https://example.com"])
    service = ApiKeyPolicyService(
        allowed_origin_repo=repo,
        space_service=DummySpaceService(),
        user=None,
    )
    service._tenant_origin_cache_ttl_seconds = 60

    await service.validate_allowed_origins_subset(
        allowed_origins=["https://example.com"], tenant_id=tenant_id
    )
    service.invalidate_tenant_origin_cache(tenant_id)
    await service.validate_allowed_origins_subset(
        allowed_origins=["https://example.com"], tenant_id=tenant_id
    )

    assert repo.calls == 2


@pytest.mark.asyncio
async def test_pk_key_missing_origin_header_rejected():
    """pk_ key with NO Origin header → 403 origin_not_allowed."""
    service = ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(["https://example.com"]),
        space_service=DummySpaceService(),
        user=None,
    )
    key = SimpleNamespace(
        key_type=ApiKeyType.PK.value,
        allowed_origins=["https://example.com"],
        allowed_ips=None,
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
        tenant_id=uuid4(),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.enforce_guardrails(key=key, origin=None, client_ip=None)

    assert exc.value.status_code == 403
    assert exc.value.code == "origin_not_allowed"


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


@pytest.mark.asyncio
async def test_max_rate_limit_override_blocks_unlimited_rate_limit():
    """max_rate_limit_override blocks rate_limit=-1 on create/update."""
    service = _service_with_user([])
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 100}

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(-1)

    assert exc.value.status_code == 400
    assert "not allowed" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_max_rate_limit_override_blocks_exceeding_value():
    """max_rate_limit_override blocks rate_limit exceeding the cap."""
    service = _service_with_user([])
    service.user.tenant.api_key_policy = {"max_rate_limit_override": 100}

    with pytest.raises(ApiKeyValidationError) as exc:
        await service._validate_rate_limit(200)

    assert exc.value.status_code == 400
    assert "exceeds" in exc.value.message.lower()


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
