"""Authorization server discovery for an MCP server.

Follows the MCP authorization spec: the server's Protected Resource Metadata
(RFC 9728, found through the ``WWW-Authenticate`` challenge or the well-known
locations) names its authorization server; that server's metadata (RFC 8414,
with OpenID Connect discovery as the fallback the spec requires) names the
endpoints and the registration and grant features it supports. Metadata is
validated the way the spec demands: the resource must match the server URL
and the issuer must match the URL the document was fetched for.

Documents are cached per server URL with a TTL so a tool call never pays for
discovery, while metadata changes still propagate without a restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, cast

import httpx
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    validate_metadata_issuer,
)
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from mcp.types import LATEST_PROTOCOL_VERSION

from eneo.main.logging import get_logger

logger = get_logger(__name__)

DISCOVERY_TIMEOUT_SECONDS = 10.0
DISCOVERY_CACHE_TTL_SECONDS = 900.0

ID_JAG_GRANT_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
CLIENT_CREDENTIALS_GRANT = "client_credentials"


class OAuthDiscoveryError(Exception):
    """The server is not an OAuth-protected MCP server we can work with."""


@dataclass(frozen=True)
class OAuthChallenge:
    """What a 401 or 403 from the MCP server told us."""

    status_code: int
    resource_metadata_url: Optional[str]
    scope: Optional[str]
    error: Optional[str]


@dataclass(frozen=True)
class OAuthServerDiscovery:
    server_url: str
    resource: str
    issuer: str
    protected_resource: Optional[ProtectedResourceMetadata]
    authorization_server: OAuthMetadata
    raw_authorization_server: dict[str, Any]
    challenge_scope: Optional[str]

    @property
    def authorization_endpoint(self) -> str:
        return str(self.authorization_server.authorization_endpoint)

    @property
    def token_endpoint(self) -> str:
        return str(self.authorization_server.token_endpoint)

    @property
    def registration_endpoint(self) -> Optional[str]:
        endpoint = self.authorization_server.registration_endpoint
        return str(endpoint) if endpoint is not None else None

    @property
    def revocation_endpoint(self) -> Optional[str]:
        endpoint = self.authorization_server.revocation_endpoint
        return str(endpoint) if endpoint is not None else None

    @property
    def supports_cimd(self) -> bool:
        return self.authorization_server.client_id_metadata_document_supported is True

    @property
    def supports_dcr(self) -> bool:
        return self.registration_endpoint is not None

    @property
    def grant_types_supported(self) -> tuple[str, ...]:
        # RFC 8414: absent means authorization_code and implicit.
        grants = self.authorization_server.grant_types_supported
        return tuple(grants) if grants is not None else ("authorization_code",)

    @property
    def supports_client_credentials(self) -> bool:
        return CLIENT_CREDENTIALS_GRANT in self.grant_types_supported

    @property
    def supports_id_jag(self) -> bool:
        """The Enterprise-Managed Authorization extension is advertised."""
        profiles = self.raw_authorization_server.get(
            "authorization_grant_profiles_supported"
        )
        if not isinstance(profiles, list):
            return False
        return ID_JAG_GRANT_PROFILE in cast(list[object], profiles)

    @property
    def token_endpoint_auth_methods(self) -> tuple[str, ...]:
        methods = self.authorization_server.token_endpoint_auth_methods_supported
        # RFC 8414: absent means client_secret_basic.
        return tuple(methods) if methods is not None else ("client_secret_basic",)

    def default_scope(self) -> Optional[str]:
        """The spec's scope selection: the challenge's scope, else the PRM's
        ``scopes_supported``, else nothing."""
        if self.challenge_scope:
            return self.challenge_scope
        if (
            self.protected_resource is not None
            and self.protected_resource.scopes_supported
        ):
            return " ".join(self.protected_resource.scopes_supported)
        return None


_CACHE: dict[str, tuple[float, OAuthServerDiscovery]] = {}


def reset_discovery_cache() -> None:
    """Test seam."""
    _CACHE.clear()


def parse_challenge(response: httpx.Response) -> Optional[OAuthChallenge]:
    """The bearer challenge of a 401 or 403, or None for any other response."""
    if response.status_code not in (401, 403):
        return None
    return OAuthChallenge(
        status_code=response.status_code,
        resource_metadata_url=extract_resource_metadata_from_www_auth(response),
        scope=extract_field_from_www_auth(response, "scope"),
        error=extract_field_from_www_auth(response, "error"),
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(DISCOVERY_TIMEOUT_SECONDS), follow_redirects=False
    )


async def probe_challenge(server_url: str) -> Optional[OAuthChallenge]:
    """Send one unauthenticated MCP request to read the server's challenge.

    Authorization is evaluated before method dispatch, so an ``initialize``
    body is the least surprising probe. A server that answers anything but
    401 or 403 is not asking for a token and yields None.
    """
    try:
        async with _client() as http:
            response = await http.post(
                server_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "eneo", "version": "0.1"},
                    },
                },
            )
    except httpx.HTTPError as exc:
        raise OAuthDiscoveryError(f"Could not reach {server_url}: {exc}") from exc
    return parse_challenge(response)


async def _get_json(http: httpx.AsyncClient, url: str) -> Optional[dict[str, Any]]:
    try:
        response = await http.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.debug("Discovery GET %s failed: %s", url, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        payload: object = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


async def discover(
    server_url: str,
    *,
    challenge: Optional[OAuthChallenge] = None,
    force: bool = False,
) -> OAuthServerDiscovery:
    """Resolve the authorization server protecting ``server_url``.

    ``challenge`` is the server's own 401, when the caller has one; otherwise
    the server is probed for it so the ``resource_metadata`` hint and the
    required scope are honoured.
    """
    cached = _CACHE.get(server_url)
    if cached is not None and not force:
        expiry, discovery = cached
        if time.monotonic() < expiry:
            return discovery

    if challenge is None:
        challenge = await probe_challenge(server_url)
    if challenge is None:
        raise OAuthDiscoveryError(
            "The server did not ask for authorization (no 401 or 403 challenge); "
            "it is not protected by OAuth."
        )

    async with _client() as http:
        prm: Optional[ProtectedResourceMetadata] = None
        for url in build_protected_resource_metadata_discovery_urls(
            challenge.resource_metadata_url, server_url
        ):
            payload = await _get_json(http, url)
            if payload is None:
                continue
            try:
                candidate = ProtectedResourceMetadata.model_validate(payload)
            except ValueError as exc:
                logger.debug("Invalid protected resource metadata at %s: %s", url, exc)
                continue
            # RFC 8707: the metadata must describe this very server.
            if not check_resource_allowed(
                requested_resource=resource_url_from_server_url(server_url),
                configured_resource=str(candidate.resource),
            ):
                raise OAuthDiscoveryError(
                    f"Protected resource metadata at {url} describes "
                    f"{candidate.resource}, not {server_url}"
                )
            prm = candidate
            break

        if prm is not None:
            auth_server_url: Optional[str] = str(prm.authorization_servers[0])
            resource = str(prm.resource)
        else:
            # Pre-RFC 9728 servers: the authorization server is the resource
            # server's own origin. Kept for interoperability.
            auth_server_url = None
            resource = resource_url_from_server_url(server_url)

        asm: Optional[OAuthMetadata] = None
        raw_asm: dict[str, Any] = {}
        expected_issuer = auth_server_url or _origin(server_url)
        for url in build_oauth_authorization_server_metadata_discovery_urls(
            auth_server_url, server_url
        ):
            payload = await _get_json(http, url)
            if payload is None:
                continue
            try:
                candidate_asm = OAuthMetadata.model_validate(payload)
            except ValueError as exc:
                logger.debug(
                    "Invalid authorization server metadata at %s: %s", url, exc
                )
                continue
            # RFC 8414 section 3.3: the document must name the issuer it was
            # fetched for, or it belongs to someone else.
            try:
                validate_metadata_issuer(candidate_asm, expected_issuer)
            except OAuthFlowError as exc:
                raise OAuthDiscoveryError(str(exc)) from exc
            asm = candidate_asm
            raw_asm = payload
            break

    if asm is None:
        raise OAuthDiscoveryError(
            f"No authorization server metadata found for {expected_issuer}"
        )

    discovery = OAuthServerDiscovery(
        server_url=server_url,
        resource=resource.rstrip("/") if resource.endswith("/") else resource,
        issuer=str(asm.issuer).rstrip("/")
        if str(asm.issuer).endswith("/")
        else str(asm.issuer),
        protected_resource=prm,
        authorization_server=asm,
        raw_authorization_server=raw_asm,
        challenge_scope=challenge.scope,
    )
    _CACHE[server_url] = (time.monotonic() + DISCOVERY_CACHE_TTL_SECONDS, discovery)
    return discovery


def _origin(url: str) -> str:
    parsed = httpx.URL(url)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.host}{port}"
