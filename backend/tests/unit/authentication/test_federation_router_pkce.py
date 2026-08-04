"""PKCE (RFC 7636) behavior of the OIDC federation flow.

The verifier is generated server-side at initiate and stored only in the
Redis state cache; the S256 challenge rides the authorize URL. When the
cache write fails, no challenge is sent (an IdP that never saw a
challenge must not receive a verifier either).
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from eneo.authentication import federation_router
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant import TenantInDB, TenantState


class DummySettings(SimpleNamespace):
    def __init__(self, **overrides):
        defaults = {
            "jwt_secret": "unit-test-secret-padded-to-the-hs256-minimum",
            "oidc_state_ttl_seconds": 600,
            "oidc_redirect_grace_period_seconds": 900,
            "strict_oidc_redirect_validation": True,
            "tenant_credentials_enabled": False,
            "federation_enabled": True,
            "public_origin": "https://global.example.com",
            "openai_api_key": None,
            "anthropic_api_key": None,
            "azure_api_key": None,
            "mistral_api_key": None,
            "ovhcloud_api_key": None,
            "vllm_api_key": None,
            "oidc_discovery_endpoint": None,
            "oidc_client_secret": None,
            "oidc_client_id": None,
            "oidc_tenant_id": None,
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:  # noqa: ARG002
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class BrokenRedis(FakeRedis):
    async def setex(self, key: str, ttl: int, value: str) -> None:
        raise ConnectionError("redis down")


class TenantRepoStub:
    def __init__(self, tenant: TenantInDB):
        self._tenant = tenant

    async def get_by_slug(self, slug: str) -> TenantInDB | None:
        return self._tenant if self._tenant.slug == slug else None


class MockContainer:
    def __init__(self, *, tenant_repo, redis_client):
        self._tenant_repo = tenant_repo
        self._redis_client = redis_client

    def tenant_repo(self):
        return self._tenant_repo

    def encryption_service(self):
        return EncryptionService(None)

    def redis_client(self):
        return self._redis_client


def _tenant() -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name="PkceTenant",
        display_name="PkceTenant",
        quota_limit=1024**3,
        slug="pkce-tenant",
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "provider": "generic",
            "client_id": "client",
            "client_secret": "secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "discovery_endpoint": (
                "https://idp.example.com/.well-known/openid-configuration"
            ),
            "canonical_public_origin": "https://canonical.example.com",
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def test_initiate_sends_s256_challenge_and_caches_verifier(monkeypatch):
    monkeypatch.setattr(federation_router, "get_settings", lambda: DummySettings())
    redis = FakeRedis()
    container = MockContainer(tenant_repo=TenantRepoStub(_tenant()), redis_client=redis)

    response = await federation_router.initiate_auth(
        tenant="pkce-tenant",
        state=None,
        redirect_uri_param=None,
        container=container,
    )

    query = parse_qs(urlparse(response.authorization_url).query)
    assert query["code_challenge_method"] == ["S256"]
    challenge = query["code_challenge"][0]
    assert len(challenge) == 43  # unpadded base64url of a SHA-256 digest

    cached = [json.loads(v) for v in redis.store.values()]
    assert len(cached) == 1
    verifier = cached[0]["code_verifier"]
    # The verifier never appears in the front channel.
    assert verifier not in response.authorization_url

    import base64
    import hashlib

    recomputed = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert recomputed == challenge


async def test_initiate_omits_challenge_when_state_cache_unavailable(monkeypatch):
    """A challenge without a retrievable verifier would make the later token
    exchange fail unconditionally; degrade to a non-PKCE request instead."""
    monkeypatch.setattr(federation_router, "get_settings", lambda: DummySettings())
    container = MockContainer(
        tenant_repo=TenantRepoStub(_tenant()), redis_client=BrokenRedis()
    )

    response = await federation_router.initiate_auth(
        tenant="pkce-tenant",
        state=None,
        redirect_uri_param=None,
        container=container,
    )

    query = parse_qs(urlparse(response.authorization_url).query)
    assert "code_challenge" not in query
    assert "code_challenge_method" not in query
