"""Which client identity Eneo uses at a server's authorization server.

The order is the spec's: a client the admin pre-registered at the vendor,
then Eneo's Client ID Metadata Document, then a Dynamic Client Registration
remembered for the issuer. Whenever the authorization server supports
``private_key_jwt``, the confidential identity is preferred over the public
one, so Eneo's tokens can only be refreshed by a holder of Eneo's key.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    MCPOAuthClientRegistration,
)
from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import MCPOAuthRepository
from eneo.mcp_servers.infrastructure.oauth import client_metadata
from eneo.mcp_servers.infrastructure.oauth.client_assertion import (
    PRIVATE_KEY_JWT,
    ClientAssertionSigner,
)
from eneo.mcp_servers.infrastructure.oauth.discovery import OAuthServerDiscovery
from eneo.mcp_servers.infrastructure.oauth.token_client import (
    ClientCredential,
    choose_client_auth_method,
)

SignerFactory = Callable[[], Awaitable[ClientAssertionSigner]]

CLIENT_AUTH_METHODS = ("none", PRIVATE_KEY_JWT)


def private_key_jwt_offered(discovery: OAuthServerDiscovery, settings: Any) -> bool:
    """The server accepts ``private_key_jwt`` and we can publish keys to it."""
    return (
        PRIVATE_KEY_JWT in discovery.token_endpoint_auth_methods
        and client_metadata.jwks_url(settings) is not None
    )


async def credential_for_registration(
    registration: MCPOAuthClientRegistration,
    discovery: OAuthServerDiscovery,
    signer: SignerFactory,
) -> ClientCredential:
    """The credential a stored registration was made with."""
    method = (registration.registration_payload or {}).get("token_endpoint_auth_method")
    if method == PRIVATE_KEY_JWT:
        return ClientCredential(
            client_id=registration.client_id,
            client_secret=None,
            auth_method=PRIVATE_KEY_JWT,
            signer=await signer(),
        )
    return ClientCredential(
        client_id=registration.client_id,
        client_secret=registration.client_secret,
        auth_method=choose_client_auth_method(
            registration.client_secret, discovery.token_endpoint_auth_methods
        ),
    )


async def resolve_client_credential(
    *,
    mcp_server_id: Any,
    discovery: OAuthServerDiscovery,
    settings: Any,
    config: dict[str, Any],
    repo: MCPOAuthRepository,
    signer: SignerFactory,
) -> Optional[ClientCredential]:
    """Eneo's identity at this authorization server, or None when only a new
    Dynamic Client Registration can provide one.

    ``config`` is the server's auth config with its secret already in the
    clear.
    """
    client_id = config.get("client_id")
    if isinstance(client_id, str) and client_id:
        secret = config.get("client_secret")
        secret_str = secret if isinstance(secret, str) and secret else None
        # The admin registered the client at the vendor and chose how it
        # authenticates there; the server's advertisement does not override it.
        if config.get("client_auth_method") == PRIVATE_KEY_JWT and not secret_str:
            return ClientCredential(
                client_id=client_id,
                client_secret=None,
                auth_method=PRIVATE_KEY_JWT,
                signer=await signer(),
            )
        return ClientCredential(
            client_id=client_id,
            client_secret=secret_str,
            auth_method=choose_client_auth_method(
                secret_str, discovery.token_endpoint_auth_methods
            ),
        )

    if discovery.supports_cimd:
        if private_key_jwt_offered(discovery, settings):
            confidential = client_metadata.client_metadata_url(
                settings, confidential=True
            )
            if confidential is not None:
                return ClientCredential(
                    client_id=confidential,
                    client_secret=None,
                    auth_method=PRIVATE_KEY_JWT,
                    signer=await signer(),
                )
        public = client_metadata.client_metadata_url(settings)
        if public is not None:
            return ClientCredential(
                client_id=public, client_secret=None, auth_method="none"
            )

    # Registrations are bound to the issuer that made them: a changed
    # authorization server means registering again.
    registration = await repo.get_registration(
        mcp_server_id=mcp_server_id, issuer=discovery.issuer
    )
    if registration is not None:
        return await credential_for_registration(registration, discovery, signer)
    return None


def dcr_request_for(
    discovery: OAuthServerDiscovery, settings: Any
) -> Optional[dict[str, Any]]:
    """The registration body for this server, confidential when it allows."""
    return client_metadata.dcr_registration_request(
        settings, private_key_jwt=private_key_jwt_offered(discovery, settings)
    )
