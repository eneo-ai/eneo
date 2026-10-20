"""The connect flow: Eneo as an OAuth 2.1 authorization-code client.

The user's browser does the redirect, so the flow is split in two backend
calls. ``authorize_url`` discovers the authorization server, resolves Eneo's
client identity there (an admin pre-registration, the Client ID Metadata
Document, or Dynamic Client Registration, in the spec's priority), generates
PKCE and ``state``, records the expected issuer, and hands back the URL the
popup opens. ``complete`` consumes the state once, validates ``iss`` (RFC
9207), exchanges the code with the ``resource`` parameter and stores the
tokens on the user's connection, or on the server's shared connection when an
administrator connects a service account.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlencode
from uuid import UUID

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.mcp_servers.application.mcp_oauth_client_identity import (
    credential_for_registration,
    dcr_request_for,
    resolve_client_credential,
)
from eneo.mcp_servers.application.mcp_oauth_signing_keys import current_signer
from eneo.mcp_servers.application.mcp_oauth_token_provider import (
    MCPOAuthTokenProvider,
    connection_public_state,
)
from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    STRATEGY_AUTH_CODE,
    MCPOAuthClientRegistration,
    MCPOAuthConnection,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.oauth import client_metadata
from eneo.mcp_servers.infrastructure.oauth.authorization_wait import (
    MCPOAuthAuthorizationWaiter,
)
from eneo.mcp_servers.infrastructure.oauth.client_assertion import (
    ClientAssertionSigner,
)
from eneo.mcp_servers.infrastructure.oauth.discovery import (
    OAuthDiscoveryError,
    OAuthServerDiscovery,
    discover,
)
from eneo.mcp_servers.infrastructure.oauth.token_client import (
    ClientCredential,
    OAuthTokenError,
    exchange_authorization_code,
    register_client,
    revoke_token,
)
from eneo.roles.permissions import Permission

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from eneo.main.config import Settings
    from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import (
        MCPOAuthRepository,
    )
    from eneo.mcp_servers.domain.repositories.mcp_server_repo import (
        MCPServerRepository,
    )
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

# Pending authorizations live in Redis under the state they were started
# with; a callback consumes them once (GETDEL) and they expire on their own.
_STATE_PREFIX = "mcp_oauth:state:"
_STATE_TTL_SECONDS = 600


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class MCPOAuthService:
    def __init__(
        self,
        *,
        user: UserInDB,
        mcp_server_repo: MCPServerRepository,
        repo: MCPOAuthRepository,
        encryption_service: EncryptionService,
        settings: Settings,
        redis_client: aioredis.Redis,
        token_provider: MCPOAuthTokenProvider,
    ) -> None:
        self.user = user
        self._servers = mcp_server_repo
        self._repo = repo
        self._encryption = encryption_service
        self._settings = settings
        self._redis = redis_client
        self._tokens = token_provider

    # -- lookups ------------------------------------------------------------

    async def _oauth_server(self, mcp_server_id: UUID) -> MCPServer:
        server = await self._servers.one_or_none(id=mcp_server_id)
        if server is None or server.tenant_id != self.user.tenant_id:
            raise NotFoundException("MCP server not found")
        if not server.is_oauth:
            raise BadRequestException("This MCP server does not use OAuth")
        return server

    def _require_admin_for_shared(self, server: MCPServer) -> None:
        if server.is_shared_oauth and Permission.ADMIN not in self.user.permissions:
            raise UnauthorizedException(
                "Only an administrator can connect a shared MCP server"
            )

    def _principal_user_id(self, server: MCPServer) -> Optional[UUID]:
        if server.is_shared_oauth:
            return None
        user_id = self._tokens.user_id
        if user_id is None:
            raise UnauthorizedException(
                "A service key cannot authorize a per-user MCP server"
            )
        return user_id

    # -- client identity ----------------------------------------------------

    async def _signer(self) -> ClientAssertionSigner:
        return await current_signer(self._repo)

    async def _client_for(
        self, server: MCPServer, discovery: OAuthServerDiscovery
    ) -> ClientCredential:
        """Pre-registered, then CIMD, then DCR, as the spec orders them."""
        config = dict(server.http_auth_config_schema or {})
        secret = config.get("client_secret")
        if isinstance(secret, str) and secret and self._encryption.is_encrypted(secret):
            config["client_secret"] = self._encryption.decrypt(secret)
        credential = await resolve_client_credential(
            mcp_server_id=server.id,
            discovery=discovery,
            settings=self._settings,
            config=config,
            repo=self._repo,
            signer=self._signer,
        )
        if credential is not None:
            return credential

        if discovery.registration_endpoint is None:
            raise BadRequestException(
                "The authorization server supports neither Client ID Metadata "
                "Documents nor Dynamic Client Registration; an administrator "
                "must enter a pre-registered client id for this server."
            )
        request = dcr_request_for(discovery, self._settings)
        if request is None:
            raise BadRequestException(
                "PUBLIC_ORIGIN must be configured before Eneo can register as "
                "an OAuth client."
            )
        try:
            payload = await register_client(
                registration_endpoint=discovery.registration_endpoint, metadata=request
            )
        except OAuthTokenError as exc:
            raise BadRequestException(str(exc)) from exc
        secret = payload.get("client_secret")
        secret_str = secret if isinstance(secret, str) and secret else None
        # The method the client was registered with decides how it
        # authenticates from now on, whether or not the server echoes it.
        stored_payload = {
            key: value
            for key, value in payload.items()
            if key not in ("client_secret", "registration_access_token")
        }
        stored_payload.setdefault(
            "token_endpoint_auth_method", request["token_endpoint_auth_method"]
        )
        registration = await self._repo.save_registration(
            MCPOAuthClientRegistration(
                tenant_id=server.tenant_id,
                mcp_server_id=server.id,
                issuer=discovery.issuer,
                client_id=str(payload["client_id"]),
                client_secret=secret_str,
                source="dcr",
                registration_payload=stored_payload,
            )
        )
        return await credential_for_registration(registration, discovery, self._signer)

    # -- flow ---------------------------------------------------------------

    async def authorize_url(self, mcp_server_id: UUID) -> dict[str, str]:
        server = await self._oauth_server(mcp_server_id)
        self._require_admin_for_shared(server)
        principal = self._principal_user_id(server)
        redirect_uri = client_metadata.redirect_uri(self._settings)
        if redirect_uri is None:
            raise BadRequestException(
                "PUBLIC_ORIGIN must be configured before Eneo can act as an OAuth client"
            )
        try:
            discovery = await discover(server.http_url)
        except OAuthDiscoveryError as exc:
            raise BadRequestException(str(exc)) from exc
        credential = await self._client_for(server, discovery)

        config = dict(server.http_auth_config_schema or {})
        override = config.get("scope")
        scope = (
            override.strip()
            if isinstance(override, str) and override.strip()
            else discovery.default_scope()
        )
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(32)
        await self._redis.set(
            f"{_STATE_PREFIX}{state}",
            json.dumps(
                {
                    "user_id": str(self.user.id),
                    "tenant_id": str(self.user.tenant_id),
                    "principal_user_id": str(principal) if principal else None,
                    "mcp_server_id": str(server.id),
                    "issuer": discovery.issuer,
                    "resource": discovery.resource,
                    "token_endpoint": discovery.token_endpoint,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                    "client_id": credential.client_id,
                    "scope": scope,
                    # RFC 9207: only meaningful when the AS says it sends iss.
                    "iss_supported": bool(
                        discovery.raw_authorization_server.get(
                            "authorization_response_iss_parameter_supported"
                        )
                    ),
                }
            ),
            ex=_STATE_TTL_SECONDS,
        )
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": credential.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # RFC 8707: the token must be minted for this MCP server.
            "resource": discovery.resource,
        }
        if scope:
            params["scope"] = scope
        return {
            "url": f"{discovery.authorization_endpoint}?{urlencode(params)}",
            "state": state,
        }

    async def _pop_state(self, state: str) -> dict[str, Any]:
        raw: object = await self._redis.getdel(f"{_STATE_PREFIX}{state}")
        if raw is None:
            raise BadRequestException("Unknown or expired authorization state")
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8")
        try:
            payload: object = json.loads(str(raw))
        except ValueError as exc:
            raise BadRequestException("Corrupt authorization state") from exc
        if not isinstance(payload, dict):
            raise BadRequestException("Corrupt authorization state")
        pending: dict[str, Any] = dict(payload)  # type: ignore[arg-type]
        if pending.get("user_id") != str(self.user.id):
            raise BadRequestException("This authorization was started by another user")
        return pending

    async def complete(
        self,
        mcp_server_id: UUID,
        *,
        code: str,
        state: str,
        iss: Optional[str] = None,
    ) -> dict[str, Any]:
        pending = await self._pop_state(state)
        if pending.get("mcp_server_id") != str(mcp_server_id):
            raise BadRequestException("Authorization state belongs to another server")
        server = await self._oauth_server(mcp_server_id)
        self._require_admin_for_shared(server)

        # RFC 9207 issuer identification, per the spec's table.
        expected_issuer = str(pending["issuer"])
        if iss is not None:
            if iss != expected_issuer:
                raise BadRequestException(
                    "Authorization response came from an unexpected issuer"
                )
        elif pending.get("iss_supported"):
            raise BadRequestException(
                "Authorization response is missing the iss parameter"
            )

        try:
            discovery = await discover(server.http_url)
        except OAuthDiscoveryError as exc:
            raise BadRequestException(str(exc)) from exc
        if discovery.issuer != expected_issuer:
            raise BadRequestException(
                "The server's authorization server changed during authorization"
            )
        credential = await self._client_for(server, discovery)
        if credential.client_id != pending.get("client_id"):
            raise BadRequestException(
                "Eneo's client identity changed during authorization"
            )
        try:
            response = await exchange_authorization_code(
                token_endpoint=str(pending["token_endpoint"]),
                code=code,
                code_verifier=str(pending["code_verifier"]),
                redirect_uri=str(pending["redirect_uri"]),
                resource=str(pending["resource"]),
                credential=credential,
            )
        except OAuthTokenError as exc:
            raise BadRequestException(str(exc)) from exc

        principal_raw = pending.get("principal_user_id")
        principal = UUID(str(principal_raw)) if principal_raw else None
        if (principal is None) != server.is_shared_oauth:
            raise BadRequestException("The server's identity mode changed")
        connection = MCPOAuthConnection(
            tenant_id=server.tenant_id,
            mcp_server_id=server.id,
            user_id=principal,
            issuer=discovery.issuer,
            resource=str(pending["resource"]),
            strategy=STRATEGY_AUTH_CODE,
            connected_by_user_id=self.user.id,
        )
        requested_scope = pending.get("scope")
        connection.accept_tokens(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            expires_at=response.expires_at,
            scopes=response.scopes
            or (str(requested_scope).split() if requested_scope else []),
        )
        saved = await self._repo.save_connection(connection)
        if principal is not None:
            # A turn may be paused on this very authorization.
            await MCPOAuthAuthorizationWaiter(self._redis).mark_connected(
                principal, server.id
            )
        logger.info(
            "MCP OAuth connection established for '%s' (%s)",
            server.name,
            "shared" if saved.is_shared else "user",
        )
        return connection_public_state(server, saved)

    async def decline(self, mcp_server_id: UUID) -> None:
        """The user refused or abandoned the vendor's consent: a turn paused on
        this authorization proceeds without it instead of waiting it out."""
        server = await self._oauth_server(mcp_server_id)
        principal = self._principal_user_id(server)
        if principal is None:
            return
        await MCPOAuthAuthorizationWaiter(self._redis).mark_declined(
            principal, server.id
        )

    async def disconnect(self, mcp_server_id: UUID) -> bool:
        server = await self._oauth_server(mcp_server_id)
        self._require_admin_for_shared(server)
        principal = self._principal_user_id(server)
        connection = await self._repo.get_connection(
            mcp_server_id=server.id, user_id=principal
        )
        if connection is None:
            return False
        await self._revoke(server, connection)
        return await self._repo.delete_connection(
            mcp_server_id=server.id, user_id=principal
        )

    async def _revoke(self, server: MCPServer, connection: MCPOAuthConnection) -> None:
        """Tell the authorization server the tokens are retired (RFC 7009)."""
        token = connection.refresh_token or connection.access_token
        if not token:
            return
        try:
            discovery = await discover(server.http_url)
        except OAuthDiscoveryError:
            return
        if discovery.revocation_endpoint is None:
            return
        try:
            credential = await self._client_for(server, discovery)
        except BadRequestException:
            return
        await revoke_token(
            revocation_endpoint=discovery.revocation_endpoint,
            token=token,
            credential=credential,
        )

    # -- status -------------------------------------------------------------

    async def connections_for(self, servers: list[MCPServer]) -> list[dict[str, Any]]:
        """Connection state of the OAuth servers among ``servers`` for this user.

        A shared server reports its shared connection; the caller does not
        need to be the administrator who made it.
        """
        oauth_servers = [server for server in servers if server.is_oauth]
        if not oauth_servers:
            return []
        shared = {
            c.mcp_server_id: c
            for c in await self._repo.list_connections(
                mcp_server_ids=[s.id for s in oauth_servers if s.is_shared_oauth],
                user_id=None,
            )
        }
        mine: dict[UUID, MCPOAuthConnection] = {}
        user_id = self._tokens.user_id
        if user_id is not None:
            mine = {
                c.mcp_server_id: c
                for c in await self._repo.list_connections(
                    mcp_server_ids=[
                        s.id for s in oauth_servers if not s.is_shared_oauth
                    ],
                    user_id=user_id,
                )
            }
        stored = {
            server.id: (
                shared.get(server.id) if server.is_shared_oauth else mine.get(server.id)
            )
            for server in oauth_servers
        }
        # A row that says connected may have run out since: verify every
        # stale one the way a call would, all at once, so the list says what
        # the next call will find for each server, not only the one it hits.
        stale = [
            (server, connection)
            for server in oauth_servers
            if (connection := stored[server.id]) is not None
            and connection.is_connected
            and not connection.token_is_fresh()
        ]
        if stale:
            verified = await asyncio.gather(
                *(self._tokens.verify(server, c) for server, c in stale)
            )
            for (server, _), connection in zip(stale, verified):
                stored[server.id] = connection
        return [
            connection_public_state(server, stored[server.id])
            for server in oauth_servers
        ]

    async def my_connections(self) -> list[dict[str, Any]]:
        servers = await self._servers.query(tenant_id=self.user.tenant_id)
        return await self.connections_for(
            [server for server in servers if server.is_enabled]
        )

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
