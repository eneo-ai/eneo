"""Tokens for OAuth-protected MCP servers at request time.

One provider serves one acting principal (the user of a completion, or an
administrator syncing tools) for the servers of one request. For each OAuth
server it decides which strategy applies, hands the proxy an httpx auth
carrying a fresh access token, and records what the server said when the
token was refused.

Strategy per server:

* ``shared`` with a client secret configured and ``client_credentials``
  advertised: the OAuth Client Credentials extension, a machine identity.
* ``shared`` otherwise: the connection an administrator made, logged in at
  the vendor as a service account.
* ``per_user`` when the authorization server advertises the id-jag grant
  profile and the tenant enabled it: Enterprise-Managed Authorization, the
  user's login ID token exchanged silently.
* ``per_user`` otherwise: the user's own authorization-code connection.

Refreshes run under a Redis lock per connection so parallel tool calls from
several workers never spend the same rotating refresh token twice.

The provider works while a turn streams, after the request's own transaction
has ended, so in production it opens a short session of its own for every
database access (``repo_factory``), like the tool-catalog staging does. Tests
hand it a repository directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import httpx
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

from eneo.authentication.auth_models import is_service_api_key
from eneo.main.exceptions import MCPUserActionRequiredError
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    STRATEGY_CLIENT_CREDENTIALS,
    STRATEGY_ID_JAG,
    MCPOAuthConnection,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
)
from eneo.mcp_servers.infrastructure.oauth import client_metadata
from eneo.mcp_servers.infrastructure.oauth.bearer_auth import MCPOAuthBearerAuth
from eneo.mcp_servers.infrastructure.oauth.discovery import (
    OAuthDiscoveryError,
    OAuthServerDiscovery,
    discover,
)
from eneo.mcp_servers.infrastructure.oauth.token_client import (
    ClientCredential,
    OAuthTokenError,
    TokenResponse,
    choose_client_auth_method,
    client_credentials_grant,
    redeem_id_jag,
    refresh_access_token,
    request_id_jag,
)

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from eneo.main.config import Settings
    from eneo.mcp_servers.domain.entities.mcp_oauth_connection import IdpUserToken
    from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import (
        MCPOAuthRepository,
    )
    from eneo.settings.encryption_service import EncryptionService
    from eneo.tenants.tenant import TenantInDB
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

RepoFactory = Callable[[], AbstractAsyncContextManager["MCPOAuthRepository"]]

REFRESH_LOCK_TTL_SECONDS = 30
REFRESH_LOCK_WAIT_SECONDS = 5.0
REFRESH_LOCK_POLL_SECONDS = 0.25
# A tenant opts into the Enterprise-Managed Authorization strategy here.
ID_JAG_FEDERATION_FLAG = "id_jag_enabled"


class MCPOAuthTokenProvider:
    def __init__(
        self,
        *,
        repo: Optional[MCPOAuthRepository] = None,
        repo_factory: Optional[RepoFactory] = None,
        encryption_service: EncryptionService,
        settings: Settings,
        user: Optional[UserInDB],
        tenant: Optional[TenantInDB] = None,
        redis_client: Optional[aioredis.Redis] = None,
    ) -> None:
        if repo is None and repo_factory is None:
            raise ValueError("MCPOAuthTokenProvider needs a repo or a repo_factory")
        self._static_repo = repo
        self._repo_factory = repo_factory
        self._encryption = encryption_service
        self._settings = settings
        self._user = user
        self._tenant = tenant if tenant is not None else getattr(user, "tenant", None)
        self._redis = redis_client
        self._connections: dict[tuple[UUID, Optional[UUID]], MCPOAuthConnection] = {}
        self._auths: dict[UUID, MCPOAuthBearerAuth] = {}
        # Serialises database work: the proxy connects servers from one task,
        # but identity-scoped discovery probes several in parallel.
        self._db_lock = asyncio.Lock()

    @asynccontextmanager
    async def _repo(self) -> AsyncGenerator[MCPOAuthRepository]:
        """The repository for one database access, serialised.

        With a factory each access gets its own short session and transaction,
        so the provider never depends on the request's transaction, which has
        ended by the time a streaming turn calls a tool.
        """
        async with self._db_lock:
            if self._repo_factory is not None:
                async with self._repo_factory() as repo:
                    yield repo
            else:
                assert self._static_repo is not None
                yield self._static_repo

    # -- public ---------------------------------------------------------------

    @property
    def user_id(self) -> Optional[UUID]:
        """The acting user, or None for a service key or a worker."""
        if self._user is None or is_service_api_key(self._user):
            return None
        return self._user.id

    async def preload(self, servers: list[MCPServer]) -> None:
        """Load the connections one request may need in two queries."""
        oauth_servers = [server for server in servers if server.is_oauth]
        if not oauth_servers:
            return
        shared_ids = [s.id for s in oauth_servers if s.is_shared_oauth]
        user_ids = [s.id for s in oauth_servers if not s.is_shared_oauth]
        async with self._repo() as repo:
            if shared_ids:
                for connection in await repo.list_connections(
                    mcp_server_ids=shared_ids, user_id=None
                ):
                    self._connections[(connection.mcp_server_id, None)] = connection
            if user_ids and self.user_id is not None:
                for connection in await repo.list_connections(
                    mcp_server_ids=user_ids, user_id=self.user_id
                ):
                    self._connections[(connection.mcp_server_id, self.user_id)] = (
                        connection
                    )

    def forget(self, server: MCPServer) -> None:
        """Drop the cached connection: the user just authorized this server."""
        self._connections.pop(self._key(server), None)
        self._auths.pop(server.id, None)

    async def auth_for(self, server: MCPServer) -> MCPOAuthBearerAuth:
        """An httpx auth with a fresh token, or the error that explains why not."""
        token = await self.access_token_for(server)
        auth = MCPOAuthBearerAuth(token)
        self._auths[server.id] = auth
        return auth

    async def access_token_for(self, server: MCPServer) -> str:
        if server.is_shared_oauth:
            return await self._shared_token(server)
        return await self._user_token(server)

    async def record_denial(
        self, server: MCPServer, auth: Optional[httpx.Auth] = None
    ) -> Optional[MCPUserActionRequiredError]:
        """The server refused the token we sent: invalidate and explain.

        Returns the error to surface, or None when the auth saw no challenge
        (the failure was something else and the token stays).
        """
        if not isinstance(auth, MCPOAuthBearerAuth):
            auth = self._auths.get(server.id)
        if auth is None or auth.challenge is None:
            return None
        challenge = auth.challenge
        reason = (
            "insufficient_scope"
            if challenge.error == "insufficient_scope"
            else "token_rejected"
        )
        key = self._key(server)
        connection = self._connections.get(key)
        if connection is not None:
            connection.invalidate(reason)
            async with self._repo() as repo:
                await repo.save_connection(connection)
        scopes = challenge.scope.split() if challenge.scope else []
        return self.user_action_required(server, reason=reason, scopes=scopes)

    def user_action_required(
        self,
        server: MCPServer,
        *,
        reason: str,
        scopes: Optional[list[str]] = None,
    ) -> MCPUserActionRequiredError:
        if server.is_shared_oauth:
            message = (
                f"'{server.name}' needs an administrator to connect it before "
                "it can be used."
            )
            connect_url = None
        else:
            message = (
                f"The user has not authorized Eneo to use '{server.name}' yet; "
                "they must connect it in Eneo first."
            )
            connect_url = (
                client_metadata.connect_url(self._settings, server.id)
                if self.user_id is not None
                else None
            )
        return MCPUserActionRequiredError(
            message,
            mcp_server_id=server.id,
            server_name=server.name,
            auth_scope=server.auth_scope,
            scopes=scopes,
            connect_url=connect_url,
            reason=reason,
        )

    # -- strategies -----------------------------------------------------------

    def _key(self, server: MCPServer) -> tuple[UUID, Optional[UUID]]:
        return (server.id, None if server.is_shared_oauth else self.user_id)

    @staticmethod
    def _bound_to(connection: MCPOAuthConnection, server: MCPServer) -> bool:
        """Whether the tokens were issued for the server the row points at now.

        A token is bound to one resource (RFC 8707). When an administrator
        points the row at another address, the stored tokens must never be
        sent there; the connection reads as absent until someone authorizes
        the new resource.
        """
        try:
            return check_resource_allowed(
                requested_resource=resource_url_from_server_url(server.http_url),
                configured_resource=connection.resource,
            )
        except ValueError:
            return False

    async def _connection(self, server: MCPServer) -> Optional[MCPOAuthConnection]:
        key = self._key(server)
        if key in self._connections:
            connection: Optional[MCPOAuthConnection] = self._connections[key]
        else:
            async with self._repo() as repo:
                connection = await repo.get_connection(
                    mcp_server_id=server.id, user_id=key[1]
                )
            if connection is not None:
                self._connections[key] = connection
        if connection is not None and not self._bound_to(connection, server):
            logger.info(
                "Ignoring OAuth connection for '%s': bound to %s, server is now %s",
                server.name,
                connection.resource,
                server.http_url,
            )
            return None
        return connection

    async def _reload(
        self, connection: MCPOAuthConnection
    ) -> Optional[MCPOAuthConnection]:
        """The row as another worker may have left it meanwhile."""
        async with self._repo() as repo:
            latest = await repo.get_connection(
                mcp_server_id=connection.mcp_server_id, user_id=connection.user_id
            )
        if latest is not None:
            self._connections[(latest.mcp_server_id, latest.user_id)] = latest
        return latest

    async def _save(self, connection: MCPOAuthConnection) -> MCPOAuthConnection:
        async with self._repo() as repo:
            saved = await repo.save_connection(connection)
        self._connections[(saved.mcp_server_id, saved.user_id)] = saved
        return saved

    async def _shared_token(self, server: MCPServer) -> str:
        config = self._decrypted_config(server)
        connection = await self._connection(server)
        if config.get("client_id") and config.get("client_secret"):
            try:
                discovery = await discover(server.http_url)
            except OAuthDiscoveryError as exc:
                raise self.user_action_required(server, reason=str(exc)) from exc
            if discovery.supports_client_credentials:
                return await self._client_credentials_token(
                    server, connection, discovery, config
                )
        if connection is None or not connection.is_connected:
            raise self.user_action_required(
                server,
                reason=connection.last_error
                if connection is not None and connection.last_error
                else "not_connected",
            )
        return await self._fresh_token(server, connection)

    async def _client_credentials_token(
        self,
        server: MCPServer,
        connection: Optional[MCPOAuthConnection],
        discovery: OAuthServerDiscovery,
        config: dict[str, Any],
    ) -> str:
        if (
            connection is not None
            and connection.strategy == STRATEGY_CLIENT_CREDENTIALS
            and connection.token_is_fresh()
        ):
            assert connection.access_token is not None
            return connection.access_token
        credential = ClientCredential(
            client_id=str(config["client_id"]),
            client_secret=str(config["client_secret"]),
            auth_method=choose_client_auth_method(
                str(config["client_secret"]), discovery.token_endpoint_auth_methods
            ),
        )
        scope = self._scope_override(config) or discovery.default_scope()
        try:
            response = await client_credentials_grant(
                token_endpoint=discovery.token_endpoint,
                resource=discovery.resource,
                credential=credential,
                scope=scope,
            )
        except OAuthTokenError as exc:
            raise self.user_action_required(server, reason=str(exc)) from exc
        if connection is None:
            connection = MCPOAuthConnection(
                tenant_id=server.tenant_id,
                mcp_server_id=server.id,
                user_id=None,
                issuer=discovery.issuer,
                resource=discovery.resource,
                strategy=STRATEGY_CLIENT_CREDENTIALS,
            )
        connection.strategy = STRATEGY_CLIENT_CREDENTIALS
        connection.issuer = discovery.issuer
        connection.resource = discovery.resource
        self._apply(connection, response)
        connection = await self._save(connection)
        assert connection.access_token is not None
        return connection.access_token

    async def _user_token(self, server: MCPServer) -> str:
        if self.user_id is None:
            raise self.user_action_required(server, reason="no_user_identity")
        connection = await self._connection(server)
        if connection is not None and connection.token_is_fresh():
            assert connection.access_token is not None
            return connection.access_token

        # Silent path first: the extension, when both ends support it.
        idp_token = await self._idp_token_if_enabled()
        if idp_token is not None:
            try:
                discovery = await discover(server.http_url)
            except OAuthDiscoveryError:
                discovery = None
            if discovery is not None and discovery.supports_id_jag:
                token = await self._id_jag_token(
                    server, connection, discovery, idp_token
                )
                if token is not None:
                    return token

        if connection is None or not connection.is_connected:
            raise self.user_action_required(
                server,
                reason=connection.last_error
                if connection is not None and connection.last_error
                else "not_connected",
            )
        return await self._fresh_token(server, connection)

    async def _id_jag_token(
        self,
        server: MCPServer,
        connection: Optional[MCPOAuthConnection],
        discovery: OAuthServerDiscovery,
        idp_token: IdpUserToken,
    ) -> Optional[str]:
        """Exchange the login ID token; None means fall back to the popup."""
        tenant = self._tenant
        federation: dict[str, Any] = (
            dict(getattr(tenant, "federation_config", None) or {})
            if tenant is not None
            else {}
        )
        idp_token_endpoint = federation.get("token_endpoint")
        client_id = federation.get("client_id")
        if not isinstance(idp_token_endpoint, str) or not isinstance(client_id, str):
            return None
        client_secret = federation.get("client_secret")
        idp_credential = ClientCredential(
            client_id=client_id,
            client_secret=client_secret if isinstance(client_secret, str) else None,
            auth_method=choose_client_auth_method(
                client_secret if isinstance(client_secret, str) else None,
                ("client_secret_post",),
            ),
        )
        config = self._decrypted_config(server)
        as_client = await self._as_client_for(server, discovery, config)
        scope = self._scope_override(config) or discovery.default_scope()
        try:
            assertion = await request_id_jag(
                idp_token_endpoint=idp_token_endpoint,
                id_token=idp_token.id_token,
                authorization_server_issuer=discovery.issuer,
                resource=discovery.resource,
                credential=idp_credential,
                scope=scope,
            )
            response = await redeem_id_jag(
                token_endpoint=discovery.token_endpoint,
                assertion=assertion,
                resource=discovery.resource,
                credential=as_client,
                scope=scope,
            )
        except OAuthTokenError as exc:
            # The IdP's policy said no, or the AS did not accept the assertion:
            # the interactive flow is the spec's fallback.
            logger.info(
                "ID-JAG for '%s' not granted (%s); falling back to authorization code",
                server.name,
                exc,
            )
            return None
        if connection is None:
            connection = MCPOAuthConnection(
                tenant_id=server.tenant_id,
                mcp_server_id=server.id,
                user_id=self.user_id,
                issuer=discovery.issuer,
                resource=discovery.resource,
                strategy=STRATEGY_ID_JAG,
            )
        connection.strategy = STRATEGY_ID_JAG
        connection.issuer = discovery.issuer
        connection.resource = discovery.resource
        self._apply(connection, response)
        connection = await self._save(connection)
        return connection.access_token

    async def _idp_token_if_enabled(self) -> Optional[IdpUserToken]:
        tenant = self._tenant
        federation: dict[str, Any] = dict(
            getattr(tenant, "federation_config", None) or {}
        )
        if not federation.get(ID_JAG_FEDERATION_FLAG) or self.user_id is None:
            return None
        async with self._repo() as repo:
            token = await repo.get_idp_token(user_id=self.user_id)
        if token is None or not token.id_token:
            return None
        if (
            token.id_token_expires_at is not None
            and token.id_token_expires_at <= datetime.now(timezone.utc)
        ):
            return None
        return token

    async def _fresh_token(
        self, server: MCPServer, connection: MCPOAuthConnection
    ) -> str:
        """The stored access token, refreshed under a lock when it is stale."""
        if connection.token_is_fresh():
            assert connection.access_token is not None
            return connection.access_token
        if not connection.refresh_token:
            connection.invalidate("access_token_expired")
            await self._save(connection)
            raise self.user_action_required(server, reason="access_token_expired")

        lock_key = f"mcp_oauth:refresh:{connection.id}"
        acquired = await self._acquire_lock(lock_key)
        try:
            if not acquired:
                # Another worker is refreshing this very connection; take its
                # result instead of spending the same refresh token.
                reloaded = await self._wait_for_refresh(connection)
                if reloaded is not None and reloaded.token_is_fresh():
                    assert reloaded.access_token is not None
                    return reloaded.access_token
                acquired = await self._acquire_lock(lock_key)
                if not acquired:
                    raise self.user_action_required(server, reason="refresh_busy")
            # The lock is held: re-read the row. Another worker may have
            # refreshed and rotated the refresh token since this provider
            # loaded its copy; spending that stale token would get the
            # connection refused and torn down.
            latest = await self._reload(connection)
            if latest is not None:
                if latest.token_is_fresh():
                    assert latest.access_token is not None
                    return latest.access_token
                if not latest.refresh_token:
                    raise self.user_action_required(
                        server, reason=latest.last_error or "not_connected"
                    )
                connection = latest
            return await self._refresh(server, connection)
        finally:
            if acquired:
                await self._release_lock(lock_key)

    async def _refresh(self, server: MCPServer, connection: MCPOAuthConnection) -> str:
        assert connection.refresh_token is not None
        try:
            discovery = await discover(server.http_url)
        except OAuthDiscoveryError as exc:
            raise self.user_action_required(server, reason=str(exc)) from exc
        config = self._decrypted_config(server)
        credential = await self._as_client_for(server, discovery, config)
        try:
            response = await refresh_access_token(
                token_endpoint=discovery.token_endpoint,
                refresh_token=connection.refresh_token,
                resource=connection.resource,
                credential=credential,
            )
        except OAuthTokenError as exc:
            if exc.is_invalid_grant or exc.status_code in (400, 401):
                # Refused: unless the row was rotated under us meanwhile (then
                # the stored tokens are the good ones), the connection is dead.
                latest = await self._reload(connection)
                if (
                    latest is not None
                    and latest.refresh_token
                    and latest.refresh_token != connection.refresh_token
                    and latest.token_is_fresh()
                ):
                    assert latest.access_token is not None
                    return latest.access_token
                connection.invalidate(exc.error or "refresh_rejected")
                await self._save(connection)
                raise self.user_action_required(
                    server, reason=connection.last_error or "refresh_rejected"
                ) from exc
            # A transient failure keeps the connection; the call fails for now.
            raise
        self._apply(connection, response)
        connection = await self._save(connection)
        assert connection.access_token is not None
        return connection.access_token

    # -- helpers --------------------------------------------------------------

    def _decrypted_config(self, server: MCPServer) -> dict[str, Any]:
        config = dict(server.http_auth_config_schema or {})
        secret = config.get("client_secret")
        if isinstance(secret, str) and secret and self._encryption.is_encrypted(secret):
            config["client_secret"] = self._encryption.decrypt(secret)
        return config

    @staticmethod
    def _scope_override(config: dict[str, Any]) -> Optional[str]:
        scope = config.get("scope")
        return scope.strip() if isinstance(scope, str) and scope.strip() else None

    async def _as_client_for(
        self,
        server: MCPServer,
        discovery: OAuthServerDiscovery,
        config: dict[str, Any],
    ) -> ClientCredential:
        """Eneo's client identity at this server's authorization server."""
        client_id = config.get("client_id")
        if isinstance(client_id, str) and client_id:
            secret = config.get("client_secret")
            secret_str = secret if isinstance(secret, str) and secret else None
            return ClientCredential(
                client_id=client_id,
                client_secret=secret_str,
                auth_method=choose_client_auth_method(
                    secret_str, discovery.token_endpoint_auth_methods
                ),
            )
        async with self._repo() as repo:
            registration = await repo.get_registration(
                mcp_server_id=server.id, issuer=discovery.issuer
            )
        if registration is not None:
            return ClientCredential(
                client_id=registration.client_id,
                client_secret=registration.client_secret,
                auth_method=choose_client_auth_method(
                    registration.client_secret, discovery.token_endpoint_auth_methods
                ),
            )
        cimd = client_metadata.client_metadata_url(self._settings)
        if cimd is not None and discovery.supports_cimd:
            return ClientCredential(
                client_id=cimd, client_secret=None, auth_method="none"
            )
        raise self.user_action_required(server, reason="client_not_registered")

    @staticmethod
    def _apply(connection: MCPOAuthConnection, response: TokenResponse) -> None:
        connection.accept_tokens(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            expires_at=response.expires_at,
            scopes=response.scopes,
        )

    async def _acquire_lock(self, key: str) -> bool:
        if self._redis is None:
            return True
        try:
            result: object = await self._redis.set(
                key, "1", nx=True, ex=REFRESH_LOCK_TTL_SECONDS
            )
        except Exception as exc:  # pragma: no cover - Redis outage
            logger.warning("Refresh lock unavailable (%s); proceeding without", exc)
            return True
        return bool(result)

    async def _release_lock(self, key: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(key)
        except Exception:  # pragma: no cover - Redis outage
            pass

    async def _wait_for_refresh(
        self, connection: MCPOAuthConnection
    ) -> Optional[MCPOAuthConnection]:
        waited = 0.0
        while waited < REFRESH_LOCK_WAIT_SECONDS:
            await asyncio.sleep(REFRESH_LOCK_POLL_SECONDS)
            waited += REFRESH_LOCK_POLL_SECONDS
            async with self._repo() as repo:
                reloaded = await repo.get_connection(
                    mcp_server_id=connection.mcp_server_id, user_id=connection.user_id
                )
            if reloaded is not None and reloaded.token_is_fresh():
                self._connections[(reloaded.mcp_server_id, reloaded.user_id)] = reloaded
                return reloaded
        return None


def connection_public_state(
    server: MCPServer, connection: Optional[MCPOAuthConnection]
) -> dict[str, Any]:
    """The connection as clients see it (never the tokens)."""
    connected = connection is not None and connection.is_connected
    return {
        "mcp_server_id": str(server.id),
        "server_name": server.name,
        "auth_scope": server.auth_scope,
        "status": "connected"
        if connected
        else ("needs_authorization" if connection is not None else "not_connected"),
        "strategy": connection.strategy if connection is not None else None,
        "scopes": list(connection.scopes) if connection is not None else [],
        "connected_at": connection.created_at.isoformat()
        if connection is not None and connection.created_at is not None
        else None,
        "connected_by_user_id": str(connection.connected_by_user_id)
        if connection is not None and connection.connected_by_user_id is not None
        else None,
        "last_error": connection.last_error if connection is not None else None,
    }
