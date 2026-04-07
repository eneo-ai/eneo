from types import SimpleNamespace
from uuid import uuid4

from intric.users import user_router


class AllowedOriginRepoStub:
    def __init__(self, origins_by_tenant):
        self._origins_by_tenant = origins_by_tenant

    async def get_by_tenant(self, tenant_id):
        origins = self._origins_by_tenant.get(tenant_id, [])
        return [SimpleNamespace(url=origin) for origin in origins]


async def test_resolve_single_tenant_redirect_uri_uses_allowed_request_origin():
    tenant_id = uuid4()
    container = SimpleNamespace(
        allowed_origin_repo=lambda: AllowedOriginRepoStub(
            {tenant_id: ["https://external.example.com"]}
        )
    )
    settings = SimpleNamespace(oidc_tenant_id=str(tenant_id))

    resolved = await user_router._resolve_single_tenant_redirect_uri(
        container=container,
        settings=settings,
        redirect_uri="https://canonical.example.com/login/callback",
        request_origin="https://external.example.com",
        correlation_id="corr-allowed-origin",
    )

    assert resolved == "https://external.example.com/login/callback"


async def test_resolve_single_tenant_redirect_uri_rejects_non_allowed_origin():
    tenant_id = uuid4()
    container = SimpleNamespace(
        allowed_origin_repo=lambda: AllowedOriginRepoStub(
            {tenant_id: ["https://external.example.com"]}
        )
    )
    settings = SimpleNamespace(oidc_tenant_id=str(tenant_id))

    resolved = await user_router._resolve_single_tenant_redirect_uri(
        container=container,
        settings=settings,
        redirect_uri="https://canonical.example.com/login/callback",
        request_origin="https://unknown.example.com",
        correlation_id="corr-not-allowed",
    )

    assert resolved == "https://canonical.example.com/login/callback"


async def test_resolve_single_tenant_redirect_uri_requires_tenant_id_for_override():
    container = SimpleNamespace(
        allowed_origin_repo=lambda: AllowedOriginRepoStub(
            {uuid4(): ["https://external.example.com"]}
        )
    )
    settings = SimpleNamespace(oidc_tenant_id=None)

    resolved = await user_router._resolve_single_tenant_redirect_uri(
        container=container,
        settings=settings,
        redirect_uri="https://canonical.example.com/login/callback",
        request_origin="https://external.example.com",
        correlation_id="corr-no-tenant-id",
    )

    assert resolved == "https://canonical.example.com/login/callback"
