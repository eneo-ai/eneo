"""JWKS caching with Redis for multi-worker deployments.

Provides simple, reliable caching of JSON Web Key Sets to avoid
repeated network fetches during authentication.
"""

import asyncio
import json
import time
from typing import Any
from uuid import UUID

from intric.main.logging import get_logger

logger = get_logger(__name__)

# Module-level locks for per-process singleflight
_JWKS_LOCKS: dict[str, asyncio.Lock] = {}

# Cache configuration
DEFAULT_TTL_SECONDS = 3600  # 1 hour (like PyJWKClient behavior)
MIN_TTL_SECONDS = 300  # 5 minutes minimum
MAX_TTL_SECONDS = 86400  # 24 hours maximum


def _get_lock(jwks_uri: str) -> asyncio.Lock:
    """Get or create asyncio.Lock for singleflight per JWKS URI."""
    if jwks_uri not in _JWKS_LOCKS:
        _JWKS_LOCKS[jwks_uri] = asyncio.Lock()
    return _JWKS_LOCKS[jwks_uri]


def _parse_cache_control_max_age(headers: dict) -> int | None:
    """Extract max-age from Cache-Control header if present."""
    cache_control = headers.get("cache-control", "")
    if not cache_control:
        return None

    for directive in cache_control.split(","):
        directive = directive.strip()
        if directive.startswith("max-age="):
            try:
                return int(directive.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
    return None


async def get_jwks(
    jwks_uri: str,
    tenant_id: UUID,
    correlation_id: str,
    provider: str,
    redis_client,
    fetch_function,
) -> dict[str, Any]:
    """
    Get JWKS with Redis caching.

    Implements caching similar to PyJWKClient's internal cache:
    - Caches JWKS in Redis (shared across workers)
    - Respects HTTP Cache-Control headers
    - Falls back to fetch if cache miss or Redis unavailable

    Args:
        jwks_uri: JWKS endpoint URL
        tenant_id: Tenant UUID for logging
        correlation_id: Request correlation ID
        provider: IdP provider name
        redis_client: Redis async client (can be None for degraded mode)
        fetch_function: Async function to fetch JWKS (should be _make_idp_http_request wrapper)

    Returns:
        JWKS data dict with "keys" array
    """
    cache_key = f"jwks:{jwks_uri}"

    # Guard: If Redis unavailable, skip caching entirely (degraded mode)
    if not redis_client:
        logger.warning(
            "Redis unavailable - fetching JWKS without caching (degraded mode)",
            extra={
                "tenant_id": str(tenant_id),
                "correlation_id": correlation_id,
                "jwks_uri": jwks_uri,
                "provider": provider,
            },
        )
        jwks_bytes, jwks_status, jwks_headers = await fetch_function()
        if jwks_status != 200:
            raise Exception(f"JWKS fetch returned HTTP {jwks_status}")
        jwks_data = json.loads(jwks_bytes)
        if "keys" not in jwks_data or not isinstance(jwks_data["keys"], list):
            raise ValueError(f"Invalid JWKS structure from {jwks_uri}")
        return jwks_data

    # Try Redis cache first
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.debug(
                "JWKS cache HIT (Redis)",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                    "provider": provider,
                    "cache_key": cache_key,
                },
            )
            return json.loads(cached_data)
    except Exception as e:
        logger.warning(
            f"Redis cache read failed for JWKS: {e}",
            extra={
                "tenant_id": str(tenant_id),
                "correlation_id": correlation_id,
                "jwks_uri": jwks_uri,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        # Continue to fetch (degraded mode)

    # Cache miss - use singleflight to prevent thundering herd within this process
    lock = _get_lock(jwks_uri)
    async with lock:
        # Double-check cache after acquiring lock (another coroutine might have fetched)
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                logger.debug(
                    "JWKS cache HIT (Redis, post-lock double-check)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "jwks_uri": jwks_uri,
                    },
                )
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(
                f"Redis double-check failed after lock acquisition: {e}",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            # Continue to fetch

        # Try to acquire distributed lock (prevent multi-worker thundering herd)
        lock_key = f"jwks:lock:{jwks_uri}"
        lock_acquired = False

        try:
            # Redis SET NX EX for distributed locking
            lock_acquired = await redis_client.set(
                lock_key,
                correlation_id,
                nx=True,  # Only set if not exists
                ex=10,  # 10 second auto-expiry (prevents deadlock)
            )
        except Exception as e:
            logger.warning(
                f"Failed to acquire distributed lock (will fetch anyway): {e}",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                    "error": str(e),
                },
            )
            lock_acquired = False

        # If we didn't get the lock, another worker is fetching - wait and retry cache
        if not lock_acquired:
            logger.debug(
                "Another worker is fetching JWKS - waiting briefly",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                },
            )
            await asyncio.sleep(0.2)  # Wait for other worker to populate cache

            # Retry cache after wait
            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    logger.debug(
                        "JWKS cache populated by another worker",
                        extra={
                            "tenant_id": str(tenant_id),
                            "correlation_id": correlation_id,
                            "jwks_uri": jwks_uri,
                        },
                    )
                    return json.loads(cached_data)
            except Exception as e:
                logger.warning(f"Cache retry after lock wait failed: {e}")
                # Fall through to fetch anyway

        # Fetch from IdP (we have the distributed lock or don't care)
        logger.info(
            "JWKS cache MISS - fetching from IdP",
            extra={
                "tenant_id": str(tenant_id),
                "correlation_id": correlation_id,
                "jwks_uri": jwks_uri,
                "provider": provider,
                "has_distributed_lock": lock_acquired,
            },
        )

        try:
            fetch_start = time.perf_counter()
            jwks_bytes, jwks_status, jwks_headers = await fetch_function()
            fetch_duration_ms = int((time.perf_counter() - fetch_start) * 1000)

            if jwks_status != 200:
                raise Exception(f"JWKS fetch returned HTTP {jwks_status}")

            jwks_data = json.loads(jwks_bytes)

            # Validate JWKS structure
            if "keys" not in jwks_data or not isinstance(jwks_data["keys"], list):
                raise ValueError(f"Invalid JWKS structure from {jwks_uri}")

            # Normalize headers to lowercase for case-insensitive access
            headers_normalized = {k.lower(): v for k, v in jwks_headers.items()}

            # Determine TTL from Cache-Control or use default
            max_age = _parse_cache_control_max_age(headers_normalized)
            if max_age is not None:
                ttl = max(MIN_TTL_SECONDS, min(max_age, MAX_TTL_SECONDS))
            else:
                ttl = DEFAULT_TTL_SECONDS

            # Cache in Redis
            try:
                await redis_client.setex(cache_key, ttl, json.dumps(jwks_data))
                logger.info(
                    "JWKS fetched and cached",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "jwks_uri": jwks_uri,
                        "provider": provider,
                        "fetch_duration_ms": fetch_duration_ms,
                        "ttl_seconds": ttl,
                        "cache_key": cache_key,
                        "keys_count": len(jwks_data.get("keys", [])),
                    },
                )
            except Exception as e:
                logger.warning(
                    f"Failed to cache JWKS in Redis: {e}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "correlation_id": correlation_id,
                        "jwks_uri": jwks_uri,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                # Continue without caching (degraded mode)

            return jwks_data

        finally:
            # Release distributed lock if we acquired it
            if lock_acquired:
                try:
                    await redis_client.delete(lock_key)
                    logger.debug(
                        "Released distributed JWKS lock",
                        extra={
                            "tenant_id": str(tenant_id),
                            "correlation_id": correlation_id,
                            "jwks_uri": jwks_uri,
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to release distributed lock: {e}")
                    # Lock will auto-expire anyway


async def get_signing_key_for_kid(
    jwks_uri: str,
    kid: str,
    tenant_id: UUID,
    correlation_id: str,
    provider: str,
    redis_client,
    fetch_function,
) -> dict[str, Any] | None:
    """
    Get signing key by kid, with automatic cache refresh on kid miss.

    Handles key rotation: if kid not found, forces cache refresh once.

    Args:
        jwks_uri: JWKS endpoint URL
        kid: Key ID to find
        tenant_id: Tenant UUID
        correlation_id: Request correlation ID
        provider: IdP provider name
        redis_client: Redis client
        fetch_function: Function to fetch JWKS

    Returns:
        Signing key dict or None if not found
    """
    # Try with cache
    jwks_data = await get_jwks(jwks_uri, tenant_id, correlation_id, provider, redis_client, fetch_function)

    for key in jwks_data.get("keys", []):
        if key.get("kid") == kid:
            logger.debug(
                "Signing key found in JWKS",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "kid": kid,
                    "jwks_uri": jwks_uri,
                },
            )
            return key

    # Kid not found - might be key rotation
    # Force cache refresh once
    logger.warning(
        "Signing key kid not found in cached JWKS - forcing refresh for key rotation",
        extra={
            "tenant_id": str(tenant_id),
            "correlation_id": correlation_id,
            "kid": kid,
            "jwks_uri": jwks_uri,
            "available_kids": [k.get("kid") for k in jwks_data.get("keys", [])],
        },
    )

    # Invalidate cache and re-fetch
    if redis_client:
        try:
            await redis_client.delete(f"jwks:{jwks_uri}")
            logger.debug(
                "Invalidated JWKS cache for kid rotation",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                    "kid": kid,
                },
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate cache (will fetch anyway): {e}",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "jwks_uri": jwks_uri,
                    "error": str(e),
                },
            )

    # Re-fetch with fresh cache
    jwks_data = await get_jwks(jwks_uri, tenant_id, correlation_id, provider, redis_client, fetch_function)

    for key in jwks_data.get("keys", []):
        if key.get("kid") == kid:
            logger.info(
                "Signing key found after cache refresh (key rotation handled)",
                extra={
                    "tenant_id": str(tenant_id),
                    "correlation_id": correlation_id,
                    "kid": kid,
                    "jwks_uri": jwks_uri,
                },
            )
            return key

    # Still not found after refresh
    logger.error(
        "Signing key kid not found even after cache refresh",
        extra={
            "tenant_id": str(tenant_id),
            "correlation_id": correlation_id,
            "kid": kid,
            "jwks_uri": jwks_uri,
            "available_kids": [k.get("kid") for k in jwks_data.get("keys", [])],
        },
    )
    return None


async def invalidate_jwks_cache(jwks_uri: str, redis_client) -> None:
    """
    Manually invalidate JWKS cache (for admin/debugging).

    Useful for forcing immediate key refresh after known IdP changes.
    """
    cache_key = f"jwks:{jwks_uri}"

    if not redis_client:
        logger.warning("Cannot invalidate JWKS cache - Redis unavailable", extra={"jwks_uri": jwks_uri})
        return

    try:
        await redis_client.delete(cache_key)
        logger.info(f"Invalidated JWKS cache for {jwks_uri}", extra={"cache_key": cache_key})
    except Exception as e:
        logger.error(
            f"Failed to invalidate JWKS cache: {e}",
            extra={"jwks_uri": jwks_uri, "error": str(e), "error_type": type(e).__name__}
        )
