"""OAuth discovery for the MCP token broker.

Three lookups, all cached with a TTL:

- RFC 9728 protected resource metadata (PRM) for the MCP server: which
  authorization server protects it and what its canonical ``resource``
  identifier is. The ``WWW-Authenticate: Bearer resource_metadata="..."``
  challenge is honoured as the primary hint when the caller has one; the
  well-known locations are the fallback.
- RFC 8414 authorization server metadata (with OIDC discovery as a
  fallback): token endpoint and supported grant profiles. The
  ``id-jag`` grant profile marker is how the broker detects support for
  the MCP Enterprise-Managed Authorization flow.
- The IdP's own OIDC metadata, used to resolve the tenant IdP token
  endpoint instead of assuming the Keycloak URL convention.

The cache is module-level so it survives per-request containers, and
TTL-bound so metadata changes propagate without a process restart. Tests
reset it via :func:`reset_discovery_cache`.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, cast
from urllib.parse import urlsplit

import aiohttp

from eneo.main.logging import get_logger

logger = get_logger(__name__)

DISCOVERY_TIMEOUT_SECONDS = 10
DISCOVERY_CACHE_TTL_SECONDS = 900

ID_JAG_GRANT_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"

_CACHE: dict[str, tuple[float, Any]] = {}


def reset_discovery_cache() -> None:
    """Test seam: drop every cached discovery document."""
    _CACHE.clear()


class DiscoveryError(Exception):
    """A metadata document could not be fetched or failed validation."""


@dataclass(frozen=True)
class ProtectedResourceMetadata:
    """RFC 9728 PRM subset the broker consumes."""

    resource: str
    authorization_servers: tuple[str, ...]
    scopes_supported: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorizationServerMetadata:
    """RFC 8414 / OIDC metadata subset the broker consumes."""

    issuer: str
    token_endpoint: Optional[str]
    grant_profiles_supported: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=lambda: cast("dict[str, Any]", {}))

    @property
    def supports_id_jag(self) -> bool:
        return ID_JAG_GRANT_PROFILE in self.grant_profiles_supported


_RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')


def parse_resource_metadata_challenge(www_authenticate: str) -> Optional[str]:
    """Extract the ``resource_metadata`` URL from a WWW-Authenticate header."""
    match = _RESOURCE_METADATA_RE.search(www_authenticate)
    return match.group(1) if match else None


async def _get_json(url: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=DISCOVERY_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(url, allow_redirects=False) as resp:
                if resp.status != 200:
                    raise DiscoveryError(f"GET {url} returned HTTP {resp.status}")
                try:
                    payload = await resp.json(content_type=None)
                except Exception as exc:
                    raise DiscoveryError(f"GET {url} returned non-JSON body") from exc
                if not isinstance(payload, dict):
                    raise DiscoveryError(f"GET {url} returned a non-object document")
                return cast("dict[str, Any]", payload)
    except (aiohttp.ClientError, OSError, TimeoutError) as exc:
        raise DiscoveryError(f"GET {url} failed: {exc}") from exc


def _cache_get(key: str) -> Any | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expiry, value = entry
    if time.monotonic() >= expiry:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    _CACHE[key] = (time.monotonic() + DISCOVERY_CACHE_TTL_SECONDS, value)


class OAuthDiscoveryService:
    """Fetches and caches the metadata documents the broker needs."""

    async def get_protected_resource_metadata(
        self,
        *,
        http_url: str,
        resource_metadata_url: Optional[str] = None,
    ) -> ProtectedResourceMetadata:
        """Resolve the PRM for an MCP server.

        ``resource_metadata_url`` is the WWW-Authenticate challenge hint;
        when present it is fetched first. Otherwise the RFC 9728
        well-known locations are tried: the path-aware document
        (``{origin}/.well-known/oauth-protected-resource{path}``), then
        the origin-level one.
        """
        cache_key = f"prm:{resource_metadata_url or http_url}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        parts = urlsplit(http_url)
        if not parts.scheme or not parts.netloc:
            raise DiscoveryError(f"MCP server URL is not absolute: {http_url!r}")
        origin = f"{parts.scheme}://{parts.netloc}"
        path = parts.path.rstrip("/")

        candidates: list[str] = []
        if resource_metadata_url:
            candidates.append(resource_metadata_url)
        if path:
            candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
        candidates.append(f"{origin}/.well-known/oauth-protected-resource")

        last_error: Optional[Exception] = None
        for url in candidates:
            try:
                payload = await _get_json(url)
            except DiscoveryError as exc:
                last_error = exc
                continue
            servers = payload.get("authorization_servers")
            if not isinstance(servers, list) or not servers:
                last_error = DiscoveryError(
                    f"PRM at {url} lacks a non-empty authorization_servers array"
                )
                continue
            raw_scopes = payload.get("scopes_supported")
            scopes = (
                tuple(str(s) for s in cast("list[Any]", raw_scopes))
                if isinstance(raw_scopes, list)
                else ()
            )
            resource = payload.get("resource")
            metadata = ProtectedResourceMetadata(
                resource=resource if isinstance(resource, str) else http_url,
                authorization_servers=tuple(str(s) for s in cast("list[Any]", servers)),
                scopes_supported=scopes,
            )
            _cache_put(cache_key, metadata)
            return metadata

        raise DiscoveryError(
            f"No protected resource metadata found for {http_url}"
        ) from last_error

    async def get_authorization_server_metadata(
        self, *, issuer: str
    ) -> AuthorizationServerMetadata:
        """Resolve AS metadata for an issuer.

        Tries RFC 8414 (well-known inserted between host and path, then
        appended to the issuer) before OIDC discovery, since only the
        OAuth document carries ``authorization_grant_profiles_supported``.
        """
        normalized = issuer.rstrip("/")
        cache_key = f"as:{normalized}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        parts = urlsplit(normalized)
        if not parts.scheme or not parts.netloc:
            raise DiscoveryError(f"Issuer is not an absolute URL: {issuer!r}")
        origin = f"{parts.scheme}://{parts.netloc}"
        path = parts.path.rstrip("/")

        candidates = [f"{origin}/.well-known/oauth-authorization-server{path}"]
        if path:
            candidates.append(f"{normalized}/.well-known/oauth-authorization-server")
        candidates.append(f"{normalized}/.well-known/openid-configuration")

        last_error: Optional[Exception] = None
        for url in candidates:
            try:
                payload = await _get_json(url)
            except DiscoveryError as exc:
                last_error = exc
                continue
            doc_issuer = payload.get("issuer")
            if not isinstance(doc_issuer, str) or doc_issuer.rstrip("/") != normalized:
                last_error = DiscoveryError(
                    f"AS metadata at {url} has issuer {doc_issuer!r}, "
                    f"expected {normalized!r}"
                )
                continue
            token_endpoint = payload.get("token_endpoint")
            raw_profiles = payload.get("authorization_grant_profiles_supported")
            profiles = (
                tuple(str(p) for p in cast("list[Any]", raw_profiles))
                if isinstance(raw_profiles, list)
                else ()
            )
            metadata = AuthorizationServerMetadata(
                issuer=normalized,
                token_endpoint=(
                    token_endpoint if isinstance(token_endpoint, str) else None
                ),
                grant_profiles_supported=profiles,
                raw=payload,
            )
            _cache_put(cache_key, metadata)
            return metadata

        raise DiscoveryError(
            f"No authorization server metadata found for issuer {issuer}"
        ) from last_error

    async def resolve_token_endpoint(self, *, issuer: str) -> str:
        """Token endpoint for an issuer, via metadata with a Keycloak fallback.

        The fallback keeps existing Keycloak deployments working when the
        metadata document is unreachable (e.g. network-restricted
        environments); other IdPs must be discoverable or configure
        ``token_endpoint`` explicitly.
        """
        try:
            metadata = await self.get_authorization_server_metadata(issuer=issuer)
        except DiscoveryError:
            metadata = None
        if metadata is not None and metadata.token_endpoint:
            return metadata.token_endpoint
        fallback = f"{issuer.rstrip('/')}/protocol/openid-connect/token"
        logger.warning(
            "AS metadata unavailable for issuer %s; falling back to the "
            "Keycloak token endpoint convention %s",
            issuer,
            fallback,
        )
        return fallback
