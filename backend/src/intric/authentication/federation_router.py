"""Public OIDC authentication endpoints for tenant-based federation."""

import base64
import contextlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from jwt import PyJWKClient as _PyJWKClient
from pydantic import BaseModel

from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.request_context import set_request_context
from intric.observability.debug_toggle import is_debug_enabled
from intric.observability.redaction import sanitize_payload
from intric.server.dependencies.container import get_container
from intric.settings.credential_resolver import CredentialResolver
from intric.tenants.tenant import TenantState

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

JWKClient = _PyJWKClient
PyJWKClient = JWKClient  # Backwards compatibility alias for tests/monkeypatching


@contextlib.asynccontextmanager
async def _cleanup_state_cache(
    redis_client, state_key: str, *, tenant_id: UUID | None, correlation_id: str
):
    try:
        yield
    finally:
        if redis_client:
            try:
                await redis_client.delete(state_key)
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.debug(
                    "Failed to delete cached OIDC state",
                    extra={
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "state_key": state_key,
                        "error": str(exc),
                        "correlation_id": correlation_id,
                    },
                )


async def _log_oidc_debug(
    *,
    redis_client,
    correlation_id: str | None,
    event: str,
    **payload,
) -> None:
    if not correlation_id:
        correlation_id = "unknown"

    if not await is_debug_enabled(redis_client):
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


async def fetch_discovery(discovery_url: str) -> dict:
    """
    Fetch OIDC discovery document.

    Simple fetch without caching - discovery endpoints are rarely called
    and IdPs handle rate limiting themselves.

    Args:
        discovery_url: URL to OIDC discovery document

    Returns:
        dict: Discovery document JSON

    Raises:
        HTTPException 500: Failed to fetch discovery document
    """
    async with aiohttp_client().get(discovery_url) as resp:
        if resp.status != 200:
            logger.error(
                f"Failed to fetch OIDC discovery document: HTTP {resp.status}",
                extra={
                    "discovery_url": discovery_url,
                    "http_status": resp.status,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch discovery document: HTTP {resp.status}",
            )
        return await resp.json()


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
    code_verifier: Optional[str] = None  # For PKCE (future use)

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


@router.get(
    "/federation-status",
    response_model=FederationStatusResponse,
    summary="Check federation configuration status",
    description=(
        "Returns federation availability status for the system. "
        "Used by login page to determine which authentication method to show. "
        "No authentication required (public endpoint)."
    ),
)
async def get_federation_status(
    container: Container = Depends(get_container()),
) -> FederationStatusResponse:
    """
    Determine federation configuration status.

    This endpoint helps the login page decide which authentication UI to show:
    - Single-tenant API federation: Exactly 1 active tenant with API-configured federation
    - Multi-tenant federation: Federation per tenant is enabled
    - Global OIDC: Environment-based OIDC (federation_per_tenant_enabled=false)
    - No federation: Fall back to username/password

    Returns:
        FederationStatusResponse with:
        - has_single_tenant_federation: True if exactly 1 active tenant with API federation config
        - has_multi_tenant_federation: True if federation_per_tenant_enabled with >1 tenants
        - has_global_oidc_config: True if OIDC_* env vars are configured
        - tenant_count: Number of active tenants
    """
    settings = get_settings()
    tenant_repo = container.tenant_repo()

    # Get all active tenants
    tenants = await tenant_repo.get_all_active()
    tenant_count = len(tenants)

    # Check if global OIDC env vars are configured (used when federation_per_tenant_enabled=false)
    has_global_oidc = bool(
        settings.oidc_discovery_endpoint and settings.oidc_client_secret
    )

    # Multi-tenant mode: federation per tenant is enabled with multiple tenants
    if settings.federation_per_tenant_enabled and tenant_count > 1:
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
    # - Only applies when federation_per_tenant_enabled=true
    has_single_federation = False
    if settings.federation_per_tenant_enabled and tenant_count == 1:
        tenant = tenants[0]
        # Check if tenant has API-configured federation (non-empty federation_config JSONB)
        if tenant.federation_config and len(tenant.federation_config) > 0:
            # Verify it has the required fields (avoid empty dicts)
            required_fields = {"client_id", "discovery_endpoint"}
            if required_fields.issubset(tenant.federation_config.keys()):
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
        "Public endpoint returning all active tenants for the tenant selector grid. "
        "Only returns tenants with slugs configured for federation. "
        "No authentication required."
    ),
)
async def list_tenants(
    container: Container = Depends(get_container()),
) -> TenantListResponse:
    """
    Get list of all active tenants for selector grid.

    Returns only tenants that have:
    - Active status (not deleted)
    - Slug configured (required for federation routing)

    Returns:
        TenantListResponse with slug, name, display_name for each tenant
    """
    tenant_repo = container.tenant_repo()

    # Get all active tenants
    tenants = await tenant_repo.get_all_active()

    # Map to public info (only include tenants with slugs)
    tenant_list = [
        TenantInfo(
            slug=tenant.slug,
            name=tenant.name,
            display_name=tenant.display_name or tenant.name,
        )
        for tenant in tenants
        if tenant.slug  # Only include tenants with slugs configured
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
        403: {"description": "Tenant is not active"},
        404: {"description": "Tenant not found or not configured"},
        500: {"description": "Federation or redirect configuration missing"},
    },
)
async def initiate_auth(
    tenant: Optional[str] = Query(
        None,
        description="Tenant slug (required for multi-tenant, optional for single-tenant)",
    ),
    state: Optional[str] = Query(
        None, description="Optional frontend-generated CSRF state"
    ),
    container: Container = Depends(get_container()),
) -> InitiateAuthResponse:
    """
    Get authorization URL for tenant's identity provider.

    This endpoint:
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

        # Handle multi-tenant mode with federation_per_tenant_enabled=true
        if settings.federation_per_tenant_enabled:
            # Allow single-tenant flow if exactly 1 active tenant exists
            if len(tenants) != 1:
                logger.error(
                    "Tenant parameter missing in multi-tenant mode with multiple tenants",
                    extra={
                        "federation_per_tenant_enabled": True,
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
                    "federation_per_tenant_enabled": True,
                },
            )
        else:
            # Global OIDC mode (federation_per_tenant_enabled=false):
            # Use first active tenant with global OIDC_* env vars
            # All tenants share the same IdP configuration (no per-tenant routing)
            tenant_obj = tenants[0]
            logger.info(
                f"Global OIDC mode: using tenant {tenant_obj.name} with shared OIDC config",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "tenant_name": tenant_obj.name,
                    "tenant_count": len(tenants),
                    "federation_per_tenant_enabled": False,
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
        federation_config = credential_resolver.get_federation_config()
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

    # Resolve redirect_uri server-side
    try:
        redirect_uri = credential_resolver.get_redirect_uri()
    except ValueError as e:
        logger.error(
            "Failed to resolve redirect_uri for tenant",
            extra={
                "tenant_id": str(tenant_obj.id),
                "tenant_slug": tenant,
                "error": str(e),
            },
        )
        raise HTTPException(
            500,
            f"No public origin configured for tenant '{tenant}'. "
            "Contact administrator to configure canonical_public_origin.",
        )

    # Generate server-signed state (includes tenant context for callback validation)
    # State format: JWT with expiry (10 minutes)
    correlation_id = secrets.token_hex(8)  # Generate correlation ID for request tracing
    set_request_context(correlation_id=correlation_id)

    effective_updated_at = tenant_obj.updated_at or tenant_obj.created_at
    tenant_config_version = (
        effective_updated_at.isoformat() if effective_updated_at else None
    )

    state_payload = {
        "tenant_id": str(tenant_obj.id),
        "tenant_slug": tenant_obj.slug
        or tenant_obj.name,  # Use actual tenant slug or name as fallback
        "frontend_state": state or "",
        "nonce": secrets.token_hex(16),
        "redirect_uri": redirect_uri,  # Server-computed, consistent
        "correlation_id": correlation_id,
        "exp": int(time.time()) + settings.oidc_state_ttl_seconds,
        "iat": int(time.time()),  # Issued at timestamp
        "config_version": tenant_config_version,
    }
    signed_state = pyjwt.encode(state_payload, settings.jwt_secret, algorithm="HS256")

    state_cache_payload = {
        "tenant_id": str(tenant_obj.id),
        "tenant_slug": tenant_obj.slug
        or tenant_obj.name,  # Use actual tenant slug or name as fallback
        "redirect_uri": redirect_uri,
        "config_version": tenant_config_version,
        "iat": state_payload["iat"],
    }
    state_cache_key = f"oidc:state:{state_payload['nonce']}"

    redis_client = None
    try:
        redis_client = container.redis_client()
    except Exception:  # pragma: no cover - dependency injector safety net
        redis_client = None

    if redis_client:
        try:
            await redis_client.setex(
                state_cache_key,
                settings.oidc_state_ttl_seconds,
                json.dumps(state_cache_payload, separators=(",", ":")),
            )
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="initiate.state_cached",
                tenant_slug=tenant_obj.slug or tenant_obj.name,
                ttl=settings.oidc_state_ttl_seconds,
            )
        except Exception as exc:  # pragma: no cover - best effort cache
            logger.warning(
                "Failed to persist OIDC state in Redis",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "tenant_slug": tenant,
                    "error": str(exc),
                },
            )
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="initiate.state_cache_failed",
                tenant_slug=tenant_obj.slug or tenant_obj.name,
                error=str(exc),
            )
    else:
        await _log_oidc_debug(
            redis_client=redis_client,
            correlation_id=correlation_id,
            event="initiate.state_cache_skipped",
            tenant_slug=tenant_obj.slug or tenant_obj.name,
        )

    # Resolve authorization endpoint
    authorization_endpoint = federation_config.get("authorization_endpoint")
    if not authorization_endpoint and federation_config.get("discovery_endpoint"):
        try:
            discovery = await fetch_discovery(federation_config["discovery_endpoint"])
            authorization_endpoint = discovery.get("authorization_endpoint")
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            logger.error(
                "Failed to fetch discovery endpoint",
                extra={
                    "tenant_id": str(tenant_obj.id),
                    "discovery_endpoint": federation_config.get("discovery_endpoint"),
                    "error": str(e),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch IdP configuration",
            )

    if not authorization_endpoint:
        logger.error(
            "Failed to resolve authorization endpoint",
            extra={
                "tenant_id": str(tenant_obj.id),
                "federation_config": federation_config,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve authorization endpoint",
        )

    # Build authorization URL
    from urllib.parse import urlencode

    params = {
        "client_id": federation_config["client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(
            federation_config.get("scopes", ["openid", "email", "profile"])
        ),
        "state": signed_state,
    }
    authorization_url = f"{authorization_endpoint}?{urlencode(params)}"

    await _log_oidc_debug(
        redis_client=redis_client,
        correlation_id=correlation_id,
        event="initiate.authorization_ready",
        tenant_slug=tenant_obj.slug or tenant_obj.name,
        authorization_endpoint=authorization_endpoint,
        redirect_uri=redirect_uri,
    )

    logger.info(
        f"Authentication initiated for tenant {tenant_obj.name}",
        extra={
            "tenant_id": str(tenant_obj.id),
            "tenant_slug": tenant_obj.slug
            or tenant_obj.name,  # Use actual tenant slug or name
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
    summary="OIDC callback handler",
    description=(
        "Handle OIDC callback, validate token, lookup user. "
        "No authentication required (public endpoint). "
        "Returns JWT token for authenticated user."
    ),
    responses={
        400: {"description": "Invalid or expired state"},
        401: {"description": "Token validation failed"},
        403: {"description": "Domain not allowed, inactive tenant, or user missing"},
    },
)
async def auth_callback(
    callback: CallbackRequest,
    container: Container = Depends(get_container()),
):
    """
    Handle OIDC callback after user authenticates with IdP.

    This endpoint:
    1. Validates signed state (JWT with tenant context)
    2. Extracts tenant context from state
    3. Exchanges authorization code for tokens
    4. Validates ID token (signature, audience, expiry, at_hash)
    5. Validates email domain against tenant's allowed_domains
    6. Looks up existing user (NO auto-creation)
    7. Issues Intric JWT token

    Args:
        callback: CallbackRequest with code, state, code_verifier
        container: Dependency injection container

    Returns:
        AccessToken with Intric JWT

    Raises:
        HTTPException 400: Invalid state or code
        HTTPException 401: Token validation failed
        HTTPException 403: Email domain not allowed for tenant or user not found
    """
    settings = get_settings()
    redis_client = None
    cached_state: dict | None = None
    state_cache_key: str | None = None

    try:
        redis_client = container.redis_client()
    except Exception:  # pragma: no cover - dependency injector safety net
        redis_client = None

    # Validate and decode state
    # Note: pyjwt.decode() automatically validates 'exp' claim and raises ExpiredSignatureError
    try:
        state_payload = pyjwt.decode(
            callback.state, settings.jwt_secret, algorithms=["HS256"]
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

    state_nonce = state_payload.get("nonce")
    if not state_nonce:
        logger.error(
            "State token missing nonce claim",
            extra={"correlation_id": state_payload.get("correlation_id")},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter",
        )

    state_cache_key = f"oidc:state:{state_nonce}"

    tenant_id = UUID(state_payload["tenant_id"])
    tenant_slug = state_payload["tenant_slug"]
    redirect_uri = state_payload["redirect_uri"]
    # Extract correlation ID from state (flows from initiate endpoint)
    correlation_id = state_payload.get("correlation_id", secrets.token_hex(8))
    set_request_context(correlation_id=correlation_id, tenant_slug=tenant_slug)

    await _log_oidc_debug(
        redis_client=redis_client,
        correlation_id=correlation_id,
        event="callback.state_decoded",
        tenant_slug=tenant_slug,
    )

    if redis_client and state_cache_key:
        try:
            cached_raw = await redis_client.get(state_cache_key)
            if cached_raw:
                cached_state = json.loads(cached_raw)
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.state_cache_hit" if cached_state else "callback.state_cache_miss",
                tenant_slug=tenant_slug,
            )
        except Exception as exc:  # pragma: no cover - best effort cache fetch
            logger.warning(
                "Failed to retrieve cached OIDC state",
                extra={
                    "tenant_id": str(tenant_id),
                    "tenant_slug": tenant_slug,
                    "error": str(exc),
                    "correlation_id": correlation_id,
                },
            )
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.state_cache_error",
                tenant_slug=tenant_slug,
                error=str(exc),
            )
    else:
        await _log_oidc_debug(
            redis_client=redis_client,
            correlation_id=correlation_id,
            event="callback.state_cache_unavailable",
            tenant_slug=tenant_slug,
        )

    # Global exception handler to ensure correlation_id is always included in responses
    try:
        async with _cleanup_state_cache(
            redis_client,
            state_cache_key or "",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        ):
            if redis_client and state_cache_key:
                if not cached_state:
                    logger.error(
                        "OIDC state not found in cache during callback",
                        extra={
                            "tenant_slug": tenant_slug,
                            "state_key": state_cache_key,
                            "correlation_id": correlation_id,
                        },
                    )
                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event="callback.state_cache_missing",
                        tenant_slug=tenant_slug,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Authorization session is invalid or has expired. "
                            "Please restart the sign-in flow."
                        ),
                        headers={"X-Correlation-ID": correlation_id},
                    )

                expected_tenant_id = cached_state.get("tenant_id")
                if expected_tenant_id and expected_tenant_id != str(tenant_id):
                    logger.error(
                        "OIDC state tenant mismatch detected",
                        extra={
                            "expected_tenant_id": expected_tenant_id,
                            "supplied_tenant_id": str(tenant_id),
                            "tenant_slug": tenant_slug,
                            "state_key": state_cache_key,
                            "correlation_id": correlation_id,
                        },
                    )
                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event="callback.state_tampered",
                        reason="tenant_id_mismatch",
                        expected_tenant_id=expected_tenant_id,
                        supplied_tenant_id=str(tenant_id),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Authorization state mismatch detected. "
                            "Please restart the sign-in flow."
                        ),
                        headers={"X-Correlation-ID": correlation_id},
                    )

                expected_tenant_slug = (cached_state.get("tenant_slug") or "").lower()
                if expected_tenant_slug and expected_tenant_slug != (tenant_slug or "").lower():
                    logger.error(
                        "OIDC state tenant slug mismatch detected",
                        extra={
                            "expected_tenant_slug": expected_tenant_slug,
                            "supplied_tenant_slug": tenant_slug,
                            "state_key": state_cache_key,
                            "correlation_id": correlation_id,
                        },
                    )
                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event="callback.state_tampered",
                        reason="tenant_slug_mismatch",
                        expected_tenant_slug=expected_tenant_slug,
                        supplied_tenant_slug=tenant_slug,
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
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.tenant_loaded",
                tenant_id=str(tenant_id),
                tenant_slug=tenant_obj.slug or tenant_slug,
            )

            if tenant_obj.state != TenantState.ACTIVE:
                await _log_oidc_debug(
                    redis_client=redis_client,
                    correlation_id=correlation_id,
                    event="callback.tenant_inactive",
                    tenant_slug=tenant_slug,
                    state=str(tenant_obj.state),
                )
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

            encryption_service = container.encryption_service()
            credential_resolver = CredentialResolver(
                tenant=tenant_obj,
                settings=settings,
                encryption_service=encryption_service,
            )
            federation_config = credential_resolver.get_federation_config()

            # SECURITY: Validate redirect_uri from state matches tenant's expected redirect_uri
            # This provides defense-in-depth against:
            # 1. State JWT forgery (if JWT_SECRET is compromised)
            # 2. Configuration drift (if canonical_public_origin changed during auth flow)
            # 3. Cross-tenant redirect_uri confusion
            try:
                expected_redirect_uri = credential_resolver.get_redirect_uri()
            except ValueError as e:
                logger.error(
                    "Failed to resolve expected redirect_uri for validation",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_slug": tenant_slug,
                        "correlation_id": correlation_id,
                        "error": str(e),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to validate redirect_uri configuration",
                    headers={"X-Correlation-ID": correlation_id},
                )

            redirect_mismatch = redirect_uri != expected_redirect_uri
            allow_redirect_mismatch = False
            current_config_version = (
                tenant_obj.updated_at.isoformat() if tenant_obj.updated_at else None
            )
            state_config_version = (cached_state or {}).get(
                "config_version"
            ) or state_payload.get("config_version")
            grace_period = min(
                settings.oidc_redirect_grace_period_seconds,
                settings.oidc_state_ttl_seconds,
            )

            if redirect_mismatch:
                if not settings.strict_oidc_redirect_validation:
                    allow_redirect_mismatch = True
                else:
                    now = datetime.now(timezone.utc)
                    config_changed = (
                        current_config_version
                        and state_config_version
                        and current_config_version != state_config_version
                    )

                    if (
                        config_changed
                        and grace_period > 0
                        and cached_state
                        and cached_state.get("redirect_uri") == redirect_uri
                    ):
                        try:
                            state_issue_ts = int(state_payload.get("iat", 0))
                        except (TypeError, ValueError):
                            state_issue_ts = 0

                        seconds_since_issue = max(0, now.timestamp() - state_issue_ts)

                        tenant_updated_at = (
                            tenant_obj.updated_at or tenant_obj.created_at
                        )
                        if tenant_updated_at and tenant_updated_at.tzinfo is None:
                            tenant_updated_at = tenant_updated_at.replace(
                                tzinfo=timezone.utc
                            )

                        seconds_since_update = (
                            (now - tenant_updated_at).total_seconds()
                            if tenant_updated_at
                            else None
                        )

                        config_changed_after_state = False
                        if tenant_updated_at and state_config_version:
                            try:
                                state_config_dt = datetime.fromisoformat(
                                    state_config_version
                                )
                                if state_config_dt.tzinfo is None:
                                    state_config_dt = state_config_dt.replace(
                                        tzinfo=timezone.utc
                                    )
                                config_changed_after_state = (
                                    tenant_updated_at > state_config_dt
                                )
                            except ValueError:
                                config_changed_after_state = True
                        else:
                            config_changed_after_state = tenant_updated_at is not None

                        if (
                            seconds_since_issue <= grace_period
                            and (
                                seconds_since_update is None
                                or seconds_since_update <= grace_period
                            )
                            and config_changed_after_state
                        ):
                            allow_redirect_mismatch = True
                            logger.warning(
                                "Accepting redirect_uri from state due to recent config change",
                                extra={
                                    "tenant_id": str(tenant_id),
                                    "tenant_slug": tenant_slug,
                                    "state_redirect_uri": redirect_uri,
                                    "expected_redirect_uri": expected_redirect_uri,
                                    "correlation_id": correlation_id,
                                    "seconds_since_issue": seconds_since_issue,
                                    "seconds_since_update": seconds_since_update,
                                    "config_changed_after_state": config_changed_after_state,
                                },
                            )

                if not allow_redirect_mismatch:
                    logger.error(
                        "Redirect URI mismatch between state and tenant configuration",
                        extra={
                            "tenant_id": str(tenant_id),
                            "tenant_slug": tenant_slug,
                            "state_redirect_uri": redirect_uri,
                            "expected_redirect_uri": expected_redirect_uri,
                            "correlation_id": correlation_id,
                            "config_version_state": state_config_version,
                            "config_version_current": current_config_version,
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

            logger.debug(
                "Redirect URI validated successfully",
                extra={
                    "tenant_id": str(tenant_id),
                    "redirect_uri": redirect_uri,
                    "correlation_id": correlation_id,
                },
            )

            # Resolve token endpoint
            token_endpoint = federation_config.get("token_endpoint")
            if not token_endpoint and federation_config.get("discovery_endpoint"):
                try:
                    discovery = await fetch_discovery(
                        federation_config["discovery_endpoint"]
                    )
                    token_endpoint = discovery.get("token_endpoint")
                except HTTPException as e:
                    raise HTTPException(
                        status_code=e.status_code,
                        detail=e.detail,
                        headers={"X-Correlation-ID": correlation_id},
                    ) from e

            if not token_endpoint:
                logger.error(
                    "Failed to resolve token endpoint",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to resolve token endpoint",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # Determine token endpoint auth method
            def _select_auth_method(methods: list[str] | None) -> str | None:
                if not methods:
                    return None
                if not isinstance(methods, list):
                    methods = [methods]
                normalized = [str(m).lower() for m in methods if m]
                if "client_secret_post" in normalized:
                    return "client_secret_post"
                if "client_secret_basic" in normalized:
                    return "client_secret_basic"
                return normalized[0]

            token_auth_method = federation_config.get("token_endpoint_auth_method")
            supported_methods = federation_config.get(
                "token_endpoint_auth_methods_supported"
            )

            if not token_auth_method:
                token_auth_method = _select_auth_method(supported_methods)

            if not token_auth_method and federation_config.get("discovery_endpoint"):
                try:
                    discovery = await fetch_discovery(
                        federation_config["discovery_endpoint"]
                    )
                    supported_methods = discovery.get(
                        "token_endpoint_auth_methods_supported"
                    ) or []
                    token_auth_method = _select_auth_method(supported_methods)
                except HTTPException:
                    # Discovery failure handled earlier when resolving endpoints; fall back
                    token_auth_method = None
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to determine token endpoint auth method from discovery",
                        extra={
                            "tenant_id": str(tenant_id),
                            "token_endpoint": token_endpoint,
                            "error": str(exc),
                            "correlation_id": correlation_id,
                        },
                    )

            if not token_auth_method:
                token_auth_method = "client_secret_post"

            token_data = {
                "grant_type": "authorization_code",
                "code": callback.code,
                "redirect_uri": redirect_uri,
                "client_id": federation_config["client_id"],
                "client_secret": federation_config["client_secret"],
            }
            headers: dict[str, str] = {}

            if token_auth_method == "client_secret_basic":
                credentials = (
                    f"{federation_config['client_id']}:{federation_config['client_secret']}"
                )
                basic_token = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {basic_token}"
                token_data.pop("client_secret", None)
                token_data.pop("client_id", None)
            elif token_auth_method != "client_secret_post":
                logger.warning(
                    "Unsupported token endpoint auth method; defaulting to client_secret_post",
                    extra={
                        "tenant_id": str(tenant_id),
                        "requested_method": token_auth_method,
                        "correlation_id": correlation_id,
                    },
                )
                token_auth_method = "client_secret_post"

            logger.debug(
                "Exchanging authorization code for tokens",
                extra={
                    "tenant_id": str(tenant_id),
                    "token_endpoint": token_endpoint,
                    "auth_method": token_auth_method,
                    "correlation_id": correlation_id,
                },
            )

            async with aiohttp_client().post(
                token_endpoint, data=token_data, headers=headers or None
            ) as resp:
                if resp.status != 200:
                    # Capture IdP error response for debugging
                    try:
                        error_body = await resp.json()
                    except Exception:
                        error_body = await resp.text()

                    logger.error(
                        f"Token exchange failed: HTTP {resp.status}",
                        extra={
                            "tenant_id": str(tenant_id),
                            "http_status": resp.status,
                            "token_endpoint": token_endpoint,
                            "error_response": error_body,  # IdP's actual error message
                            "auth_method": token_auth_method,
                            "correlation_id": correlation_id,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Failed to exchange authorization code for tokens",
                        headers={"X-Correlation-ID": correlation_id},
                    )
                token_response = await resp.json()

            id_token = token_response.get("id_token")
            access_token = token_response.get("access_token")

            if not id_token or not access_token:
                logger.error(
                    "Missing id_token or access_token in response",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "has_id_token": bool(id_token),
                        "has_access_token": bool(access_token),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing id_token or access_token in response",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # Resolve JWKS URI
            jwks_uri = federation_config.get("jwks_uri")
            if not jwks_uri and federation_config.get("discovery_endpoint"):
                try:
                    discovery = await fetch_discovery(
                        federation_config["discovery_endpoint"]
                    )
                    jwks_uri = discovery.get("jwks_uri")
                except HTTPException as e:
                    raise HTTPException(
                        status_code=e.status_code,
                        detail=e.detail,
                        headers={"X-Correlation-ID": correlation_id},
                    ) from e

            if not jwks_uri:
                logger.error(
                    "Failed to resolve JWKS URI",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to resolve JWKS URI",
                    headers={"X-Correlation-ID": correlation_id},
                )

            auth_service = container.auth_service()

            # Get signing key from JWKS
            logger.debug(
                "Fetching JWKS for ID token validation",
                extra={
                    "tenant_id": str(tenant_id),
                    "jwks_uri": jwks_uri,
                    "correlation_id": correlation_id,
                },
            )

            try:
                jwk_client = JWKClient(jwks_uri)
                signing_key = jwk_client.get_signing_key_from_jwt(
                    id_token
                ).key  # Extract raw key from PyJWK wrapper
                logger.debug(
                    "JWKS fetched successfully",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                    },
                )
            except Exception as e:
                logger.error(
                    "Failed to fetch JWKS or extract signing key",
                    extra={
                        "tenant_id": str(tenant_id),
                        "jwks_uri": jwks_uri,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "correlation_id": correlation_id,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to validate ID token signature",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # Validate and decode ID token (conditional at_hash validation from Task 2)
            payload = auth_service.get_payload_from_openid_jwt(
                id_token=id_token,
                access_token=access_token,
                key=signing_key,
                signing_algos=["RS256"],
                client_id=federation_config["client_id"],
                correlation_id=correlation_id,
            )

            # Extract email from claims
            claims_mapping = federation_config.get("claims_mapping", {"email": "email"})
            email_claim = claims_mapping.get("email", "email")

            logger.debug(
                "Extracting email from ID token claims",
                extra={
                    "tenant_id": str(tenant_id),
                    "email_claim": email_claim,
                    "available_claims": list(payload.keys()),
                    "correlation_id": correlation_id,
                },
            )

            email = payload.get(email_claim)

            if not email:
                logger.error(
                    "Email claim not found in ID token",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "email_claim": email_claim,
                        "payload_keys": list(payload.keys()),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Email claim not found in ID token",
                    headers={"X-Correlation-ID": correlation_id},
                )

            set_request_context(user_email=email)
            await _log_oidc_debug(
                redis_client=redis_client,
                correlation_id=correlation_id,
                event="callback.email_extracted",
                email=email,
                email_claim=email_claim,
            )

            # Validate email format before domain checks (defensive against bad IdP data)
            _local_part, separator, domain_part = email.partition("@")
            if (
                separator == ""
                or not domain_part
                or not _local_part
                or "@" in domain_part
            ):
                logger.error(
                    "Email claim invalid format",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_slug": tenant_slug,
                        "email": email,
                        "correlation_id": correlation_id,
                    },
                )
                await _log_oidc_debug(
                    redis_client=redis_client,
                    correlation_id=correlation_id,
                    event="callback.email_invalid_format",
                    tenant_slug=tenant_slug,
                    email=email,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Email claim from identity provider is invalid. Contact your administrator.",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # CRITICAL: Email domain validation
            allowed_domains = federation_config.get("allowed_domains", [])
            if allowed_domains:
                email_domain_raw = domain_part
                email_domain = email_domain_raw.lower()
                try:
                    email_domain = email_domain.encode("idna").decode("ascii")
                except Exception:  # pragma: no cover - defensive normalization
                    pass

                normalized_allowed = []
                for domain in allowed_domains:
                    normalized = domain.lower()
                    try:
                        normalized = normalized.encode("idna").decode("ascii")
                    except Exception:
                        pass
                    normalized_allowed.append(normalized)

                if email_domain not in normalized_allowed:
                    logger.error(
                        "Email domain not allowed for tenant",
                        extra={
                            "tenant_id": str(tenant_id),
                            "tenant_slug": tenant_slug,
                            "email_domain": email_domain,
                            "allowed_domains": normalized_allowed,
                            "correlation_id": correlation_id,
                        },
                    )
                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event="callback.domain_rejected",
                        tenant_slug=tenant_slug,
                        email=email,
                        email_domain=email_domain,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Email domain '{email_domain_raw}' is not allowed for this organization. "
                            "Contact your administrator to add your domain."
                        ),
                        headers={"X-Correlation-ID": correlation_id},
                    )
                else:
                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event="callback.domain_allowed",
                        tenant_slug=tenant_slug,
                        email=email,
                        email_domain=email_domain,
                    )

            # Lookup existing user (NO user creation - users must already exist)
            user_repo = container.user_repo()
            user = await user_repo.get_user_by_email(email)

            if not user:
                logger.error(
                    "User not found in database",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_slug": tenant_slug,
                        "email": email,
                        "correlation_id": correlation_id,
                    },
                )
                await _log_oidc_debug(
                    redis_client=redis_client,
                    correlation_id=correlation_id,
                    event="callback.user_missing",
                    tenant_slug=tenant_slug,
                    email=email,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User not found. Contact your administrator for access.",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # Verify user belongs to correct tenant
            if user.tenant_id != tenant_id:
                logger.error(
                    "User tenant mismatch",
                    extra={
                        "user_tenant_id": str(user.tenant_id),
                        "expected_tenant_id": str(tenant_id),
                        "email": email,
                        "correlation_id": correlation_id,
                    },
                )
                await _log_oidc_debug(
                    redis_client=redis_client,
                    correlation_id=correlation_id,
                    event="callback.user_tenant_mismatch",
                    tenant_slug=tenant_slug,
                    email=email,
                    user_tenant_id=str(user.tenant_id),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied for this organization.",
                    headers={"X-Correlation-ID": correlation_id},
                )

            # Create JWT token for existing user
            access_token_response = auth_service.create_access_token_for_user(user)

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

            return {"access_token": access_token_response}
    except HTTPException:
        # Re-raise HTTPException with correlation_id already set
        raise
    except Exception as e:
        # Catch-all for unexpected errors - ensures correlation_id is always included
        logger.error(
            "Unexpected error during OIDC callback",
            extra={
                "tenant_id": str(tenant_id) if "tenant_id" in locals() else None,
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
