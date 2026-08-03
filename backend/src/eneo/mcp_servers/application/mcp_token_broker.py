"""MCP token broker: mints audience-bound tokens via the user's IdP.

For a server configured ``auth_scope=per_user`` or ``per_tenant`` the
broker takes the place of the static bearer credential: it discovers the
MCP server's authorization-server metadata (RFC 9728), enforces the
issuer gate, and runs the strategy-specific exchange (RFC 8693 same-IdP
today, ID-JAG for Enterprise-Managed Authorization). The result is
cached in ``mcp_exchanged_tokens`` so subsequent calls in the same chat
session don't redo the round-trip.

The broker is the only place ``OidcTokenStore`` exposes plaintext
refresh tokens to. Plaintext is held in memory only for the duration of
one ``get_token`` call; the cache row writes ciphertext.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional, Union, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import is_service_api_key
from eneo.authentication.oidc_token_store import (
    IdpRefreshFailedError,
    OidcTokenStoreError,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens
from eneo.main.logging import get_logger
from eneo.mcp_servers.application.token_exchange import (
    ConcreteExchangeProtocol,
    ExchangedToken,
    TokenExchangeError,
    TokenExchangeTarget,
    TokenExchangeUserActionRequired,
    classify_error,
    decode_expires_at,
    post_form,
    resolve_strategy,
)
from eneo.mcp_servers.application.token_exchange.rfc8693 import (
    peek_jwt_exp,
    validate_exchanged_token_claims,
)
from eneo.mcp_servers.infrastructure.oauth_discovery import (
    DiscoveryError,
    OAuthDiscoveryService,
    ProtectedResourceMetadata,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.audit.application.audit_service import AuditService
    from eneo.authentication.oidc_token_store import OidcTokenStore
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Principal and error vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserPrincipal:
    """Subject for ``per_user`` exchanges: the human caller."""

    user: "UserInDB"


@dataclass(frozen=True)
class TenantPrincipal:
    """Subject for ``per_tenant`` exchanges: the tenant service account.

    Carries the calling ``UserInDB`` separately so audit log entries
    still attribute the action to the human who triggered it.
    """

    user: "UserInDB"
    tenant_id: UUID


Principal = Union[UserPrincipal, TenantPrincipal]


class MCPSameIdpMismatchError(Exception):
    """PRM ``authorization_servers`` does not include the expected issuer.
    The broker refuses to exchange against an unrelated authorization
    server."""


class MCPRequiresUserIdentityError(Exception):
    """A service-key caller hit a ``per_user`` MCP server. The exchange has
    no human subject to delegate from."""


class MCPNotAuthenticatedError(Exception):
    """The caller has no persisted IdP refresh token. They logged in via a
    non-OIDC method (local password) or their session was revoked."""


class MCPBrokerConfigurationError(Exception):
    """Operator misconfiguration: tenant federation_config is missing
    required fields (e.g. ``client_id``, ``token_endpoint``) or the
    per-tenant service-account credentials. Surfaces as 500 to keep
    the caller honest."""


CACHE_SAFETY_MARGIN_SECONDS = 60


class MCPTokenBroker:
    """Lazy two-tier cache + token-exchange strategy dispatcher."""

    def __init__(
        self,
        *,
        session: "AsyncSession",
        encryption_service: "EncryptionService",
        audit_service: "AuditService",
        oidc_token_store: "OidcTokenStore",
        discovery: Optional[OAuthDiscoveryService] = None,
    ) -> None:
        self._session = session
        self._encryption = encryption_service
        self._audit = audit_service
        self._oidc_token_store = oidc_token_store
        self._discovery = discovery or OAuthDiscoveryService()

    @asynccontextmanager
    async def _tx(self) -> AsyncGenerator[None]:
        # eneo's sessionmaker has autobegin=False. The broker is invoked
        # lazily during SSE streaming, by which time FastAPI has torn down
        # the request-level transaction even though the session is still
        # alive. Mirror ChatSessionMcpStateRepo._tx: reuse the outer tx
        # if present, else open a short one for this call.
        if self._session.in_transaction():
            yield
            return
        async with self._session.begin():
            yield

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_token(
        self,
        *,
        mcp_server: "MCPServer",
        tenant_federation_config: dict[str, Any],
        principal: Principal,
    ) -> str:
        """Return a bearer access token audienced for this MCP server.

        Raises ``MCPSameIdpMismatchError``, ``MCPRequiresUserIdentityError``,
        ``MCPNotAuthenticatedError``, ``MCPBrokerConfigurationError``,
        :class:`TokenExchangeError`, or :class:`TokenExchangeUserActionRequired`
        depending on the failure mode. The caller (MCPClient) maps these to
        HTTP status codes.
        """
        if mcp_server.auth_scope == "static_bearer":
            raise MCPBrokerConfigurationError(
                "Broker invoked on static_bearer server; caller should have "
                "used http_auth_config_schema directly"
            )

        subject_type, subject_id = self._resolve_subject(
            mcp_server=mcp_server, principal=principal
        )

        try:
            prm = await self._discovery.get_protected_resource_metadata(
                http_url=mcp_server.http_url
            )
        except DiscoveryError as exc:
            raise MCPBrokerConfigurationError(
                f"PRM discovery failed for {mcp_server.http_url}: {exc}"
            ) from exc
        idp_issuer = self._enforce_issuer_gate(
            mcp_server=mcp_server,
            prm=prm,
            tenant_federation_config=tenant_federation_config,
        )

        # Resolve the audience/scope override with the tenant-wide default
        # as a fallback: per-server override > tenant default > the MCP
        # server's canonical RFC 8707 resource from PRM.
        tenant_default_target = tenant_federation_config.get("mcp_default_target")
        target_override = mcp_server.target_resource_or_scope or (
            tenant_default_target
            if isinstance(tenant_default_target, str) and tenant_default_target
            else None
        )
        target = TokenExchangeTarget(
            audience=prm.resource,
            resource_or_scope=target_override,
        )
        effective_audience = target.resource_or_scope or target.audience
        exchange_protocol = await self._resolve_concrete_protocol(
            mcp_server=mcp_server, idp_issuer=idp_issuer
        )
        token_endpoint, client_id, client_secret = await self._resolve_strategy_inputs(
            idp_issuer=idp_issuer,
            tenant_federation_config=tenant_federation_config,
        )

        async with self._tx():
            cached_token = await self._cache_lookup(
                mcp_server_id=mcp_server.id,
                subject_type=subject_type,
                subject_id=subject_id,
                audience=effective_audience,
                idp_issuer=idp_issuer,
            )
        if cached_token is not None:
            return cached_token

        # Try refreshing a cached refresh token before doing a full exchange.
        async with self._tx():
            cached_refresh = await self._cache_get_refresh_token(
                mcp_server_id=mcp_server.id,
                subject_type=subject_type,
                subject_id=subject_id,
                audience=effective_audience,
                idp_issuer=idp_issuer,
            )
        if cached_refresh is not None:
            try:
                exchanged = await self._refresh_exchanged_token(
                    refresh_token=cached_refresh,
                    token_endpoint=token_endpoint,
                    client_id=client_id,
                    client_secret=client_secret,
                    target=target,
                    idp_issuer=idp_issuer,
                )
                logger.info(
                    "Refreshed cached exchanged token for MCP server %s",
                    mcp_server.name,
                )
                async with self._tx():
                    await self._cache_persist(
                        mcp_server=mcp_server,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        audience=effective_audience,
                        idp_issuer=idp_issuer,
                        exchanged=exchanged,
                    )
                    await self._audit_exchange_succeeded(
                        principal=principal,
                        mcp_server=mcp_server,
                        audience=effective_audience,
                        idp_issuer=idp_issuer,
                        expires_at=exchanged.expires_at,
                    )
                return exchanged.access_token
            except (TokenExchangeError, TokenExchangeUserActionRequired) as exc:
                logger.info(
                    "Refresh of cached exchanged token failed for MCP server %s; "
                    "falling through to full exchange: %s",
                    mcp_server.name,
                    str(exc),
                )

        try:
            if isinstance(principal, UserPrincipal):
                async with self._tx():
                    exchanged = await self._exchange_as_user(
                        user=principal.user,
                        idp_issuer=idp_issuer,
                        exchange_protocol=exchange_protocol,
                        target=target,
                        token_endpoint=token_endpoint,
                        client_id=client_id,
                        client_secret=client_secret,
                    )
            else:
                exchanged = await self._exchange_as_tenant(
                    tenant_federation_config=tenant_federation_config,
                    target=target,
                    token_endpoint=token_endpoint,
                )
        except (
            TokenExchangeError,
            TokenExchangeUserActionRequired,
        ) as exc:
            async with self._tx():
                await self._audit_exchange_denied(
                    principal=principal,
                    mcp_server=mcp_server,
                    reason="exchange_failed",
                    detail=str(exc),
                )
            raise

        # If the IdP returned an expired access token with a refresh token
        # (Keycloak derives expiry from the original SSO session), refresh
        # immediately to get a valid access token.
        now = datetime.now(timezone.utc)
        if exchanged.expires_at <= now and exchanged.refresh_token:
            try:
                exchanged = await self._refresh_exchanged_token(
                    refresh_token=exchanged.refresh_token,
                    token_endpoint=token_endpoint,
                    client_id=client_id,
                    client_secret=client_secret,
                    target=target,
                    idp_issuer=idp_issuer,
                )
                logger.info(
                    "Immediately refreshed expired exchanged token for MCP server %s",
                    mcp_server.name,
                )
            except (TokenExchangeError, TokenExchangeUserActionRequired) as exc:
                async with self._tx():
                    await self._audit_exchange_denied(
                        principal=principal,
                        mcp_server=mcp_server,
                        reason="post_exchange_refresh_failed",
                        detail=str(exc),
                    )
                raise

        async with self._tx():
            await self._cache_persist(
                mcp_server=mcp_server,
                subject_type=subject_type,
                subject_id=subject_id,
                audience=effective_audience,
                idp_issuer=idp_issuer,
                exchanged=exchanged,
            )
            await self._audit_exchange_succeeded(
                principal=principal,
                mcp_server=mcp_server,
                audience=effective_audience,
                idp_issuer=idp_issuer,
                expires_at=exchanged.expires_at,
            )
        return exchanged.access_token

    async def purge_cache_for_server(self, mcp_server_id: UUID) -> int:
        """Delete every cached exchanged token for a server.

        Called when the server's ``auth_scope``, ``expected_idp_issuer``,
        or ``http_url`` changes: the cached audience is no longer
        guaranteed to match.
        """
        async with self._tx():
            result = await self._session.execute(
                sa.delete(MCPExchangedTokens).where(
                    MCPExchangedTokens.mcp_server_id == mcp_server_id
                )
            )
        return affected_row_count(result)

    async def purge_cache_for_user(self, user_id: UUID) -> int:
        """Drop cached tokens for a user (logout / revocation)."""
        async with self._tx():
            result = await self._session.execute(
                sa.delete(MCPExchangedTokens).where(
                    MCPExchangedTokens.subject_type == "user",
                    MCPExchangedTokens.subject_id == user_id,
                )
            )
        return affected_row_count(result)

    async def purge_cache_for_tenant(self, tenant_id: UUID) -> int:
        """Drop cached exchanged tokens for a tenant."""
        async with self._tx():
            result = await self._session.execute(
                sa.delete(MCPExchangedTokens).where(
                    MCPExchangedTokens.tenant_id == tenant_id
                )
            )
        return affected_row_count(result)

    # ------------------------------------------------------------------
    # Subject resolution
    # ------------------------------------------------------------------

    def _resolve_subject(
        self,
        *,
        mcp_server: "MCPServer",
        principal: Principal,
    ) -> tuple[str, UUID]:
        scope = mcp_server.auth_scope
        if scope == "per_user":
            if not isinstance(principal, UserPrincipal):
                raise MCPBrokerConfigurationError(
                    "per_user MCP server invoked with TenantPrincipal; "
                    "this is a request-routing bug"
                )
            if is_service_api_key(principal.user):
                raise MCPRequiresUserIdentityError(
                    "MCP server requires a human user identity; service "
                    "API keys cannot drive per_user OAuth"
                )
            return "user", principal.user.id

        if scope == "per_tenant":
            # Even a UserPrincipal can drive per_tenant: the user is the
            # actor, the tenant service account is the subject.
            tenant_id = (
                principal.tenant_id
                if isinstance(principal, TenantPrincipal)
                else principal.user.tenant_id
            )
            return "tenant", tenant_id

        raise MCPBrokerConfigurationError(
            f"Unknown auth_scope: {mcp_server.auth_scope}"
        )

    # ------------------------------------------------------------------
    # Issuer gate (PRM + expected_idp_issuer)
    # ------------------------------------------------------------------

    def _enforce_issuer_gate(
        self,
        *,
        mcp_server: "MCPServer",
        prm: ProtectedResourceMetadata,
        tenant_federation_config: dict[str, Any],
    ) -> str:
        """Return the issuer the broker will hit; raise on mismatch.

        Resolution order for the expected issuer:

        1. ``mcp_server.expected_idp_issuer``: per-server override for the
           rare cross-IdP case (operator explicitly federates one MCP
           server to a different IdP than the tenant default).
        2. ``tenant.federation_config.issuer``: the canonical tenant IdP
           that the user already authenticated against at login. This is
           the common path; admins configure SSO once at the tenant level
           and every MCP server inherits it.

        Then both of these must hold:

        - The resolved issuer is listed in the PRM's ``authorization_servers``
          (server agrees on its own IdP).
        - For UserPrincipal flows, the user logged in via the same IdP
          (we have an ``idp_user_tokens`` row for that issuer). The
          subject-token lookup in :meth:`_exchange_as_user` enforces this.
        """
        expected = mcp_server.expected_idp_issuer or tenant_federation_config.get(
            "issuer"
        )
        if not isinstance(expected, str) or not expected:
            raise MCPBrokerConfigurationError(
                "MCP server has no expected_idp_issuer and the tenant has no "
                "federation_config.issuer; refusing to exchange against an "
                "unknown authorization server"
            )

        # PRM authorization_servers may carry the issuer URL with or
        # without a trailing slash; normalize both sides for compare.
        normalized_expected = expected.rstrip("/")
        normalized_servers = {s.rstrip("/") for s in prm.authorization_servers}
        if normalized_expected not in normalized_servers:
            raise MCPSameIdpMismatchError(
                f"MCP server PRM lists authorization_servers="
                f"{prm.authorization_servers!r} "
                f"but server is configured for issuer {expected!r}"
            )
        return expected

    # ------------------------------------------------------------------
    # Strategy input resolution
    # ------------------------------------------------------------------

    async def _resolve_concrete_protocol(
        self,
        *,
        mcp_server: "MCPServer",
        idp_issuer: str,
    ) -> ConcreteExchangeProtocol:
        """Map the configured ``exchange_protocol`` to a concrete strategy.

        ``auto`` currently resolves to ``rfc8693``; ID-JAG grant-profile
        detection against the authorization server's metadata plugs in
        here when the ``id_jag`` strategy lands.
        """
        configured = mcp_server.exchange_protocol
        if configured == "rfc8693":
            return "rfc8693"
        if configured == "auto":
            return "rfc8693"
        raise MCPBrokerConfigurationError(
            f"exchange_protocol {configured!r} is not available yet"
        )

    async def _resolve_strategy_inputs(
        self,
        *,
        idp_issuer: str,
        tenant_federation_config: dict[str, Any],
    ) -> tuple[str, str, Optional[str]]:
        """Translate tenant federation_config into
        (token_endpoint, client_id, client_secret).

        ``token_endpoint`` is read from the config when present, otherwise
        resolved via the IdP's authorization-server / OIDC metadata (with
        the Keycloak URL convention as a last-resort fallback inside the
        discovery service).
        """
        token_endpoint = tenant_federation_config.get("token_endpoint")
        if not token_endpoint:
            token_endpoint = await self._discovery.resolve_token_endpoint(
                issuer=idp_issuer
            )
        if not isinstance(token_endpoint, str) or not token_endpoint:
            raise MCPBrokerConfigurationError(
                "tenant.federation_config.token_endpoint required for "
                "the broker; not present and could not be derived from issuer"
            )

        client_id = tenant_federation_config.get("client_id")
        client_secret = tenant_federation_config.get("client_secret")
        if not isinstance(client_id, str) or not client_id:
            raise MCPBrokerConfigurationError(
                "tenant.federation_config.client_id required for the broker"
            )
        # client_secret is stored as a Fernet envelope (enc:fernet:v1:...) in
        # the JSONB column; decrypt before posting to the IdP. CredentialResolver
        # does the same on the login path; the broker bypasses it because it
        # needs additional fields (issuer, token_endpoint) that
        # CredentialResolver does not surface today.
        if (
            isinstance(client_secret, str)
            and self._encryption.is_active()
            and self._encryption.is_encrypted(client_secret)
        ):
            client_secret = self._encryption.decrypt(client_secret)

        return (
            token_endpoint,
            client_id,
            client_secret if isinstance(client_secret, str) else None,
        )

    # ------------------------------------------------------------------
    # Subject acquisition + strategy call
    # ------------------------------------------------------------------

    async def _exchange_as_user(
        self,
        *,
        user: "UserInDB",
        idp_issuer: str,
        exchange_protocol: ConcreteExchangeProtocol,
        target: TokenExchangeTarget,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
    ) -> ExchangedToken:
        stored = await self._oidc_token_store.get_decrypted(
            user_id=user.id, idp_issuer=idp_issuer
        )
        if stored is None:
            raise MCPNotAuthenticatedError(
                "No active IdP refresh token stored for this user; the "
                "user must log in via SSO before per_user MCP servers can "
                "be reached"
            )

        # If the cached access token is missing or about to expire, refresh
        # against the IdP first. Failure here is a user-action requirement.
        subject_token = stored.access_token
        if (
            subject_token is None
            or stored.access_token_expires_at is None
            or stored.access_token_expires_at
            < datetime.now(timezone.utc)
            + timedelta(seconds=CACHE_SAFETY_MARGIN_SECONDS)
        ):
            try:
                refreshed = await self._oidc_token_store.refresh_idp_token(
                    user=user,
                    idp_issuer=idp_issuer,
                    token_endpoint=token_endpoint,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            except IdpRefreshFailedError as exc:
                raise MCPNotAuthenticatedError(
                    "Stored IdP refresh token can no longer refresh the main "
                    "login token; user must re-authenticate"
                ) from exc
            except OidcTokenStoreError as exc:
                raise TokenExchangeError(
                    "Unable to refresh the main login token before MCP token exchange"
                ) from exc
            subject_token = refreshed.access_token
            if not subject_token:
                raise MCPNotAuthenticatedError(
                    "IdP refresh returned no access_token; user must re-authenticate"
                )

        strategy = resolve_strategy(exchange_protocol)
        return await strategy.exchange(
            subject_access_token=subject_token,
            target=target,
            token_endpoint=token_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            idp_issuer=idp_issuer,
        )

    async def _exchange_as_tenant(
        self,
        *,
        tenant_federation_config: dict[str, Any],
        target: TokenExchangeTarget,
        token_endpoint: str,
    ) -> ExchangedToken:
        """``client_credentials`` grant against the IdP using the tenant
        service-account credentials configured in ``federation_config``.

        No token-exchange grant is needed; the service account is the
        subject directly. ``audience`` / ``scope`` carries the target.
        """
        sa_config_raw = tenant_federation_config.get("mcp_service_account")
        sa_config: dict[str, Any] = (
            cast("dict[str, Any]", sa_config_raw)
            if isinstance(sa_config_raw, dict)
            else {}
        )
        sa_client_id = sa_config.get("client_id")
        sa_client_secret_cipher = sa_config.get("client_secret_ciphertext")
        if not isinstance(sa_client_id, str) or not sa_client_id:
            raise MCPBrokerConfigurationError(
                "per_tenant MCP server requires "
                "tenant.federation_config.mcp_service_account.client_id"
            )
        if not isinstance(sa_client_secret_cipher, str) or not sa_client_secret_cipher:
            raise MCPBrokerConfigurationError(
                "per_tenant MCP server requires encrypted "
                "tenant.federation_config.mcp_service_account.client_secret_ciphertext"
            )
        sa_client_secret = self._encryption.decrypt(sa_client_secret_cipher)

        form = {
            "grant_type": "client_credentials",
            "client_id": sa_client_id,
            "client_secret": sa_client_secret,
        }
        # Both audience and scope are commonly used; send both so the IdP
        # picks whichever it supports.
        if target.audience:
            form["audience"] = target.audience
        if target.resource_or_scope:
            form["scope"] = target.resource_or_scope

        now = datetime.now(timezone.utc)
        status_code, payload = await post_form(token_endpoint=token_endpoint, form=form)
        if status_code >= 400:
            raise classify_error(status_code, payload)

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExchangeError(
                "client_credentials returned 2xx without an access_token"
            )

        scope = payload.get("scope")
        return ExchangedToken(
            access_token=access_token,
            expires_at=decode_expires_at(payload, now),
            issued_at=now,
            scope=str(scope) if isinstance(scope, str) else None,
        )

    # ------------------------------------------------------------------
    # Cache read / write
    # ------------------------------------------------------------------

    async def _cache_lookup(
        self,
        *,
        mcp_server_id: UUID,
        subject_type: str,
        subject_id: UUID,
        audience: str,
        idp_issuer: str,
    ) -> Optional[str]:
        safety_cutoff = datetime.now(timezone.utc) + timedelta(
            seconds=CACHE_SAFETY_MARGIN_SECONDS
        )
        row = (
            await self._session.execute(
                sa.select(MCPExchangedTokens).where(
                    MCPExchangedTokens.mcp_server_id == mcp_server_id,
                    MCPExchangedTokens.subject_type == subject_type,
                    MCPExchangedTokens.subject_id == subject_id,
                    MCPExchangedTokens.audience == audience,
                    MCPExchangedTokens.idp_issuer == idp_issuer,
                    MCPExchangedTokens.expires_at > safety_cutoff,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._encryption.decrypt(row.token_ciphertext)

    async def _cache_get_refresh_token(
        self,
        *,
        mcp_server_id: UUID,
        subject_type: str,
        subject_id: UUID,
        audience: str,
        idp_issuer: str,
    ) -> Optional[str]:
        """Retrieve a cached refresh token for an expired entry."""
        row = (
            await self._session.execute(
                sa.select(MCPExchangedTokens.refresh_token_ciphertext).where(
                    MCPExchangedTokens.mcp_server_id == mcp_server_id,
                    MCPExchangedTokens.subject_type == subject_type,
                    MCPExchangedTokens.subject_id == subject_id,
                    MCPExchangedTokens.audience == audience,
                    MCPExchangedTokens.idp_issuer == idp_issuer,
                    MCPExchangedTokens.refresh_token_ciphertext.isnot(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._encryption.decrypt(row)

    async def _refresh_exchanged_token(
        self,
        *,
        refresh_token: str,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str],
        target: TokenExchangeTarget,
        idp_issuer: str,
    ) -> ExchangedToken:
        """Use a cached refresh token to get a fresh access token."""
        form: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        if client_secret:
            form["client_secret"] = client_secret

        now = datetime.now(timezone.utc)
        status_code, payload = await post_form(token_endpoint=token_endpoint, form=form)
        if status_code >= 400:
            raise classify_error(status_code, payload)

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExchangeError(
                "Refresh of exchanged token returned 2xx without an access_token"
            )

        new_refresh = payload.get("refresh_token")
        jwt_exp = peek_jwt_exp(access_token)
        jwt_exp = (
            validate_exchanged_token_claims(
                access_token=access_token,
                subject_access_token=None,
                effective_audience=target.resource_or_scope or target.audience,
                idp_issuer=idp_issuer,
                now=now,
            )
            or jwt_exp
        )
        expires_at = jwt_exp if jwt_exp else decode_expires_at(payload, now)
        scope = payload.get("scope")

        return ExchangedToken(
            access_token=access_token,
            expires_at=expires_at,
            issued_at=now,
            scope=str(scope) if isinstance(scope, str) else None,
            refresh_token=(
                new_refresh
                if isinstance(new_refresh, str) and new_refresh
                else refresh_token
            ),
        )

    async def _cache_persist(
        self,
        *,
        mcp_server: "MCPServer",
        subject_type: str,
        subject_id: UUID,
        audience: str,
        idp_issuer: str,
        exchanged: ExchangedToken,
    ) -> None:
        ciphertext = self._encryption.encrypt(exchanged.access_token)
        refresh_ciphertext = (
            self._encryption.encrypt(exchanged.refresh_token)
            if exchanged.refresh_token
            else None
        )
        values = {
            "mcp_server_id": mcp_server.id,
            "tenant_id": mcp_server.tenant_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "token_ciphertext": ciphertext,
            "refresh_token_ciphertext": refresh_ciphertext,
            "expires_at": exchanged.expires_at,
            "issued_at": exchanged.issued_at,
            "audience": audience,
            "idp_issuer": idp_issuer,
        }
        stmt = (
            insert(MCPExchangedTokens)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_mcp_exchanged_tokens_server_subject",
                set_={
                    "token_ciphertext": ciphertext,
                    "refresh_token_ciphertext": refresh_ciphertext,
                    "expires_at": exchanged.expires_at,
                    "issued_at": exchanged.issued_at,
                    "audience": audience,
                    "idp_issuer": idp_issuer,
                    "updated_at": sa.func.now(),
                },
            )
        )
        await self._session.execute(stmt)

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    async def _audit_exchange_succeeded(
        self,
        *,
        principal: Principal,
        mcp_server: "MCPServer",
        audience: str,
        idp_issuer: str,
        expires_at: datetime,
    ) -> None:
        user = principal.user
        await self._audit.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.MCP_TOKEN_EXCHANGED,
            entity_type=EntityType.MCP_SERVER,
            entity_id=mcp_server.id,
            description=(
                f"Token exchange succeeded for MCP server '{mcp_server.name}'"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=mcp_server,
                extra={
                    "subject_type": (
                        "user" if isinstance(principal, UserPrincipal) else "tenant"
                    ),
                    "audience": audience,
                    "idp_issuer": idp_issuer,
                    "expires_at": expires_at.isoformat(),
                },
            ),
        )

    async def _audit_exchange_denied(
        self,
        *,
        principal: Principal,
        mcp_server: "MCPServer",
        reason: str,
        detail: Optional[str] = None,
    ) -> None:
        user = principal.user
        await self._audit.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.MCP_TOKEN_EXCHANGE_DENIED,
            entity_type=EntityType.MCP_SERVER,
            entity_id=mcp_server.id,
            description=(
                f"Token exchange denied for MCP server '{mcp_server.name}': {reason}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=mcp_server,
                extra={
                    "reason": reason,
                    "detail": detail,
                    "subject_type": (
                        "user" if isinstance(principal, UserPrincipal) else "tenant"
                    ),
                },
            ),
        )
