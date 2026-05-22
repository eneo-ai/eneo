"""MCP token broker — mints audience-bound tokens via the user's IdP.

For a server configured ``auth_scope=per_user`` or ``per_tenant`` the
broker takes the place of the static bearer credential: it discovers the
MCP server's authorization-server metadata (RFC 9728), enforces the
same-IdP gate, and runs the strategy-specific exchange against the same
IdP the user already authenticated with (Keycloak via RFC 8693, Entra
via OBO, generic via RFC 8693). The result is cached in
``mcp_exchanged_tokens`` so subsequent calls in the same chat session
don't redo the round-trip.

The broker is the only place ``OidcTokenStore`` exposes plaintext
refresh tokens to. Plaintext is held in memory only for the duration of
one ``get_token`` call; the cache row writes ciphertext.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional, Union, cast
from urllib.parse import urlsplit
from uuid import UUID

import aiohttp
import sqlalchemy as sa

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_models import is_service_api_key
from intric.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens
from intric.main.logging import get_logger
from intric.mcp_servers.application.token_exchange import (
    ExchangedToken,
    IdpKind,
    TokenExchangeError,
    TokenExchangeTarget,
    TokenExchangeUserActionRequired,
    classify_error,
    decode_expires_at,
    post_form,
    resolve_strategy,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.audit.application.audit_service import AuditService
    from intric.authentication.oidc_token_store import OidcTokenStore
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.settings.encryption_service import EncryptionService
    from intric.users.user import UserInDB

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Principal and error vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserPrincipal:
    """Subject for ``per_user`` exchanges — the human caller."""

    user: "UserInDB"


@dataclass(frozen=True)
class TenantPrincipal:
    """Subject for ``per_tenant`` exchanges — the tenant service account.

    Carries the calling ``UserInDB`` separately so audit log entries
    still attribute the action to the human who triggered it.
    """

    user: "UserInDB"
    tenant_id: UUID


Principal = Union[UserPrincipal, TenantPrincipal]


class MCPSameIdpMismatchError(Exception):
    """PRM ``authorization_servers`` does not include the user's IdP issuer
    or the server's ``expected_idp_issuer``. The broker refuses to exchange
    against an unrelated IdP."""


class MCPRequiresUserIdentityError(Exception):
    """A service-key caller hit a ``per_user`` MCP server. The exchange has
    no human subject to delegate from."""


class MCPNotAuthenticatedError(Exception):
    """The caller has no persisted IdP refresh token. They logged in via a
    non-OIDC method (local password) or their session was revoked."""


class MCPBrokerConfigurationError(Exception):
    """Operator misconfiguration — tenant federation_config is missing
    ``idp_kind`` or the per-tenant service-account credentials. Surfaces
    as 500 to keep the caller honest."""


# ---------------------------------------------------------------------------
# Internal cache for PRM (.well-known/oauth-protected-resource) documents
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PrmDocument:
    """Subset of RFC 9728 fields the broker actually uses."""

    resource: str
    authorization_servers: tuple[str, ...]


_PRM_CACHE: dict[str, _PrmDocument] = {}


async def _discover_prm(mcp_http_url: str) -> _PrmDocument:
    """Fetch and cache the MCP server's RFC 9728 metadata document.

    Looks at ``{origin}/.well-known/oauth-protected-resource``. Cached
    per origin for process lifetime; cache is cleared by restart. A
    future enhancement is to also consume ``WWW-Authenticate:
    Bearer resource_metadata=...`` from a 401 response.
    """
    parsed = urlsplit(mcp_http_url)
    if not parsed.scheme or not parsed.netloc:
        raise MCPBrokerConfigurationError(
            f"MCP server http_url is not absolute: {mcp_http_url!r}"
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    cached = _PRM_CACHE.get(origin)
    if cached is not None:
        return cached

    url = f"{origin}/.well-known/oauth-protected-resource"
    doc: dict[str, Any]
    async with aiohttp.ClientSession() as http:
        async with http.get(url) as resp:
            if resp.status != 200:
                raise MCPBrokerConfigurationError(
                    f"PRM discovery failed for {origin}: HTTP {resp.status}"
                )
            doc = await resp.json(content_type=None) or {}

    auth_servers_raw: Any = doc.get("authorization_servers")
    if not isinstance(auth_servers_raw, list) or not auth_servers_raw:
        raise MCPBrokerConfigurationError(
            f"PRM at {url} does not list any authorization_servers"
        )
    auth_servers = cast("list[Any]", auth_servers_raw)

    prm = _PrmDocument(
        resource=str(doc.get("resource", mcp_http_url)),
        authorization_servers=tuple(str(s) for s in auth_servers),
    )
    _PRM_CACHE[origin] = prm
    return prm


def reset_prm_cache() -> None:
    """Tests call this between cases. Production never does."""
    _PRM_CACHE.clear()


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------


CACHE_SAFETY_MARGIN_SECONDS = 60


class MCPTokenBroker:
    """Lazy two-tier cache + RFC 8693 / OBO exchange dispatcher."""

    def __init__(
        self,
        *,
        session: "AsyncSession",
        encryption_service: "EncryptionService",
        audit_service: "AuditService",
        oidc_token_store: "OidcTokenStore",
    ) -> None:
        self._session = session
        self._encryption = encryption_service
        self._audit = audit_service
        self._oidc_token_store = oidc_token_store

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

        cached_token = await self._cache_lookup(
            mcp_server_id=mcp_server.id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        if cached_token is not None:
            return cached_token

        # Cache miss: discover + exchange + persist
        prm = await _discover_prm(mcp_server.http_url)
        idp_issuer = self._enforce_same_idp_gate(
            mcp_server=mcp_server,
            prm=prm,
            principal=principal,
            tenant_federation_config=tenant_federation_config,
        )

        # Resolve the audience/scope override with the tenant-wide default
        # as a fallback. Per-server override > tenant default > strategy default
        # (Keycloak uses ``audience`` from PRM; Entra requires an explicit scope
        # and will error if both are absent).
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
        idp_kind, token_endpoint, client_id, client_secret = (
            self._resolve_strategy_inputs(
                idp_issuer=idp_issuer,
                tenant_federation_config=tenant_federation_config,
            )
        )

        try:
            if isinstance(principal, UserPrincipal):
                exchanged = await self._exchange_as_user(
                    user=principal.user,
                    idp_issuer=idp_issuer,
                    idp_kind=idp_kind,
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
            await self._audit_exchange_denied(
                principal=principal,
                mcp_server=mcp_server,
                reason="exchange_failed",
                detail=str(exc),
            )
            raise

        await self._cache_persist(
            mcp_server=mcp_server,
            subject_type=subject_type,
            subject_id=subject_id,
            audience=target.audience,
            idp_issuer=idp_issuer,
            exchanged=exchanged,
        )
        await self._audit_exchange_succeeded(
            principal=principal,
            mcp_server=mcp_server,
            audience=target.audience,
            idp_issuer=idp_issuer,
            expires_at=exchanged.expires_at,
        )
        return exchanged.access_token

    async def purge_cache_for_server(self, mcp_server_id: UUID) -> int:
        """Delete every cached exchanged token for a server.

        Called when the server's ``auth_scope``, ``expected_idp_issuer``,
        or ``http_url`` changes — the cached audience is no longer
        guaranteed to match.
        """
        result = await self._session.execute(
            sa.delete(MCPExchangedTokens).where(
                MCPExchangedTokens.mcp_server_id == mcp_server_id
            )
        )
        return result.rowcount or 0

    async def purge_cache_for_user(self, user_id: UUID) -> int:
        """Drop cached tokens for a user (logout / revocation)."""
        result = await self._session.execute(
            sa.delete(MCPExchangedTokens).where(
                MCPExchangedTokens.subject_type == "user",
                MCPExchangedTokens.subject_id == user_id,
            )
        )
        return result.rowcount or 0

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
            # Even a UserPrincipal can drive per_tenant — the user is the
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
    # Same-IdP gate (PRM + expected_idp_issuer)
    # ------------------------------------------------------------------

    def _enforce_same_idp_gate(
        self,
        *,
        mcp_server: "MCPServer",
        prm: _PrmDocument,
        principal: Principal,
        tenant_federation_config: dict[str, Any],
    ) -> str:
        """Return the issuer the broker will hit; raise on mismatch.

        Resolution order for the expected issuer:

        1. ``mcp_server.expected_idp_issuer`` — per-server override for the
           rare cross-IdP case (operator explicitly federates one MCP
           server to a different IdP than the tenant default).
        2. ``tenant.federation_config.issuer`` — the canonical tenant IdP
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
        # without a trailing slash — normalize both sides for compare.
        normalized_expected = expected.rstrip("/")
        normalized_servers = {s.rstrip("/") for s in prm.authorization_servers}
        if normalized_expected not in normalized_servers:
            raise MCPSameIdpMismatchError(
                f"MCP server PRM lists authorization_servers={prm.authorization_servers!r} "
                f"but server is configured for issuer {expected!r}"
            )
        return expected

    # ------------------------------------------------------------------
    # Strategy input resolution
    # ------------------------------------------------------------------

    def _resolve_strategy_inputs(
        self,
        *,
        idp_issuer: str,
        tenant_federation_config: dict[str, Any],
    ) -> tuple[IdpKind, str, str, Optional[str]]:
        """Translate tenant federation_config into (idp_kind, token_endpoint,
        client_id, client_secret).

        token_endpoint is derived from ``token_endpoint`` if present, else
        from ``{idp_issuer}/protocol/openid-connect/token`` (Keycloak
        convention). Operators with non-Keycloak IdPs must set it.
        """
        idp_kind_raw = tenant_federation_config.get("idp_kind")
        if idp_kind_raw not in ("keycloak", "entra"):
            raise MCPBrokerConfigurationError(
                f"tenant.federation_config.idp_kind must be either "
                f"'keycloak' (or any RFC 8693 conformant IdP) or 'entra'; "
                f"got {idp_kind_raw!r}"
            )
        idp_kind: IdpKind = idp_kind_raw  # type: ignore[assignment]

        token_endpoint = tenant_federation_config.get("token_endpoint")
        if not token_endpoint and idp_kind == "keycloak":
            token_endpoint = f"{idp_issuer.rstrip('/')}/protocol/openid-connect/token"
        if not isinstance(token_endpoint, str) or not token_endpoint:
            raise MCPBrokerConfigurationError(
                "tenant.federation_config.token_endpoint required for "
                f"idp_kind={idp_kind}; not present"
            )

        client_id = tenant_federation_config.get("client_id")
        client_secret = tenant_federation_config.get("client_secret")
        if not isinstance(client_id, str) or not client_id:
            raise MCPBrokerConfigurationError(
                "tenant.federation_config.client_id required for the broker"
            )

        return (
            idp_kind,
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
        idp_kind: IdpKind,
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
            refreshed = await self._oidc_token_store.refresh_idp_token(
                user=user,
                idp_issuer=idp_issuer,
                token_endpoint=token_endpoint,
                client_id=client_id,
                client_secret=client_secret,
            )
            subject_token = refreshed.access_token
            if not subject_token:
                raise MCPNotAuthenticatedError(
                    "IdP refresh returned no access_token; user must re-authenticate"
                )

        strategy = resolve_strategy(idp_kind)
        return await strategy.exchange(
            subject_access_token=subject_token,
            target=target,
            token_endpoint=token_endpoint,
            client_id=client_id,
            client_secret=client_secret,
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
                    MCPExchangedTokens.expires_at > safety_cutoff,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._encryption.decrypt(row.token_ciphertext)

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
        values = {
            "mcp_server_id": mcp_server.id,
            "tenant_id": mcp_server.tenant_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "token_ciphertext": ciphertext,
            "expires_at": exchanged.expires_at,
            "issued_at": exchanged.issued_at,
            "audience": audience,
            "idp_issuer": idp_issuer,
        }
        insert_stmt = sa.dialects.postgresql.insert(MCPExchangedTokens).values(**values)
        await self._session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="uq_mcp_exchanged_tokens_server_subject",
                set_={
                    "token_ciphertext": insert_stmt.excluded.token_ciphertext,
                    "expires_at": insert_stmt.excluded.expires_at,
                    "issued_at": insert_stmt.excluded.issued_at,
                    "audience": insert_stmt.excluded.audience,
                    "idp_issuer": insert_stmt.excluded.idp_issuer,
                    "updated_at": sa.func.now(),
                },
            )
        )

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
