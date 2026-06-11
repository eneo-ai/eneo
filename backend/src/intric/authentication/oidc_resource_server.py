"""Resource-server validation of IdP-issued OIDC access tokens.

When ``oidc_resource_server_enabled`` is on, bearer tokens that fail the
HS256 Eneo-JWT decode are validated here instead: RS256-family signature
against the issuer's JWKS (fetched via OIDC discovery, cached in-process),
plus ``iss``/``aud``/``exp`` claims.

Every token problem — opaque tokens, unknown keys, bad claims — surfaces as
``AuthenticationException`` (HTTP 401), never a 500.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any

import jwt

from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.exceptions import AuthenticationException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.authentication.auth_service import AuthService

logger = get_logger(__name__)

# Asymmetric signature algorithms accepted for IdP access tokens.
RS256_FAMILY = ["RS256", "RS384", "RS512"]


class JWKSFetchError(Exception):
    """Raised when the discovery document or JWKS cannot be fetched."""


async def _fetch_json(url: str) -> dict[str, Any]:
    async with aiohttp_client().get(url) as resp:
        if resp.status != 200:
            raise JWKSFetchError(f"HTTP {resp.status} fetching {url}")
        return await resp.json()


class JWKSCache:
    """In-process JWKS cache keyed by issuer, with TTL and rotation refetch.

    A token whose ``kid`` is not in the cached key set triggers exactly one
    refetch (key rotation); the lookup fails if the key is still unknown.
    """

    def __init__(self):
        self._issuer: str | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_signing_key(
        self, *, issuer: str, kid: str, ttl_seconds: int
    ) -> jwt.PyJWK:
        async with self._lock:
            expired = (
                self._issuer != issuer
                or time.monotonic() - self._fetched_at > ttl_seconds
            )
            if expired:
                await self._refresh(issuer)

            key = self._keys.get(kid)
            if key is None and not expired:
                # Unknown kid on a fresh-enough cache: refetch once in case
                # the IdP rotated its keys.
                await self._refresh(issuer)
                key = self._keys.get(kid)

            if key is None:
                raise AuthenticationException("Could not validate token credentials.")
            return key

    async def _refresh(self, issuer: str) -> None:
        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        discovery = await _fetch_json(discovery_url)

        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise JWKSFetchError(f"No jwks_uri in discovery document at {issuer}")

        jwks = await _fetch_json(jwks_uri)

        keys: dict[str, jwt.PyJWK] = {}
        for jwk_data in jwks.get("keys", []):
            kid = jwk_data.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = jwt.PyJWK.from_dict(jwk_data)
            except jwt.PyJWTError:
                logger.warning(
                    "Skipping unusable JWK from issuer",
                    extra={"issuer": issuer, "kid": kid},
                )

        self._issuer = issuer
        self._keys = keys
        self._fetched_at = time.monotonic()

        logger.info(
            "Refreshed JWKS for OIDC resource-server validation",
            extra={"issuer": issuer, "key_count": len(keys)},
        )


# Process-wide cache shared across requests.
_jwks_cache = JWKSCache()


async def validate_idp_access_token(
    token: str,
    *,
    auth_service: "AuthService",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Validate an IdP access token and return its claims payload.

    Raises ``AuthenticationException`` for any token problem (opaque token,
    unknown signing key, bad signature/iss/aud/exp, missing configuration).
    """
    settings = get_settings()
    issuer = settings.oidc_accepted_issuer
    audience = settings.oidc_accepted_audience

    if not issuer or not audience:
        logger.error(
            "OIDC resource-server mode enabled but OIDC_ACCEPTED_ISSUER or "
            "OIDC_ACCEPTED_AUDIENCE is not configured",
            extra={"correlation_id": correlation_id},
        )
        raise AuthenticationException("Could not validate token credentials.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        # Opaque / non-JWT bearer token.
        raise AuthenticationException("Could not validate token credentials.")

    if header.get("alg") not in RS256_FAMILY:
        raise AuthenticationException("Could not validate token credentials.")

    kid = header.get("kid")
    if not kid:
        raise AuthenticationException("Could not validate token credentials.")

    try:
        signing_key = await _jwks_cache.get_signing_key(
            issuer=issuer,
            kid=kid,
            ttl_seconds=settings.oidc_jwks_cache_ttl_seconds,
        )
    except AuthenticationException:
        raise
    except Exception as e:
        logger.error(
            "Failed to fetch JWKS for IdP token validation",
            extra={
                "issuer": issuer,
                "error_type": type(e).__name__,
                "error": str(e),
                "correlation_id": correlation_id,
            },
        )
        raise AuthenticationException("Could not validate token credentials.")

    try:
        payload = auth_service.get_payload_from_idp_access_token(
            access_token=token,
            key=signing_key,
            signing_algos=RS256_FAMILY,
            audience=audience,
            issuer=issuer,
            correlation_id=correlation_id,
        )
    except jwt.PyJWTError:
        raise AuthenticationException("Could not validate token credentials.")

    return payload


def reset_jwks_cache() -> None:
    """Drop cached JWKS state (test hook and operational escape hatch)."""
    global _jwks_cache
    _jwks_cache = JWKSCache()
