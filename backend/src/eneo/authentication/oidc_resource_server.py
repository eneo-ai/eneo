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

from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.authentication.auth_service import AuthService

logger = get_logger(__name__)

# Asymmetric signature algorithms accepted for IdP access tokens.
RS256_FAMILY = ["RS256", "RS384", "RS512"]
JWKS_REFRESH_COOLDOWN_SECONDS = 30


class JWKSFetchError(Exception):
    """Raised when the discovery document or JWKS cannot be fetched."""


async def _fetch_json(url: str) -> dict[str, Any]:
    async with aiohttp_client().get(url) as resp:
        if resp.status != 200:
            raise JWKSFetchError(f"HTTP {resp.status} fetching {url}")
        return await resp.json()


class JWKSCache:
    """In-process JWKS cache for one key source, with TTL and rotation refetch.

    The source is the ``jwks_uri`` when given, else the issuer's discovery;
    the cache starts over only when the source changes, so issuers sharing
    one JWKS address share its keys and its cooldown. Unknown key IDs may
    trigger one rotation refresh per cooldown, independent of the
    attacker-chosen ID. Valid cached keys never wait for that network
    request. Failed or expired refreshes are bounded by the same cooldown.
    """

    def __init__(self):
        self._source: str | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._refresh_retry_at = 0.0
        self._rotation_retry_at = 0.0
        self._lock = asyncio.Lock()

    async def get_signing_key(
        self, *, issuer: str, kid: str, ttl_seconds: int, jwks_uri: str | None = None
    ) -> jwt.PyJWK:
        source = jwks_uri or issuer
        now = time.monotonic()
        if (
            self._source == source
            and self._fetched_at is not None
            and now - self._fetched_at <= ttl_seconds
        ):
            key = self._keys.get(kid)
            if key is not None:
                return key

        async with self._lock:
            if self._source != source:
                self._source = source
                self._keys = {}
                self._fetched_at = None
                self._refresh_retry_at = self._rotation_retry_at = 0.0

            now = time.monotonic()
            expired = self._fetched_at is None or now - self._fetched_at > ttl_seconds
            key = self._keys.get(kid)
            if key is not None and not expired:
                return key

            retry_at = self._refresh_retry_at if expired else self._rotation_retry_at
            if now < retry_at:
                raise AuthenticationException("Could not validate token credentials.")

            # Mark the attempt before I/O, so an outage cannot turn every
            # waiting request into another discovery/JWKS fetch.
            self._refresh_retry_at = now + JWKS_REFRESH_COOLDOWN_SECONDS
            if not expired:
                self._rotation_retry_at = now + JWKS_REFRESH_COOLDOWN_SECONDS
            await self._refresh(issuer, jwks_uri)
            self._refresh_retry_at = 0.0
            key = self._keys.get(kid)

            if key is None:
                self._rotation_retry_at = (
                    time.monotonic() + JWKS_REFRESH_COOLDOWN_SECONDS
                )
                raise AuthenticationException("Could not validate token credentials.")
            return key

    async def _refresh(self, issuer: str, jwks_uri: str | None = None) -> None:
        if jwks_uri is None:
            discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
            discovery = await _fetch_json(discovery_url)
            jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise JWKSFetchError(f"No jwks_uri in discovery document at {issuer}")

        jwks = await _fetch_json(jwks_uri)

        keys: dict[str, jwt.PyJWK] = {}
        for jwk_data in jwks.get("keys", []):
            kid = jwk_data.get("kid")
            # As PyJWKClient: only keys for signing, never one marked for
            # encryption.
            if not kid or jwk_data.get("use") not in ("sig", None):
                continue
            try:
                keys[kid] = jwt.PyJWK.from_dict(jwk_data)
            except jwt.PyJWTError:
                logger.warning(
                    "Skipping unusable JWK from issuer",
                    extra={"issuer": issuer, "kid": kid},
                )

        self._keys = keys
        self._fetched_at = time.monotonic()

        logger.info(
            "Refreshed JWKS for OIDC resource-server validation",
            extra={"issuer": issuer, "key_count": len(keys)},
        )


# Process-wide cache shared across requests.
_jwks_cache = JWKSCache()
# The sign-in callback's keys, one cache per provider's JWKS address, so
# organisations with different providers never evict each other's keys.
_federation_jwks_caches: dict[str, JWKSCache] = {}


async def get_federation_signing_key(
    *, issuer: str, jwks_uri: str, kid: str, ttl_seconds: int
) -> jwt.PyJWK:
    """The provider's signing key for an ID token, from the shared cache."""
    cache = _federation_jwks_caches.setdefault(jwks_uri, JWKSCache())
    return await cache.get_signing_key(
        issuer=issuer, kid=kid, ttl_seconds=ttl_seconds, jwks_uri=jwks_uri
    )


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
    if not isinstance(kid, str) or not kid:
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
    _federation_jwks_caches.clear()
