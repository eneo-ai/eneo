"""Public OIDC authentication endpoints for tenant-based federation."""

import asyncio
import base64
import contextlib
import hashlib
import json
import random
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

import aiohttp
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from jwt import PyJWKClient as _PyJWKClient
from pydantic import BaseModel

from intric.authentication.jwks_cache import get_jwks
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


# HTTP timeout configuration for IdP requests
# Per-endpoint timeouts based on expected response times
#
# NOTE: 'connect' timeout includes DNS resolution time
# Token endpoint has higher timeout to accommodate:
#   - Slow DNS infrastructure (up to ~8s in some environments)
#   - TCP connection establishment (1-2s)
#   - TLS handshake (1-2s)
#   - IdP load balancer redirects (1-2s)
# These are MAXIMUM timeouts - connections complete as fast as possible
OIDC_TIMEOUTS = {
    "discovery": aiohttp.ClientTimeout(total=3.0, connect=1.5),
    "jwks": aiohttp.ClientTimeout(total=3.0, connect=1.5),
    "token": aiohttp.ClientTimeout(
        total=15.0,   # Increase from 10s to 15s (allows slow DNS + token exchange)
        connect=12.0  # Increase from 5s to 12s (allows 8s DNS + 4s TCP/TLS)
    ),  # Tolerant of slow DNS infrastructure (no artificial delay)
}

# Sensitive keys that should NEVER be logged
SENSITIVE_KEYS = {
    "client_secret",
    "authorization_code",
    "code",
    "access_token",
    "id_token",
    "refresh_token",
    "password",
    "secret",
}

# Sensitive headers that should NOT be logged
SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
}


def _classify_http_error(status_code: int) -> str:
    """
    Classify HTTP status code into error_kind for structured logging.

    Args:
        status_code: HTTP status code from IdP response

    Returns:
        Error kind string for logging and classification
    """
    if status_code == 502:
        return "http_502_bad_gateway"
    elif status_code == 503:
        return "http_503_service_unavailable"
    elif status_code == 504:
        return "http_504_gateway_timeout"
    elif status_code == 401:
        return "http_401_unauthorized"
    elif status_code == 403:
        return "http_403_forbidden"
    elif status_code == 429:
        return "http_429_rate_limited"
    elif 400 <= status_code < 500:
        return "http_4xx_client_error"
    elif 500 <= status_code < 600:
        return "http_5xx_server_error"
    else:
        return "http_unknown"


def _is_proxy_error(status_code: int, headers: dict) -> bool:
    """
    Detect if HTTP error is from proxy/load balancer vs IdP application.

    Proxy errors typically return HTML error pages with specific server headers.

    Args:
        status_code: HTTP status code
        headers: Response headers

    Returns:
        True if error appears to be from proxy, False if from IdP app
    """
    if status_code not in (502, 503, 504):
        return False

    content_type = headers.get("content-type", "").lower()
    server = headers.get("server", "").lower()

    # Proxy typically returns HTML error page
    is_html = "text/html" in content_type
    is_proxy_server = any(p in server for p in ["nginx", "apache", "haproxy", "envoy"])

    return is_html or is_proxy_server


def _classify_token_error(status_code: int, error_code: str) -> str:
    """
    Classify OAuth token exchange error.

    Args:
        status_code: HTTP status code
        error_code: OAuth error code from response body

    Returns:
        Error kind string combining OAuth error and HTTP status
    """
    if error_code == "invalid_grant":
        return "oauth_invalid_grant"
    elif error_code == "invalid_client":
        return "oauth_invalid_client"
    elif error_code == "access_denied":
        return "oauth_access_denied"
    elif error_code == "unauthorized_client":
        return "oauth_unauthorized_client"
    elif error_code == "unsupported_grant_type":
        return "oauth_unsupported_grant_type"
    else:
        return _classify_http_error(status_code)


def _redact_sensitive_data(data: dict) -> dict:
    """
    Remove sensitive keys from dict for safe logging.

    Args:
        data: Dict potentially containing sensitive keys

    Returns:
        Dict with sensitive values redacted
    """
    return {
        k: "***REDACTED***" if k.lower() in SENSITIVE_KEYS else v
        for k, v in data.items()
    }


def _safe_headers(headers: dict) -> dict:
    """
    Remove sensitive headers for safe logging.

    Args:
        headers: Response headers dict

    Returns:
        Dict with sensitive headers removed
    """
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


def _fingerprint_code(code: str) -> str:
    """
    Create SHA256 fingerprint of authorization code for logging.

    Never logs the full code value (security risk). Creates a hash
    that can be used to correlate requests without exposing the secret.

    Args:
        code: Authorization code from IdP

    Returns:
        SHA256 hash prefix (first 12 chars) in format "sha256:abc123..."
    """
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    return f"sha256:{code_hash[:12]}"


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


async def _make_idp_http_request(
    method: str,
    url: str,
    endpoint_type: Literal["discovery", "token", "jwks"],
    correlation_id: str,
    tenant_id: UUID,
    provider: str,
    redis_client=None,
    retry_enabled: bool = True,
    **request_kwargs,
) -> tuple[bytes, int, dict]:
    """
    Make HTTP request to IdP with timeout, retry, and enhanced logging.

    CRITICAL: Reads response body ONCE to avoid stream consumption errors.
    Returns raw bytes for caller to parse.

    Args:
        method: HTTP method (GET, POST)
        url: Full URL to request
        endpoint_type: Type of endpoint (discovery, token, jwks)
        correlation_id: Request correlation ID for tracing
        tenant_id: Tenant UUID
        provider: IdP provider name
        redis_client: Redis client for debug mode check
        retry_enabled: Enable retry for GET requests
        **request_kwargs: Additional arguments for aiohttp (data, headers, etc.)

    Returns:
        Tuple of (response_body_bytes, status_code, headers_dict)

    Raises:
        aiohttp.ClientError: Network-level errors
        asyncio.TimeoutError: Request timeout
    """
    timeout = OIDC_TIMEOUTS.get(endpoint_type, OIDC_TIMEOUTS["token"])
    max_attempts = 3 if method == "GET" and retry_enabled else 1
    backoff_delays = [0.2, 0.4, 0.8]  # seconds

    debug_enabled = await is_debug_enabled(redis_client) if redis_client else False

    for attempt in range(max_attempts):
        attempt_start = time.perf_counter()

        # Add jitter to backoff for retries
        if attempt > 0:
            jitter = random.uniform(-0.02, 0.02)
            delay = backoff_delays[attempt - 1] + jitter
            await asyncio.sleep(delay)
            logger.debug(
                "Retrying IdP HTTP request",
                extra={
                    "correlation_id": correlation_id,
                    "endpoint_type": endpoint_type,
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "backoff_ms": int(delay * 1000),
                },
            )

        try:
            # CRITICAL: Get singleton session directly (NOT as context manager)
            # Using `async with aiohttp_client() as session` would close the singleton!
            # The old code used aiohttp_client().post() which doesn't close the session.
            # We only use async with on the RESPONSE level, not session level.
            session = aiohttp_client()
            if session is None:
                raise RuntimeError("aiohttp ClientSession not started")

            # DIAGNOSTIC: Log aiohttp client configuration for IPv4/DNS debugging
            # Use getattr for mock compatibility (test mocks may not have connector/private attributes)
            connector = getattr(session, 'connector', None)
            if connector:
                # Safely access private attributes (may not exist in mocks)
                family = getattr(connector, '_family', None)
                family_name = (
                    "AF_INET" if family == socket.AF_INET
                    else "AF_INET6" if family == socket.AF_INET6
                    else f"UNKNOWN({family})" if family is not None
                    else "NO_FAMILY"
                )
                logger.debug(
                    f"DIAGNOSTIC: aiohttp session config for {endpoint_type} endpoint",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "endpoint_type": endpoint_type,
                        "connector_type": type(connector).__name__,
                        "connector_family": family,
                        "connector_family_name": family_name,
                        "use_dns_cache": getattr(connector, '_use_dns_cache', None),
                        "ttl_dns_cache": getattr(connector, '_ttl_dns_cache', None),
                        "session_closed": getattr(session, 'closed', None),
                    },
                )

            async with session.request(
                method=method,
                url=url,
                timeout=timeout,
                **request_kwargs,
            ) as response:
                # Read response body ONCE (critical for stream safety)
                body_bytes = await response.read()
                status_code = response.status
                headers = dict(response.headers)

            duration_ms = int((time.perf_counter() - attempt_start) * 1000)

            # Log successful or error responses
            log_extra = {
                "event": "idp_http_request",
                "correlation_id": correlation_id,
                "tenant_id": str(tenant_id),
                "provider": provider,
                "endpoint_type": endpoint_type,
                "http_method": method,
                "url": url,  # NOTE: client_id in query params is safe to log
                "http_status": status_code,
                "duration_ms": duration_ms,
                "content_type": headers.get("content-type", ""),
                "response_size_bytes": len(body_bytes),
                "attempt": attempt + 1,
            }

            if status_code >= 400:
                error_kind = _classify_http_error(status_code)
                proxy_generated = _is_proxy_error(status_code, headers)

                log_extra.update(
                    {
                        "error_kind": error_kind,
                        "proxy_generated": proxy_generated,
                    }
                )

                # Debug mode: log response body preview and headers
                if debug_enabled:
                    body_preview = body_bytes[:2048].decode("utf-8", errors="ignore")
                    safe_headers = _safe_headers(headers)
                    log_extra.update(
                        {
                            "response_body_preview": body_preview,
                            "response_headers": safe_headers,
                        }
                    )

                logger.error(
                    f"IdP HTTP request failed: HTTP {status_code}", extra=log_extra
                )

                # Retry conditions for GET requests
                if (
                    method == "GET"
                    and status_code in (502, 503, 504, 429)
                    and attempt < max_attempts - 1
                ):
                    logger.warning(
                        "IdP request failed, will retry",
                        extra={
                            "correlation_id": correlation_id,
                            "http_status": status_code,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                        },
                    )
                    continue  # Retry

                # No retry, return error response
                return body_bytes, status_code, headers

            else:
                # Success (2xx)
                logger.info(
                    "IdP HTTP request succeeded",
                    extra=log_extra,
                )

                # Debug mode: log response preview
                if debug_enabled and endpoint_type in ("discovery", "jwks"):
                    body_preview = body_bytes[:2048].decode("utf-8", errors="ignore")
                    log_extra["response_body_preview"] = body_preview

                    await _log_oidc_debug(
                        redis_client=redis_client,
                        correlation_id=correlation_id,
                        event=f"{endpoint_type}.response_preview",
                        body_preview=body_preview,
                    )

                return body_bytes, status_code, headers

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            duration_ms = int((time.perf_counter() - attempt_start) * 1000)

            # Classify error type for better diagnostics
            if isinstance(e, asyncio.TimeoutError):
                error_kind = "timeout_error"
            elif isinstance(e, aiohttp.ClientConnectorSSLError):
                error_kind = "tls_handshake_error"
            elif isinstance(e, aiohttp.ClientConnectorError):
                error_kind = "connection_error"
            elif isinstance(e, aiohttp.ClientConnectionError):
                error_kind = "connection_error"
            else:
                error_kind = "network_error"

            logger.error(
                f"IdP HTTP request {error_kind}: {e.__class__.__name__}",
                extra={
                    "event": "idp_http_request_failed",
                    "correlation_id": correlation_id,
                    "tenant_id": str(tenant_id),
                    "provider": provider,
                    "endpoint_type": endpoint_type,
                    "http_method": method,
                    "url": url,
                    "error_kind": error_kind,
                    "exception_class": e.__class__.__name__,
                    "error_message": str(e),
                    "duration_ms": duration_ms,
                    "attempt": attempt + 1,
                },
            )

            # Retry for GET on network errors
            if method == "GET" and attempt < max_attempts - 1:
                logger.warning(
                    "Network error, will retry",
                    extra={
                        "correlation_id": correlation_id,
                        "exception": e.__class__.__name__,
                        "attempt": attempt + 1,
                    },
                )
                continue  # Retry

            # Re-raise for caller to handle
            raise

    # Should not reach here, but for safety
    raise Exception(f"Max retry attempts ({max_attempts}) exhausted")


async def fetch_discovery(
    discovery_url: str,
    correlation_id: str,
    tenant_id: UUID,
    provider: str,
    redis_client=None,
) -> dict:
    """
    Fetch OIDC discovery document with timeout and enhanced error logging.

    Uses wrapper function for timeout, retry, and enhanced logging.
    Discovery endpoints are rarely called and IdPs handle rate limiting.

    Args:
        discovery_url: URL to OIDC discovery document
        correlation_id: Request correlation ID for tracing
        tenant_id: Tenant UUID
        provider: IdP provider name
        redis_client: Redis client for debug mode check

    Returns:
        dict: Discovery document JSON

    Raises:
        HTTPException 500: Failed to fetch discovery document
        aiohttp.ClientError: Network errors
        asyncio.TimeoutError: Request timeout
    """
    try:
        body_bytes, status_code, headers = await _make_idp_http_request(
            method="GET",
            url=discovery_url,
            endpoint_type="discovery",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            provider=provider,
            redis_client=redis_client,
            retry_enabled=True,
        )

        if status_code != 200:
            # Error already logged by wrapper
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch discovery document: HTTP {status_code}",
            )

        # Parse discovery document JSON
        try:
            return json.loads(body_bytes)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse discovery document JSON",
                extra={
                    "correlation_id": correlation_id,
                    "tenant_id": str(tenant_id),
                    "error_kind": "discovery_parse_error",
                    "error": str(e),
                    "body_preview": body_bytes[:256].decode("utf-8", errors="ignore"),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Discovery document is not valid JSON",
            )

    except (aiohttp.ClientError, asyncio.TimeoutError):
        # Network error already logged by wrapper
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch discovery document: network error",
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
    tenant_slug: str  # Echo back resolved tenant slug for frontend routing

    model_config = {
        "json_schema_extra": {
            "example": {
                "authorization_url": "https://idp.example.com/authorize?client_id=abc123&...",
                "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "tenant_slug": "example-tenant",
            }
        }
    }


class CallbackRequest(BaseModel):
    """OIDC callback with authorization code or error from IdP."""

    code: Optional[str] = None
    state: str
    code_verifier: Optional[str] = None  # For PKCE (future use)
    error: Optional[str] = None  # OAuth error code from IdP
    error_description: Optional[str] = None  # OAuth error description from IdP

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
        # Validate: tenant parameter required in multi-tenant mode
        if settings.federation_per_tenant_enabled:
            logger.error(
                "Tenant parameter missing in multi-tenant mode",
                extra={"federation_per_tenant_enabled": True},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tenant parameter required when multi-tenant federation is enabled",
            )

        # Single-tenant mode: use first active tenant with global OIDC config
        tenants = await tenant_repo.get_all_active()
        if not tenants:
            logger.error("No active tenant found for single-tenant OIDC")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No active tenant found",
            )

        # SAFETY: Prevent silent misconfiguration - require explicit multi-tenant mode
        if len(tenants) > 1:
            logger.error(
                f"Cannot use single-tenant OIDC with {len(tenants)} active tenants",
                extra={
                    "tenant_count": len(tenants),
                    "recommendation": "Set FEDERATION_PER_TENANT_ENABLED=true for multi-tenant support",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Single-tenant OIDC mode requires exactly one tenant, but {len(tenants)} active tenants found. "
                    "To enable multi-tenant federation, set FEDERATION_PER_TENANT_ENABLED=true in your backend configuration. "
                    "Alternatively, deactivate extra tenants if you only need one."
                ),
            )

        tenant_obj = tenants[0]  # Use the single active tenant
        logger.info(
            f"Single-tenant OIDC: using tenant {tenant_obj.name}",
            extra={
                "tenant_id": str(tenant_obj.id),
                "tenant_name": tenant_obj.name,
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
            discovery = await fetch_discovery(
                discovery_url=federation_config["discovery_endpoint"],
                correlation_id=correlation_id,
                tenant_id=tenant_obj.id,
                provider=federation_config.get("provider", "unknown"),
                redis_client=redis_client,
            )
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
                    "correlation_id": correlation_id,
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
        tenant_slug=tenant_obj.slug or tenant_obj.name,
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

    # Log callback entry (before correlation_id is available)
    logger.info(
        "OIDC callback received",
        extra={
            "event": "oidc_callback_received",
            "code_present": bool(callback.code),
            "state_present": bool(callback.state),
            "error_present": bool(callback.error),
        },
    )

    # Check if IdP returned OAuth error parameters (e.g., redirect_uri mismatch, user canceled)
    if callback.error:
        error_desc = callback.error_description or ""
        logger.error(
            f"IdP returned error during authorization: {callback.error}",
            extra={
                "event": "oidc_callback_idp_error",
                "idp_error_code": callback.error,
                "idp_error_description": error_desc[:256],  # Truncate for safety
                "state_present": bool(callback.state),
            },
        )

        # Map common OAuth errors to user-friendly messages
        if callback.error == "access_denied":
            user_message = "Login was canceled or access was denied."
        elif callback.error == "invalid_request":
            user_message = f"Configuration error: {error_desc[:100]}"
        elif callback.error == "unauthorized_client":
            user_message = "This application is not authorized."
        elif callback.error == "server_error":
            user_message = "Identity provider encountered an error. Please try again."
        else:
            user_message = f"Authentication failed: {callback.error}"

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message,
            headers={
                "X-Error-Kind": f"idp_{callback.error}",
                "X-IdP-Error-Code": callback.error,
            },
        )

    # Validate code is present when no error
    if not callback.code:
        logger.error(
            "OIDC callback missing authorization code",
            extra={
                "event": "oidc_callback_missing_code",
                "state_present": bool(callback.state),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code is missing. Please try logging in again.",
            headers={"X-Error-Kind": "missing_authorization_code"},
        )

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
            headers={"X-Error-Kind": "state_expired"},
        )
    except pyjwt.PyJWTError as e:
        # Note: correlation_id not available yet (state decode failed)
        logger.error(
            "Invalid state parameter",
            extra={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter. Please try logging in again.",
            headers={"X-Error-Kind": "invalid_state"},
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

    # Log state validation success
    logger.info(
        "State validation succeeded",
        extra={
            "event": "oidc_state_validated",
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "correlation_id": correlation_id,
        },
    )

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
                event="callback.state_cache_hit"
                if cached_state
                else "callback.state_cache_miss",
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
                if (
                    expected_tenant_slug
                    and expected_tenant_slug != (tenant_slug or "").lower()
                ):
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
                        discovery_url=federation_config["discovery_endpoint"],
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        provider=federation_config.get("provider", "unknown"),
                        redis_client=redis_client,
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
                        discovery_url=federation_config["discovery_endpoint"],
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        provider=federation_config.get("provider", "unknown"),
                        redis_client=redis_client,
                    )
                    supported_methods = (
                        discovery.get("token_endpoint_auth_methods_supported") or []
                    )
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
                credentials = f"{federation_config['client_id']}:{federation_config['client_secret']}"
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
                    "client_id": federation_config["client_id"],  # Safe to log
                    "correlation_id": correlation_id,
                },
            )

            # Debug mode: Log token request parameters for diagnosing config issues
            if redis_client and await is_debug_enabled(redis_client) and callback.code:
                # Create sanitized view of request parameters
                # Note: Only log if code exists (it's Optional now for OAuth error callbacks)
                code_fingerprint = _fingerprint_code(callback.code)
                token_request_params = {
                    "grant_type": token_data.get("grant_type"),
                    "redirect_uri": token_data.get("redirect_uri"),
                    "client_id": token_data.get("client_id"),
                    "auth_method": token_auth_method,
                    "code_fingerprint": code_fingerprint,  # Hash only, not full code
                    "request_headers_present": list(headers.keys()) if headers else [],
                }

                await _log_oidc_debug(
                    redis_client=redis_client,
                    correlation_id=correlation_id,
                    event="token_exchange.request_params",
                    tenant_slug=tenant_slug,
                    **token_request_params,
                )

                logger.debug(
                    "Token exchange request parameters (debug mode)",
                    extra={
                        "correlation_id": correlation_id,
                        "tenant_id": str(tenant_id),
                        **token_request_params,
                    },
                )

            # Exchange authorization code for tokens
            try:
                (
                    body_bytes,
                    status_code,
                    response_headers,
                ) = await _make_idp_http_request(
                    method="POST",
                    url=token_endpoint,
                    endpoint_type="token",
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    provider=federation_config.get("provider", "unknown"),
                    redis_client=redis_client,
                    retry_enabled=False,  # NEVER retry token POST (OAuth safety)
                    data=token_data,
                    headers=headers or None,
                    allow_redirects=False,  # Token endpoint should NEVER redirect
                )

                # Handle redirects from load balancer (e.g., m00 → m02/m03)
                # Allow up to 3 hops to support multi-tier load balancer setups
                max_redirects = 3
                redirect_count = 0
                while 300 <= status_code < 400 and redirect_count < max_redirects:
                    location = response_headers.get("Location") or response_headers.get(
                        "location"
                    )
                    if not location:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token endpoint redirect without Location header",
                            headers={"X-Correlation-ID": correlation_id},
                        )

                    # Resolve absolute URL
                    from urllib.parse import urljoin, urlparse

                    redirected_url = urljoin(token_endpoint, location)
                    parsed = urlparse(redirected_url)

                    # Security validation: require HTTPS and expected domain
                    if parsed.scheme != "https" or not parsed.netloc.endswith(
                        ".login.sundsvall.se"
                    ):
                        logger.error(
                            "Token endpoint redirected to unexpected location",
                            extra={
                                "tenant_id": str(tenant_id),
                                "original_url": token_endpoint,
                                "redirect_url": redirected_url,
                                "http_status": status_code,
                                "error_kind": "unexpected_redirect_target",
                                "correlation_id": correlation_id,
                            },
                        )
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token endpoint configuration error: unexpected redirect target",
                            headers={"X-Correlation-ID": correlation_id},
                        )

                    logger.info(
                        f"Following token endpoint redirect (hop {redirect_count + 1})",
                        extra={
                            "tenant_id": str(tenant_id),
                            "from_url": token_endpoint
                            if redirect_count == 0
                            else "previous_redirect",
                            "to_url": redirected_url,
                            "http_status": status_code,
                            "redirect_hop": redirect_count + 1,
                            "correlation_id": correlation_id,
                        },
                    )

                    # Re-POST to redirected URL
                    (
                        body_bytes,
                        status_code,
                        response_headers,
                    ) = await _make_idp_http_request(
                        method="POST",
                        url=redirected_url,
                        endpoint_type="token",
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        provider=federation_config.get("provider", "unknown"),
                        redis_client=redis_client,
                        retry_enabled=False,
                        data=token_data,
                        headers=headers or None,
                        allow_redirects=False,
                    )

                    redirect_count += 1
                    token_endpoint = redirected_url  # Update for next iteration logging

                # If still 3xx after max redirects, fail
                if 300 <= status_code < 400:
                    logger.error(
                        "Too many redirects from token endpoint",
                        extra={
                            "tenant_id": str(tenant_id),
                            "http_status": status_code,
                            "redirect_count": redirect_count,
                            "max_redirects": max_redirects,
                            "correlation_id": correlation_id,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Token endpoint configuration error: exceeded {max_redirects} redirects",
                        headers={"X-Correlation-ID": correlation_id},
                    )

                if status_code != 200:
                    # Parse OAuth error response
                    try:
                        error_json = json.loads(body_bytes)
                        error_code = error_json.get("error", "unknown")
                        error_desc = error_json.get("error_description", "")[
                            :256
                        ]  # Truncate
                    except Exception:
                        error_code = "parse_failed"
                        error_desc = body_bytes[:256].decode("utf-8", errors="ignore")

                    # Enhanced error logging with OAuth error details
                    logger.error(
                        f"Token exchange failed: HTTP {status_code}",
                        extra={
                            "tenant_id": str(tenant_id),
                            "http_status": status_code,
                            "token_endpoint": token_endpoint,
                            "idp_error_code": error_code,
                            "idp_error_description": error_desc,
                            "auth_method": token_auth_method,
                            "client_id": federation_config["client_id"],  # Safe to log
                            "error_kind": _classify_token_error(
                                status_code, error_code
                            ),
                            "proxy_generated": _is_proxy_error(
                                status_code, response_headers
                            ),
                            "correlation_id": correlation_id,
                        },
                    )
                    error_kind = _classify_token_error(status_code, error_code)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Failed to exchange authorization code for tokens",
                        headers={
                            "X-Correlation-ID": correlation_id,
                            "X-Error-Kind": error_kind,
                            "X-IdP-Error-Code": error_code,
                        },
                    )

                # Parse token response JSON
                try:
                    token_response = json.loads(body_bytes)
                except json.JSONDecodeError as e:
                    logger.error(
                        "Token response is not valid JSON",
                        extra={
                            "tenant_id": str(tenant_id),
                            "error_kind": "token_response_parse_error",
                            "content_type": response_headers.get("content-type"),
                            "error": str(e),
                            "body_preview": body_bytes[:256].decode(
                                "utf-8", errors="ignore"
                            ),
                            "correlation_id": correlation_id,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token endpoint returned invalid response",
                        headers={"X-Correlation-ID": correlation_id},
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # Network error already logged by wrapper
                error_extra = {
                    "tenant_id": str(tenant_id),
                    "token_endpoint": token_endpoint,
                    "error_kind": "network_error",
                    "exception_class": e.__class__.__name__,
                    "correlation_id": correlation_id,
                }

                # Add diagnostic hint for connection/DNS timeouts
                if isinstance(e, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
                    error_extra["diagnostic_hint"] = (
                        "Connection timeout may indicate slow DNS resolution. "
                        "Check 'dns_slow' events in logs or DNS server configuration."
                    )

                logger.error(
                    "Token exchange - network error",
                    extra=error_extra,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to exchange authorization code: network error",
                    headers={"X-Correlation-ID": correlation_id},
                )

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
                        discovery_url=federation_config["discovery_endpoint"],
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        provider=federation_config.get("provider", "unknown"),
                        redis_client=redis_client,
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

            # Try to decode ID token header for logging (non-fatal if fails)
            kid = None
            alg = None
            try:
                unverified_header = pyjwt.get_unverified_header(id_token)
                kid = unverified_header.get("kid")
                alg = unverified_header.get("alg")

                logger.debug(
                    "ID token header decoded",
                    extra={
                        "tenant_id": str(tenant_id),
                        "kid": kid,
                        "alg": alg,
                        "correlation_id": correlation_id,
                    },
                )
            except Exception:
                # Header decoding is only for logging, don't fail if it doesn't work
                # JWKClient will handle validation
                pass

            try:
                # Create fetch function for JWKS cache
                async def fetch_jwks_func():
                    return await _make_idp_http_request(
                        method="GET",
                        url=jwks_uri,
                        endpoint_type="jwks",
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        provider=federation_config.get("provider", "unknown"),
                        redis_client=redis_client,
                        retry_enabled=True,
                    )

                # Get JWKS with caching (Redis-based, 1 hour TTL like PyJWKClient)
                jwks_data = await get_jwks(
                    jwks_uri=jwks_uri,
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                    provider=federation_config.get("provider", "unknown"),
                    redis_client=redis_client,
                    fetch_function=fetch_jwks_func,
                )

                # Extract signing key matching kid from ID token
                from jwt import PyJWKSet

                jwk_set = PyJWKSet.from_dict(jwks_data)
                signing_key = None

                # Try to find key by kid if kid is present
                if kid:
                    for jwk in jwk_set.keys:
                        if jwk.key_id == kid:
                            signing_key = jwk.key
                            break

                # Fallback: if kid missing or not found, use single key if available
                if not signing_key:
                    if len(jwk_set.keys) == 1:
                        # Only one key available - use it (common in test/dev environments)
                        signing_key = jwk_set.keys[0].key
                        logger.debug(
                            "Using single available key from JWKS (kid not matched)",
                            extra={
                                "tenant_id": str(tenant_id),
                                "jwks_uri": jwks_uri,
                                "kid": kid,
                                "correlation_id": correlation_id,
                            },
                        )
                    else:
                        logger.error(
                            "KID not found in JWKS",
                            extra={
                                "tenant_id": str(tenant_id),
                                "jwks_uri": jwks_uri,
                                "kid": kid,
                                "available_kids": [j.key_id for j in jwk_set.keys],
                                "correlation_id": correlation_id,
                            },
                        )
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Signing key not found in JWKS",
                            headers={"X-Correlation-ID": correlation_id},
                        )

                logger.debug(
                    "JWKS fetched and signing key extracted",
                    extra={
                        "tenant_id": str(tenant_id),
                        "kid": kid,
                        "jwks_uri": jwks_uri,
                        "correlation_id": correlation_id,
                    },
                )

            except HTTPException:
                # Re-raise HTTP exceptions as-is
                raise
            except Exception as e:
                # Catch any other errors (PyJWT parsing, etc.)
                logger.error(
                    "Failed to process JWKS or extract signing key",
                    extra={
                        "tenant_id": str(tenant_id),
                        "jwks_uri": jwks_uri,
                        "kid": kid,
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

            # Log ID token validation success
            logger.info(
                "ID token validation succeeded",
                extra={
                    "event": "id_token_validated",
                    "tenant_id": str(tenant_id),
                    "iss": payload.get("iss"),
                    "aud": payload.get("aud"),
                    "kid": kid if "kid" in locals() else None,
                    "alg": alg if "alg" in locals() else None,
                    "correlation_id": correlation_id,
                },
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
                    logger.info(
                        "Email domain validation succeeded",
                        extra={
                            "event": "email_domain_validated",
                            "tenant_id": str(tenant_id),
                            "email_domain": email_domain,
                            "correlation_id": correlation_id,
                        },
                    )
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

            # Log user lookup and tenant validation success
            logger.info(
                "User lookup and tenant validation succeeded",
                extra={
                    "event": "user_validated",
                    "tenant_id": str(tenant_id),
                    "user_id": str(user.id),
                    "email_domain": email.split("@")[1] if "@" in email else "unknown",
                    "correlation_id": correlation_id,
                },
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
