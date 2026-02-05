import pytest
from uuid import uuid4
from types import SimpleNamespace

from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError


class DummyOrigin:
    def __init__(self, url: str):
        self.url = url


class DummyOriginRepo:
    def __init__(self, patterns: list[str]):
        self.patterns = patterns

    async def get_by_tenant(self, tenant_id):
        return [DummyOrigin(url) for url in self.patterns]


class DummySpaceService:
    pass


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
