"""Public OIDC authentication endpoints for tenant-based federation."""

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, Protocol, cast
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from typing_extensions import NotRequired, TypedDict

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.authentication.oidc.authorization import build_authorization_request
from eneo.authentication.oidc.errors import OidcSignInError
from eneo.authentication.oidc.profile import (
    OidcProfile,
    OidcProviderError,
    load_profile,
)
from eneo.authentication.oidc.transaction import (
    STORE_TIMEOUT_SECONDS,
    OidcChannel,
    OidcTransaction,
    save_transaction,
    take_transaction,
)
from eneo.authentication.oidc.verification import CallbackResponse, verify_response
from eneo.main.config import (
    Settings,
    get_settings,
    has_env_oidc_client,
    validate_redirect_uri,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import FederatedLoginDenied
from eneo.main.logging import get_logger
from eneo.main.models import GeneralError
from eneo.main.request_context import ensure_correlation_id, set_request_context
from eneo.observability.debug_toggle import is_debug_enabled
from eneo.observability.redaction import sanitize_payload
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.settings.credential_resolver import CredentialResolver
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.identity_binding_repo import IdentityConflictError

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)


class OIDCClaimsMapping(TypedDict):
    email: str
    subject: NotRequired[str]


class FederationConfig(TypedDict):
    client_id: str
    client_secret: str
    provider: NotRequired[str]
    discovery_endpoint: NotRequired[str]
    authorization_endpoint: NotRequired[str]
    token_endpoint: NotRequired[str]
    jwks_uri: NotRequired[str]
    token_endpoint_auth_method: NotRequired[str]
    token_endpoint_auth_methods_supported: NotRequired[list[str]]
    scopes: NotRequired[list[str]]
    claims_mapping: NotRequired[OIDCClaimsMapping]
    allowed_domains: NotRequired[list[str]]


class OIDCStatePayload(TypedDict):
    tenant_id: str
    tenant_slug: str
    frontend_state: str
    # Names the server-side transaction that holds the nonce and PKCE verifier.
    transaction_id: str
    correlation_id: str
    exp: int
    iat: int


class AccessTokenResponse(TypedDict):
    access_token: str
    frontend_state: str


class _FederationConfigResolver(Protocol):
    def get_federation_config(self) -> FederationConfig: ...


async def _log_oidc_debug(
    *,
    redis_client: Any,
    correlation_id: str | None,
    event: str,
    **payload: Any,
) -> None:
    if not correlation_id:
        correlation_id = "unknown"

    try:
        async with asyncio.timeout(STORE_TIMEOUT_SECONDS):
            enabled = await is_debug_enabled(redis_client)
    except TimeoutError:
        # Diagnostics are optional: a store that stops answering skips them
        # rather than holding up the sign-in.
        return
    if not enabled:
        return

    sanitized = sanitize_payload(payload)
    set_request_context(correlation_id=correlation_id)

    logger.debug(
        f"[OIDC DEBUG] {event}",
        extra={
            "event": event,
            "correlation_id": correlation_id,
            **sanitized,
        },
    )


def _transaction_store(container: Container) -> Redis | None:
    """The sign-in transaction store; None when it cannot be built, which
    refuses the sign-in rather than continuing without it."""
    try:
        return container.redis_client()
    except Exception as exc:
        logger.error(
            "oidc_transaction_store_failed",
            extra={"operation": "connect", "error_type": type(exc).__name__},
        )
        return None


async def _load_profile(
    federation_config: FederationConfig, settings: Settings, correlation_id: str
) -> OidcProfile:
    try:
        # Discovery is cached as long as the provider's keys.
        return await load_profile(
            federation_config,
            discovery_ttl_seconds=settings.oidc_jwks_cache_ttl_seconds,
        )
    except OidcProviderError as exc:
        logger.error(
            "OIDC provider configuration is unusable",
            extra={"reason": str(exc), "correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
            headers={"X-Correlation-ID": correlation_id},
        ) from exc


def _changed_during_sign_in(
    transaction: OidcTransaction, tenant: TenantInDB, settings: Settings
) -> bool:
    """The tenant's config changed after this sign-in started, recently enough
    that a redirect URI it no longer lists is still accepted."""
    grace_period = min(
        settings.oidc_redirect_grace_period_seconds, settings.oidc_state_ttl_seconds
    )
    current_version = tenant.updated_at.isoformat() if tenant.updated_at else None
    started_version = transaction.config_version
    if (
        grace_period <= 0
        or not current_version
        or not started_version
        or current_version == started_version
    ):
        return False
    now = datetime.now(timezone.utc)
    updated_at = tenant.updated_at or tenant.created_at
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    try:
        started_at = datetime.fromisoformat(started_version)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        changed_after_start = updated_at > started_at
    except ValueError:
        changed_after_start = True
    return (
        max(0, now.timestamp() - transaction.issued_at) <= grace_period
        and (now - updated_at).total_seconds() <= grace_period
        and changed_after_start
    )


def _require_registered_redirect_uri(
    transaction: OidcTransaction,
    tenant: TenantInDB,
    credential_resolver: CredentialResolver,
    settings: Settings,
    correlation_id: str,
) -> None:
    """Refuse the callback unless the tenant still registers the sign-in's
    redirect URI.

    Defence in depth against a forged state (if the JWT secret leaks), a
    public origin changed during the sign-in, and cross-tenant confusion.
    """
    log_context = {
        "tenant_id": transaction.tenant_id,
        "tenant_slug": transaction.tenant_slug,
        "correlation_id": correlation_id,
    }
    try:
        expected_redirect_uri = credential_resolver.get_redirect_uri()
    except ValueError as e:
        logger.error(
            "Failed to resolve expected redirect_uri for validation",
            extra={**log_context, "error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to validate redirect_uri configuration",
            headers={"X-Correlation-ID": correlation_id},
        )
    valid_redirect_uris = set(credential_resolver.get_valid_redirect_uris())
    try:
        redirect_uri = validate_redirect_uri(transaction.redirect_uri) or ""
    except ValueError:
        logger.error(
            "State redirect_uri failed validation",
            extra={**log_context, "state_redirect_uri": transaction.redirect_uri},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Redirect URI mismatch - authentication flow invalid. "
                "Please try logging in again."
            ),
            headers={"X-Correlation-ID": correlation_id},
        )

    if redirect_uri in valid_redirect_uris:
        if redirect_uri != expected_redirect_uri:
            logger.info(
                "Accepted non-canonical configured redirect_uri during callback",
                extra={
                    **log_context,
                    "state_redirect_uri": redirect_uri,
                    "expected_redirect_uri": expected_redirect_uri,
                },
            )
        return
    if not settings.strict_oidc_redirect_validation:
        return
    if _changed_during_sign_in(transaction, tenant, settings):
        logger.warning(
            "Accepting redirect_uri from state due to recent config change",
            extra={
                **log_context,
                "state_redirect_uri": redirect_uri,
                "expected_redirect_uri": expected_redirect_uri,
            },
        )
        return
    logger.error(
        "Redirect URI mismatch between state and tenant configuration",
        extra={
            **log_context,
            "state_redirect_uri": redirect_uri,
            "expected_redirect_uri": expected_redirect_uri,
            "allowed_redirect_uri_count": len(valid_redirect_uris),
            "config_version_state": transaction.config_version,
        },
    )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Redirect URI mismatch - authentication flow invalid. "
            "This may occur if tenant configuration changed during login. "
            "Please try logging in again. If this persists, contact your administrator."
        ),
        headers={"X-Correlation-ID": correlation_id},
    )


class TenantInfo(BaseModel):
    """Public tenant information for selector grid."""

    slug: str
    name: str
    display_name: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "slug": "stockholm",
                "name": "Stockholm Municipality",
                "display_name": "Stockholm",
            }
        }
    }


class TenantListResponse(BaseModel):
    """List of tenants for selector."""

    tenants: list[TenantInfo]

    model_config = {
        "json_schema_extra": {
            "example": {
                "tenants": [
                    {
                        "slug": "stockholm",
                        "name": "Stockholm Municipality",
                        "display_name": "Stockholm",
                    },
                    {
                        "slug": "goteborg",
                        "name": "Gothenburg Municipality",
                        "display_name": "Gothenburg",
                    },
                ]
            }
        }
    }


class InitiateAuthResponse(BaseModel):
    """Response with IdP authorization URL."""

    authorization_url: str
    state: str  # Server-signed state (includes tenant context)

    model_config = {
        "json_schema_extra": {
            "example": {
                "authorization_url": "https://idp.example.com/authorize?client_id=abc123&...",
                "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            }
        }
    }


class CallbackRequest(BaseModel):
    """OIDC callback with authorization code."""

    code: str
    state: str
    # Ignored: the PKCE verifier never leaves the server.
    code_verifier: Optional[str] = None
    # The authorization response's RFC 9207 issuer, when the provider sends it.
    iss: Optional[str] = None
    binding_verifier: Optional[str] = Field(
        default=None,
        min_length=43,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
        description=(
            "The secret whose S256 hash was sent as binding_challenge at "
            "initiate. Required for a bound sign-in and refused for an unbound "
            "one."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "code": "authorization_code_from_idp",
                "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            }
        }
    }


class FederationStatusResponse(BaseModel):
    """Federation configuration status for login page."""

    has_single_tenant_federation: bool
    has_multi_tenant_federation: bool
    has_global_oidc_config: bool
    tenant_count: int

    model_config = {
        "json_schema_extra": {
            "example": {
                "has_single_tenant_federation": True,
                "has_multi_tenant_federation": False,
                "has_global_oidc_config": False,
                "tenant_count": 1,
            }
        }
    }


def _has_federation_config(config: dict[str, Any]) -> bool:
    return bool(config.get("client_id") and config.get("discovery_endpoint"))


@router.get(
    "/federation-status",
    response_model=FederationStatusResponse,
    summary="Check federation configuration status",
    description=(
        "Returns federation availability status for the system. "
        "Used by login page to determine which authentication method to show. "
        "No authentication required (public endpoint)."
    ),
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Federation discovery and login handshake precede an Eneo session; AuthService validates exchanged credentials and state.",
)
async def get_federation_status(
    container: Annotated[Container, Depends(get_container())],
) -> FederationStatusResponse:
    """
    Determine federation configuration status.

    This endpoint helps the login page decide which authentication UI to show:
    - Single-tenant API federation: Exactly 1 active tenant with API-configured federation
    - Multi-tenant federation: Federation per tenant is enabled
    - Global OIDC: Environment-based OIDC (federation_enabled=false)
    - No federation: Fall back to username/password

    Returns:
        FederationStatusResponse with:
        - has_single_tenant_federation: True if exactly 1 active tenant with API federation config
        - has_multi_tenant_federation: True if federation_enabled with >1 tenants
        - has_global_oidc_config: True if federation_enabled=false and OIDC_* env vars are configured
        - tenant_count: Number of active tenants
    """
    settings = get_settings()
    tenant_repo = container.tenant_repo()

    # Get all active tenants
    tenants = await tenant_repo.get_all_active()
    tenant_count = len(tenants)

    # The OIDC_* settings sign people in only in env mode; with
    # FEDERATION_ENABLED they are ignored and never a fallback.
    has_global_oidc = not settings.federation_enabled and has_env_oidc_client(settings)

    # Multi-tenant mode: federation per tenant is enabled with multiple tenants
    if settings.federation_enabled and tenant_count > 1:
        return FederationStatusResponse(
            has_single_tenant_federation=False,
            has_multi_tenant_federation=True,
            has_global_oidc_config=has_global_oidc,
            tenant_count=tenant_count,
        )

    # Single-tenant federation detection (API-configured federation in database):
    # - Exactly 1 active tenant
    # - Has API-configured federation (non-empty federation_config JSONB)
    # - Federation config has required fields
    # - Only applies when federation_enabled=true
    has_single_federation = False
    if settings.federation_enabled and tenant_count == 1:
        tenant = tenants[0]
        if _has_federation_config(tenant.federation_config):
            has_single_federation = True
            logger.info(
                "Single-tenant API federation detected",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "provider": tenant.federation_config.get("provider", "unknown"),
                },
            )

    return FederationStatusResponse(
        has_single_tenant_federation=has_single_federation,
        has_multi_tenant_federation=False,
        has_global_oidc_config=has_global_oidc,
        tenant_count=tenant_count,
    )


@router.get(
    "/tenants",
    response_model=TenantListResponse,
    summary="List tenants for selector",
    description=(
        "Public endpoint returning active tenants with slugs for the tenant selector. "
        "With federation enabled, only tenants with an IdP configuration are returned. "
        "No authentication required."
    ),
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Federation discovery and login handshake precede an Eneo session; AuthService validates exchanged credentials and state.",
)
async def list_tenants(
    container: Annotated[Container, Depends(get_container())],
) -> TenantListResponse:
    """
    Get the active tenants eligible for the selector grid.

    Returns only tenants that have:
    - Active status (not deleted)
    - Slug configured (required for federation routing)
    - Client ID and discovery endpoint when federation is enabled

    Returns:
        TenantListResponse with slug, name, display_name for each tenant
    """
    tenant_repo = container.tenant_repo()
    federation_enabled = get_settings().federation_enabled

    # Get all active tenants
    tenants = await tenant_repo.get_all_active()

    # Keep only public selector fields, never the federation credentials.
    tenant_list = [
        TenantInfo(
            slug=tenant.slug,
            name=tenant.name,
            display_name=tenant.display_name or tenant.name,
        )
        for tenant in tenants
        if tenant.slug
        and (not federation_enabled or _has_federation_config(tenant.federation_config))
    ]

    logger.info(f"Listed {len(tenant_list)} tenants for selector")

    return TenantListResponse(tenants=tenant_list)


@router.get(
    "/initiate",
    response_model=InitiateAuthResponse,
    summary="Initiate OIDC authentication",
    description=(
        "Get authorization URL for tenant's identity provider. "
        "No authentication required. "
        "Returns URL to redirect user to IdP login page."
    ),
    responses={
        400: {"description": "Tenant selection or redirect URI is invalid"},
        403: {"description": "Tenant is not active"},
        404: {"description": "Tenant not found or not configured"},
        500: {"description": "Federation or redirect configuration missing"},
        503: {"description": "Sign-in store unavailable (oidc_login_unavailable)"},
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Federation discovery and login handshake precede an Eneo session; AuthService validates exchanged credentials and state.",
)
async def initiate_auth(
    response: Response,
    container: Annotated[Container, Depends(get_container())],
    tenant: Annotated[
        Optional[str],
        Query(
            description="Tenant slug (required for multi-tenant, optional for single-tenant)",
        ),
    ] = None,
    state: Annotated[
        Optional[str], Query(description="Optional frontend-generated CSRF state")
    ] = None,
    redirect_uri_param: Annotated[
        Optional[str],
        Query(
            alias="redirect_uri",
            description=(
                "Optional redirect URI override. Must exactly match a configured "
                "redirect URI for the tenant."
            ),
        ),
    ] = None,
    binding_challenge: Annotated[
        Optional[str],
        Query(
            pattern=r"^[A-Za-z0-9_-]{43}$",
            description=(
                "Optional base64url S256 hash of a secret the client keeps "
                "(RFC 7636 4.2). The callback then needs that secret as "
                "binding_verifier. Create the secret from at least 32 random "
                "bytes."
            ),
        ),
    ] = None,
) -> InitiateAuthResponse:
    """Get the authorization URL for the tenant's identity provider."""
    return await initiate_federated_sign_in(
        response,
        container,
        tenant=tenant,
        state=state,
        redirect_uri_param=redirect_uri_param,
        channel="api",
        binding_challenge=binding_challenge,
    )


async def initiate_federated_sign_in(
    response: Response,
    container: Container,
    *,
    tenant: str | None,
    state: str | None,
    redirect_uri_param: str | None,
    channel: OidcChannel,
    binding_challenge: str | None,
) -> InitiateAuthResponse:
    """
    Start a sign-in at the tenant's identity provider: the shared initiation core.

    This function:
    1. Looks up tenant by slug (or uses first active tenant in single-tenant mode)
    2. Resolves tenant's federation config (tenant-specific or global)
    3. Computes redirect_uri server-side from canonical_public_origin
    4. Generates server-signed state (includes tenant context for callback)
    5. Builds authorization URL with IdP parameters
    6. Returns URL for frontend to redirect user

    Args:
        tenant: Tenant slug (required for multi-tenant, optional for single-tenant mode)
        state: Optional frontend-generated state for CSRF protection
        container: Dependency injection container

    Returns:
        InitiateAuthResponse with authorization_url and signed state

    Raises:
        HTTPException 400: Tenant parameter required in multi-tenant mode
        HTTPException 404: Tenant not found or no slug configured
        HTTPException 500: No IdP configured for tenant or no public origin
        OidcLoginUnavailableError (503): The transaction store is unavailable
    """
    tenant_repo = container.tenant_repo()
    settings = get_settings()

    # Handle single-tenant mode (no tenant slug needed)
    if tenant is None:
        # Get all active tenants to determine if single-tenant flow is applicable
        tenants = await tenant_repo.get_all_active()

        if not tenants:
            logger.error("No active tenant found")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No active tenant found",
            )

        # Handle multi-tenant mode with federation_enabled=true
        if settings.federation_enabled:
            # Allow single-tenant flow if exactly 1 active tenant exists
            if len(tenants) != 1:
                logger.error(
                    "Tenant parameter missing in multi-tenant mode with multiple tenants",
                    extra={
                        "federation_enabled": True,
                        "tenant_count": len(tenants),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tenant parameter required when multiple tenants exist",
                )
            # Single tenant exists: allow auto-selection
            tenant_obj = tenants[0]
            logger.info(
                f"Single-tenant federation: auto-selected tenant {tenant_obj.name}",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "tenant_name": tenant_obj.name,
                    "federation_enabled": True,
                },
            )
        else:
            # Global OIDC mode (federation_enabled=false):
            # Use first active tenant with global OIDC_* env vars
            # All tenants share the same IdP configuration (no per-tenant routing)
            tenant_obj = tenants[0]
            logger.info(
                f"Global OIDC mode: using tenant {tenant_obj.name} with shared OIDC config",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "tenant_name": tenant_obj.name,
                    "tenant_count": len(tenants),
                    "federation_enabled": False,
                },
            )
    else:
        # Multi-tenant mode: lookup tenant by slug
        tenant_obj = await tenant_repo.get_by_slug(tenant)
        if not tenant_obj:
            logger.error(
                f"Tenant not found by slug: {tenant}",
                extra={"tenant_slug": tenant},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant '{tenant}' not found or not configured for federation",
            )

    if tenant_obj.state != TenantState.ACTIVE:
        logger.error(
            "Inactive tenant attempted authentication",
            extra={
                "tenant_id": str(tenant_obj.id),
                "tenant_slug": tenant_obj.slug,
                "state": tenant_obj.state,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant}' is not active. Contact your administrator.",
        )

    set_request_context(tenant_slug=tenant_obj.slug or tenant_obj.name)

    # Resolve federation config (tenant-specific or global)
    # Create CredentialResolver with tenant, settings, and encryption_service
    encryption_service = container.encryption_service()
    credential_resolver = CredentialResolver(
        tenant=tenant_obj,
        settings=settings,
        encryption_service=encryption_service,
    )

    try:
        federation_config = cast(
            _FederationConfigResolver, credential_resolver
        ).get_federation_config()
    except ValueError as e:
        logger.error(
            "No federation config for tenant",
            extra={
                "tenant_id": str(tenant_obj.id),
                "tenant_slug": tenant,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No identity provider configured for tenant '{tenant}'",
        )

    correlation_id = ensure_correlation_id()
    # The id the callback restores from the state; the trace middleware only
    # sets this header when a span is active.
    response.headers["X-Correlation-ID"] = correlation_id

    # Resolve redirect_uri server-side
    try:
        canonical_redirect_uri = credential_resolver.get_redirect_uri()
    except ValueError as e:
        logger.error(
            "Failed to resolve redirect_uri for tenant",
            extra={
                "tenant_id": str(tenant_obj.id),
                "tenant_slug": tenant,
                "error": str(e),
                "correlation_id": correlation_id,
            },
        )
        raise HTTPException(
            500,
            f"No public origin configured for tenant '{tenant}'. "
            "Contact administrator to configure canonical_public_origin.",
        )

    valid_redirect_uris = credential_resolver.get_valid_redirect_uris()

    if redirect_uri_param is not None:
        try:
            redirect_uri = validate_redirect_uri(redirect_uri_param)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

        if redirect_uri not in valid_redirect_uris:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The provided redirect_uri is not registered for this tenant. "
                    "Configure it via the tenant federation settings and register it with your IdP."
                ),
            )

        if redirect_uri != canonical_redirect_uri:
            logger.info(
                "OIDC initiate using non-canonical redirect_uri",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "chosen_redirect_uri": redirect_uri,
                    "canonical_redirect_uri": canonical_redirect_uri,
                    "correlation_id": correlation_id,
                },
            )
    else:
        redirect_uri = canonical_redirect_uri

    effective_updated_at = tenant_obj.updated_at or tenant_obj.created_at
    tenant_config_version = (
        effective_updated_at.isoformat() if effective_updated_at else None
    )
    profile = await _load_profile(federation_config, settings, correlation_id)
    transaction = OidcTransaction.start(
        "login",
        channel=channel,
        binding_challenge=binding_challenge,
        redirect_uri=redirect_uri,
        tenant_id=str(tenant_obj.id),
        tenant_slug=tenant_obj.slug or tenant_obj.name,
        config_version=tenant_config_version,
        issuer=profile.issuer,
        iss_parameter_supported=profile.iss_parameter_supported,
    )
    state_payload: OIDCStatePayload = {
        "tenant_id": transaction.tenant_id,
        "tenant_slug": transaction.tenant_slug,
        "frontend_state": state or "",
        "transaction_id": transaction.id,
        "correlation_id": correlation_id,
        "exp": transaction.issued_at + settings.oidc_state_ttl_seconds,
        "iat": transaction.issued_at,
    }
    signed_state = pyjwt.encode(
        cast(dict[str, Any], state_payload), settings.jwt_secret, algorithm="HS256"
    )
    redis_client = _transaction_store(container)
    await save_transaction(
        redis_client, transaction, ttl_seconds=settings.oidc_state_ttl_seconds
    )
    authorization_url = build_authorization_request(
        profile, transaction, state=signed_state
    )

    await _log_oidc_debug(
        redis_client=redis_client,
        correlation_id=correlation_id,
        event="initiate.authorization_ready",
        tenant_slug=transaction.tenant_slug,
        authorization_endpoint=profile.authorization_endpoint,
        redirect_uri=redirect_uri,
    )

    logger.info(
        f"Authentication initiated for tenant {tenant_obj.name}",
        extra={
            "tenant_id": str(tenant_obj.id),
            "tenant_slug": transaction.tenant_slug,
            "provider": federation_config.get("provider"),
            "redirect_uri": redirect_uri,  # Log server-computed value
            "correlation_id": correlation_id,
        },
    )

    return InitiateAuthResponse(
        authorization_url=authorization_url,
        state=signed_state,
    )


@router.post(
    "/callback",
    response_model=AccessTokenResponse,
    summary="OIDC callback handler",
    description=(
        "Handle OIDC callback, validate token, lookup user. "
        "No authentication required (public endpoint). "
        "Returns JWT token for authenticated user."
    ),
    responses={
        400: {
            "description": (
                "Invalid or expired state, or a binding_verifier that does not "
                "match the sign-in (oidc_transaction_invalid)"
            ),
            "model": GeneralError,
        },
        401: {"description": "Token validation failed", "model": GeneralError},
        403: {
            "description": (
                "Domain not allowed, inactive tenant or user missing; or "
                "`identity_conflict` (9082): the account is bound to another "
                "sign-in identity"
            ),
            "model": GeneralError,
        },
        404: {"description": "Tenant or user not found", "model": GeneralError},
        503: {
            "description": "Sign-in store unavailable (oidc_login_unavailable)",
            "model": GeneralError,
        },
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Federation discovery and login handshake precede an Eneo session; AuthService validates exchanged credentials and state.",
)
async def auth_callback(
    callback: CallbackRequest,
    # The session (and an account the sign-in created) commits before the
    # token leaves, so its first request is admitted.
    container: Annotated[
        Container, Depends(get_container(transaction_scope="function"))
    ],
) -> AccessTokenResponse:
    """Handle the OIDC callback after the user authenticated with the IdP."""
    signed_in = await federated_sign_in(callback, container, channel="api")
    # The token names its session, so signing out (POST /users/logout/)
    # ends every copy of it.
    return AccessTokenResponse(
        access_token=await container.browser_session_service().start(
            signed_in["access_token"]
        ),
        frontend_state=signed_in["frontend_state"],
    )


async def federated_sign_in(
    callback: CallbackRequest, container: Container, *, channel: OidcChannel
) -> AccessTokenResponse:
    """
    Verify a provider's callback and admit its user: the shared sign-in core.

    Starts no session. Each route that hands the token out decides which
    session it gets (``BrowserSessionService.start``).

    This function:
    1. Validates signed state (JWT with tenant context)
    2. Takes the single-use sign-in transaction the state names, if this
       channel and binding verifier are the ones that started it
    3. Exchanges the code with the PKCE verifier and verifies the ID token
       (signature, issuer, audience, freshness, nonce)
    4. Validates email domain against tenant's allowed_domains
    5. Resolves an active tenant member or provisions under the shared JIT policy
    6. Issues Eneo JWT token

    Raises:
        HTTPException 400: Invalid state or code
        OidcTransactionInvalidError (400): No live transaction for the state
        HTTPException 401: The verified token carries no usable email
        OidcResponseNotVerifiedError (401): The provider's response failed a check
        HTTPException 403: Email domain not allowed for tenant or user not found
        IdentityConflictError (403): The identity cannot be bound to the account
            its email names
        OidcLoginUnavailableError (503): The transaction store is unavailable
    """
    settings = get_settings()

    # Validate and decode state
    # Note: pyjwt.decode() automatically validates 'exp' claim and raises ExpiredSignatureError
    try:
        state_payload = cast(
            OIDCStatePayload,
            pyjwt.decode(callback.state, settings.jwt_secret, algorithms=["HS256"]),
        )
    except pyjwt.ExpiredSignatureError:
        # Note: correlation_id not available yet (state decode failed)
        logger.error(
            "State token expired",
            extra={"detail": "Authorization session expired (10 minute timeout)"},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization session expired. Please try logging in again.",
        )
    except pyjwt.PyJWTError as e:
        # Note: correlation_id not available yet (state decode failed)
        logger.error(
            "Invalid state parameter",
            extra={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter",
        )

    # A state issued before sign-in transactions existed names none.
    transaction_id = state_payload.get("transaction_id")
    if not transaction_id:
        logger.error(
            "State token names no sign-in transaction",
            extra={"correlation_id": state_payload.get("correlation_id")},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter",
        )

    tenant_id = UUID(state_payload["tenant_id"])
    tenant_slug = state_payload["tenant_slug"]
    # Extract correlation ID from state (flows from initiate endpoint)
    correlation_id = state_payload["correlation_id"] or secrets.token_hex(8)
    set_request_context(correlation_id=correlation_id, tenant_slug=tenant_slug)
    redis_client = _transaction_store(container)

    await _log_oidc_debug(
        redis_client=redis_client,
        correlation_id=correlation_id,
        event="callback.state_decoded",
        tenant_slug=tenant_slug,
    )

    # Global exception handler to ensure correlation_id is always included in responses
    try:
        # Single use, and only for the client that started the sign-in.
        transaction = await take_transaction(
            redis_client,
            transaction_id,
            channel=channel,
            binding_verifier=callback.binding_verifier,
        )
        if transaction.tenant_id != str(tenant_id) or (
            transaction.tenant_slug.lower() != (tenant_slug or "").lower()
        ):
            logger.error(
                "OIDC state tenant mismatch detected",
                extra={
                    "expected_tenant_id": transaction.tenant_id,
                    "supplied_tenant_id": str(tenant_id),
                    "expected_tenant_slug": transaction.tenant_slug,
                    "supplied_tenant_slug": tenant_slug,
                    "correlation_id": correlation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Authorization state mismatch detected. "
                    "Please restart the sign-in flow."
                ),
                headers={"X-Correlation-ID": correlation_id},
            )

        # Get tenant and federation config
        tenant_repo = container.tenant_repo()
        tenant_obj = await tenant_repo.get(tenant_id)
        if not tenant_obj:
            logger.error(
                "Tenant not found",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
                headers={"X-Correlation-ID": correlation_id},
            )

        set_request_context(tenant_slug=tenant_obj.slug or tenant_slug)

        if tenant_obj.state != TenantState.ACTIVE:
            logger.error(
                "Inactive tenant attempted callback",
                extra={
                    "tenant_id": str(tenant_id),
                    "tenant_slug": tenant_slug,
                    "state": tenant_obj.state,
                    "correlation_id": correlation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant is not active. Contact your administrator.",
                headers={"X-Correlation-ID": correlation_id},
            )

        credential_resolver = CredentialResolver(
            tenant=tenant_obj,
            settings=settings,
            encryption_service=container.encryption_service(),
        )
        federation_config = cast(
            _FederationConfigResolver, credential_resolver
        ).get_federation_config()
        _require_registered_redirect_uri(
            transaction, tenant_obj, credential_resolver, settings, correlation_id
        )
        profile = await _load_profile(federation_config, settings, correlation_id)
        verified = await verify_response(
            profile,
            transaction,
            CallbackResponse(code=callback.code, iss=callback.iss),
            jwks_ttl_seconds=settings.oidc_jwks_cache_ttl_seconds,
            correlation_id=correlation_id,
        )

        try:
            identity = verified.identity()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"X-Correlation-ID": correlation_id},
            ) from exc

        email = identity.email
        await _log_oidc_debug(
            redis_client=redis_client,
            correlation_id=correlation_id,
            event="callback.email_extracted",
            email=email,
            email_claim=profile.email_claim,
        )
        try:
            user, created = await container.user_service().resolve_federated_user(
                identity=identity,
                tenant_id=tenant_id,
                allowed_domains=federation_config.get("allowed_domains") or [],
                correlation_id=correlation_id,
            )
        except IdentityConflictError as exc:
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.identity_conflict",
                tenant_slug=tenant_slug,
                reason=exc.reason,
            )
            # Typed: 403 with its code, for the login pages to explain.
            raise
        except FederatedLoginDenied as exc:
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.user_denied",
                tenant_slug=tenant_slug,
                reason=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
                headers={"X-Correlation-ID": correlation_id},
            ) from exc

        # Only an admitted sign-in puts its email in the request's log context,
        # so a refused one (an identity conflict, a denied account) logs none,
        # like the provider-response refusals before it.
        set_request_context(user_email=email)

        if created:
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.jit_provisioning",
                tenant_slug=tenant_slug,
                email=email,
            )

        # Create JWT token for existing user
        access_token_response = container.auth_service().create_access_token_for_user(
            user
        )

        logger.info(
            f"Federated login successful for {email} on tenant {tenant_slug}",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_slug": tenant_slug,
                "user_id": str(user.id),
                "email": email,
                "correlation_id": correlation_id,
            },
        )

        await _log_oidc_debug(
            redis_client=redis_client,
            correlation_id=correlation_id,
            event="callback.success",
            tenant_slug=tenant_slug,
            email=email,
            user_id=str(user.id),
        )

        return AccessTokenResponse(
            access_token=access_token_response,
            frontend_state=state_payload["frontend_state"],
        )
    except (HTTPException, OidcSignInError, IdentityConflictError):
        # Re-raise HTTP and typed sign-in refusals with correlation_id already set
        raise
    except Exception as e:
        # Catch-all for unexpected errors - ensures correlation_id is always included
        logger.error(
            "Unexpected error during OIDC callback",
            extra={
                "tenant_id": str(tenant_id),
                "error": str(e),
                "error_type": type(e).__name__,
                "correlation_id": correlation_id,
            },
        )
        await _log_oidc_debug(
            redis_client=redis_client,
            correlation_id=correlation_id,
            event="callback.unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during authentication. Please try again.",
            headers={"X-Correlation-ID": correlation_id},
        )
