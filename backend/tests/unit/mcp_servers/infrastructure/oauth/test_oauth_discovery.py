"""Authorization server discovery follows the MCP spec: the challenge's
resource_metadata hint first, then the well-known locations; the metadata
must describe this server and name the issuer it was fetched for."""

import pytest

from eneo.mcp_servers.infrastructure.oauth import discovery
from eneo.mcp_servers.infrastructure.oauth.discovery import (
    OAuthDiscoveryError,
    discover,
)
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
)


async def test_discovers_through_the_challenge_hint(monkeypatch):
    vendor = FakeAuthorizationServer(challenge_scope="mcp:read")
    vendor.install(monkeypatch)

    found = await discover(vendor.server_url)

    assert found.issuer == vendor.issuer
    assert found.resource == vendor.resource
    assert found.token_endpoint == f"{vendor.base}/oauth2/token"
    assert found.supports_cimd and found.supports_dcr
    assert not found.supports_id_jag and not found.supports_client_credentials
    # The challenge's scope wins over scopes_supported.
    assert found.default_scope() == "mcp:read"
    paths = [r.url.path for r in vendor.requests]
    assert paths[:3] == [
        "/mcp",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
    ]


async def test_falls_back_to_well_known_locations_without_a_hint(monkeypatch):
    vendor = FakeAuthorizationServer(prm_in_challenge=False)
    vendor.install(monkeypatch)

    found = await discover(vendor.server_url)

    assert found.issuer == vendor.issuer
    # No challenge scope: the PRM's scopes_supported is the default.
    assert found.default_scope() == "mcp:read mcp:write"


async def test_reports_extension_support_from_metadata(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=True, client_credentials=True, cimd=False)
    vendor.install(monkeypatch)

    found = await discover(vendor.server_url)

    assert found.supports_id_jag
    assert found.supports_client_credentials
    assert not found.supports_cimd


async def test_rejects_metadata_for_another_issuer(monkeypatch):
    vendor = FakeAuthorizationServer()
    asm = vendor._asm()
    asm["issuer"] = "https://attacker.example"
    monkeypatch.setattr(vendor, "_asm", lambda: asm)
    vendor.install(monkeypatch)

    with pytest.raises(OAuthDiscoveryError, match="issuer mismatch"):
        await discover(vendor.server_url)


async def test_rejects_resource_metadata_for_another_server(monkeypatch):
    vendor = FakeAuthorizationServer()
    prm = vendor._prm()
    prm["resource"] = "https://other.example/mcp"
    monkeypatch.setattr(vendor, "_prm", lambda: prm)
    vendor.install(monkeypatch)

    with pytest.raises(OAuthDiscoveryError, match="describes"):
        await discover(vendor.server_url)


async def test_a_server_that_does_not_challenge_is_not_oauth(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.issued = 1  # pretend the probe's (empty) bearer is accepted

    def accept_everything(request):
        if request.url.path == "/mcp":
            import httpx

            return httpx.Response(200, json={})
        return vendor.handle(request)

    import httpx

    monkeypatch.setattr(
        discovery,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(accept_everything)),
    )
    discovery.reset_discovery_cache()

    with pytest.raises(OAuthDiscoveryError, match="did not ask for authorization"):
        await discover(vendor.server_url)


async def test_the_issuer_is_kept_exactly_as_published(monkeypatch):
    with_slash = FakeAuthorizationServer(issuer="https://vendor.example/")
    with_slash.install(monkeypatch)
    assert (await discover(with_slash.server_url)).issuer == "https://vendor.example/"

    bare = FakeAuthorizationServer()
    bare.install(monkeypatch)
    assert (await discover(bare.server_url)).issuer == "https://vendor.example"
    assert (await discover(bare.server_url)).resource == "https://vendor.example/mcp"


async def test_discovery_is_cached_per_server(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)

    await discover(vendor.server_url)
    count = len(vendor.requests)
    await discover(vendor.server_url)

    assert len(vendor.requests) == count
    await discover(vendor.server_url, force=True)
    assert len(vendor.requests) > count
