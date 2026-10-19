"""Admin configuration of an OAuth server: what the auth config may hold,
when auth_scope applies, and how a save is validated when the admin has not
connected yet."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException, MCPUserActionRequiredError
from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import OAUTH_AUTH_TYPE, MCPServer
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
)


def _service(token_provider=None, oauth_repo=None):
    user = MagicMock()
    user.tenant_id = uuid4()
    user.permissions = ["admin"]
    repo = MagicMock()
    repo.add = AsyncMock(side_effect=lambda server: server)
    tool_repo = MagicMock()
    tool_repo.by_server = AsyncMock(return_value=[])
    tool_repo.stage_observed = AsyncMock(return_value=[])
    tool_repo.add_many = AsyncMock(return_value=[])
    service = MCPServerService(
        mcp_server_repo=repo,
        mcp_server_tool_repo=tool_repo,
        user=user,
        oauth_token_provider=token_provider,
        mcp_oauth_repo=oauth_repo,
    )
    return service, repo


class TestAuthConfig:
    def test_accepts_client_and_scope_keys_only(self):
        MCPServerService._validate_auth_config(
            OAUTH_AUTH_TYPE,
            {"client_id": "pre", "client_secret": "s3cret", "scope": "mcp:read"},
        )
        MCPServerService._validate_auth_config(OAUTH_AUTH_TYPE, None)
        with pytest.raises(BadRequestException, match="unexpected"):
            MCPServerService._validate_auth_config(OAUTH_AUTH_TYPE, {"token": "x"})

    def test_a_secret_needs_a_client_id(self):
        with pytest.raises(BadRequestException, match="requires a client_id"):
            MCPServerService._validate_auth_config(
                OAUTH_AUTH_TYPE, {"client_secret": "s3cret"}
            )

    def test_values_must_be_clean_strings(self):
        with pytest.raises(BadRequestException, match="non-empty"):
            MCPServerService._validate_auth_config(OAUTH_AUTH_TYPE, {"client_id": " "})
        with pytest.raises(BadRequestException, match="control"):
            MCPServerService._validate_auth_config(
                OAUTH_AUTH_TYPE, {"client_id": "a\r\nb"}
            )


class TestAuthScope:
    def test_only_known_scopes(self):
        with pytest.raises(BadRequestException, match="auth_scope must be"):
            MCPServerService._validate_auth_scope(OAUTH_AUTH_TYPE, "tenant")

    def test_shared_applies_to_oauth_servers_only(self):
        MCPServerService._validate_auth_scope(OAUTH_AUTH_TYPE, "shared")
        MCPServerService._validate_auth_scope("bearer", "per_user")
        with pytest.raises(BadRequestException, match="only to OAuth"):
            MCPServerService._validate_auth_scope("bearer", "shared")


class TestSavingWithoutAConnection:
    async def test_discovery_stands_in_for_the_connection_test(self, monkeypatch):
        vendor = FakeAuthorizationServer()
        vendor.install(monkeypatch)
        service, repo = _service()

        result = await service.create_mcp_server(
            name="Vendor",
            http_url=vendor.server_url,
            http_auth_type=OAUTH_AUTH_TYPE,
            auth_scope="shared",
            http_auth_config_schema={"client_id": "pre", "client_secret": "s3cret"},
        )

        assert result.connection.success
        assert result.connection.tools_discovered == 0
        saved: MCPServer = repo.add.await_args.args[0]
        assert saved.auth_scope == "shared"
        # The secret is encrypted at rest when an encryption service exists;
        # without one it is stored as given, like other auth types.
        assert saved.http_auth_config_schema is not None
        assert saved.http_auth_config_schema["client_id"] == "pre"

    async def test_a_server_that_is_not_oauth_protected_is_refused(self, monkeypatch):
        vendor = FakeAuthorizationServer(serve_prm=False, prm_in_challenge=False)
        vendor.install(monkeypatch)
        # No PRM and no AS metadata at the origin: discovery cannot complete.
        asm_free = vendor.handle

        def no_metadata(request):
            if request.url.path.startswith("/.well-known/"):
                import httpx

                return httpx.Response(404)
            return asm_free(request)

        import httpx

        from eneo.mcp_servers.infrastructure.oauth import discovery

        monkeypatch.setattr(
            discovery,
            "_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(no_metadata)),
        )
        service, repo = _service()

        result = await service.create_mcp_server(
            name="Vendor", http_url=vendor.server_url, http_auth_type=OAUTH_AUTH_TYPE
        )

        assert not result.connection.success
        assert "No authorization server metadata" in (
            result.connection.error_message or ""
        )
        repo.add.assert_not_awaited()

    async def test_a_new_address_forgets_the_old_connections(self, monkeypatch):
        vendor = FakeAuthorizationServer()
        vendor.install(monkeypatch)
        from tests.unit.mcp_servers.application.test_mcp_oauth_token_provider import (
            FakeOAuthRepo,
        )

        oauth_repo = FakeOAuthRepo()
        service, repo = _service(oauth_repo=oauth_repo)
        server = MCPServer(
            id=uuid4(),
            tenant_id=service.user.tenant_id,
            name="Vendor",
            http_url="https://old-vendor.example/mcp",
            http_auth_type=OAUTH_AUTH_TYPE,
        )
        repo.one = AsyncMock(return_value=server)
        repo.update = AsyncMock(side_effect=lambda s: s)
        oauth_repo.connections[(server.id, uuid4())] = MagicMock()
        oauth_repo.registrations[(server.id, "https://old-vendor.example")] = (
            MagicMock()
        )

        result = await service.update_mcp_server(server.id, http_url=vendor.server_url)

        # The update reports a connection only when its test failed.
        assert result.connection is None or result.connection.success
        assert oauth_repo.connections == {}
        assert oauth_repo.registrations == {}

    async def test_tool_sync_names_the_remedy_when_the_admin_is_not_connected(
        self, monkeypatch
    ):
        vendor = FakeAuthorizationServer()
        vendor.install(monkeypatch)
        server = MCPServer(
            id=uuid4(),
            tenant_id=uuid4(),
            name="Vendor",
            http_url=vendor.server_url,
            http_auth_type=OAUTH_AUTH_TYPE,
        )

        class Provider:
            async def auth_for(self, s):
                raise MCPUserActionRequiredError(
                    "connect",
                    mcp_server_id=s.id,
                    server_name=s.name,
                    auth_scope=s.auth_scope,
                    reason="not_connected",
                )

        service, _ = _service(token_provider=Provider())
        service.user.tenant_id = server.tenant_id

        result = await service.discover_and_sync_tools(server)

        assert not result.connection.success
        assert (result.connection.error_message or "").startswith(
            "mcp_authorization_required:"
        )
