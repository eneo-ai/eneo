"""
Public OIDC authentication endpoints for tenant-based federation.

This router provides:
1. /auth/tenants - List active tenants for selector grid
2. /auth/initiate - Get authorization URL for tenant's IdP
3. /auth/callback - Handle OIDC callback and issue JWT token

All endpoints are public (no authentication required).
"""

import secrets
import time
from typing import Optional
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container
from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
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
)
async def initiate_auth(
    tenant: str = Query(..., description="Tenant slug (e.g., 'stockholm')"),
    state: Optional[str] = Query(
        None, description="Optional frontend-generated CSRF state"
    ),
    container: Container = Depends(get_container()),
) -> InitiateAuthResponse:
    """
    Get authorization URL for tenant's identity provider.

    This endpoint:
    1. Looks up tenant by slug
    2. Resolves tenant's federation config (tenant-specific or global)
    3. Computes redirect_uri server-side from canonical_public_origin
    4. Generates server-signed state (includes tenant context for callback)
    5. Builds authorization URL with IdP parameters
    6. Returns URL for frontend to redirect user

    Args:
        tenant: Tenant slug (from URL parameter)
        state: Optional frontend-generated state for CSRF protection
        container: Dependency injection container

    Returns:
        InitiateAuthResponse with authorization_url and signed state

    Raises:
        HTTPException 404: Tenant not found or no slug configured
        HTTPException 500: No IdP configured for tenant or no public origin
    """
    tenant_repo = container.tenant_repo()
    settings = get_settings()

    # Lookup tenant by slug
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

    state_payload = {
        "tenant_id": str(tenant_obj.id),
        "tenant_slug": tenant,
        "frontend_state": state or "",
        "nonce": secrets.token_hex(16),
        "redirect_uri": redirect_uri,  # Server-computed, consistent
        "correlation_id": correlation_id,
        "exp": int(time.time()) + 600,  # Expires in 10 minutes
        "iat": int(time.time()),  # Issued at timestamp
    }
    signed_state = pyjwt.encode(state_payload, settings.jwt_secret, algorithm="HS256")

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

    logger.info(
        f"Authentication initiated for tenant {tenant}",
        extra={
            "tenant_id": str(tenant_obj.id),
            "tenant_slug": tenant,
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

    tenant_id = UUID(state_payload["tenant_id"])
    tenant_slug = state_payload["tenant_slug"]
    redirect_uri = state_payload["redirect_uri"]
    # Extract correlation ID from state (flows from initiate endpoint)
    correlation_id = state_payload.get("correlation_id", secrets.token_hex(8))

    # Get tenant and federation config
    tenant_repo = container.tenant_repo()
    tenant_obj = await tenant_repo.get(tenant_id)
    if not tenant_obj:
        logger.error(
            "Tenant not found",
            extra={"tenant_id": str(tenant_id), "correlation_id": correlation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
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

    if redirect_uri != expected_redirect_uri:
        logger.error(
            "Redirect URI mismatch between state and tenant configuration",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_slug": tenant_slug,
                "state_redirect_uri": redirect_uri,
                "expected_redirect_uri": expected_redirect_uri,
                "correlation_id": correlation_id,
                "potential_cause": "Configuration changed during auth flow or state JWT tampering",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Redirect URI mismatch - authentication flow invalid. "
                "This may occur if tenant configuration changed during login. "
                "Please try logging in again. "
                "If this persists, contact your administrator."
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
            discovery = await fetch_discovery(federation_config["discovery_endpoint"])
            token_endpoint = discovery.get("token_endpoint")
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code,
                detail=e.detail,
                headers={"X-Correlation-ID": correlation_id}
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

    # Exchange code for tokens
    token_data = {
        "grant_type": "authorization_code",
        "code": callback.code,
        "redirect_uri": redirect_uri,
        "client_id": federation_config["client_id"],
        "client_secret": federation_config["client_secret"],
    }

    async with aiohttp_client().post(token_endpoint, data=token_data) as resp:
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
            discovery = await fetch_discovery(federation_config["discovery_endpoint"])
            jwks_uri = discovery.get("jwks_uri")
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code,
                detail=e.detail,
                headers={"X-Correlation-ID": correlation_id}
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

    # Validate ID token using existing auth_service method
    from jwt import PyJWKClient

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
        jwk_client = PyJWKClient(jwks_uri)
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
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

    # CRITICAL: Email domain validation
    allowed_domains = federation_config.get("allowed_domains", [])
    if allowed_domains:
        email_domain = email.split("@")[1]
        if email_domain not in allowed_domains:
            logger.error(
                "Email domain not allowed for tenant",
                extra={
                    "tenant_id": str(tenant_id),
                    "tenant_slug": tenant_slug,
                    "email_domain": email_domain,
                    "allowed_domains": allowed_domains,
                    "correlation_id": correlation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Email domain '{email_domain}' is not allowed for this organization. "
                f"Contact your administrator to add your domain.",
                headers={"X-Correlation-ID": correlation_id},
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

    return {"access_token": access_token_response}
