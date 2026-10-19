"""Eneo's OAuth client identity.

Per the MCP authorization spec, a client that has no prior relationship with
an authorization server identifies itself with a Client ID Metadata Document:
an HTTPS URL that is both its ``client_id`` and the location of a JSON
document describing it. Eneo serves that document from the backend under the
deployment's public origin. Dynamic Client Registration is the fallback for
authorization servers that do not support metadata documents.

Eneo has two such identities. The public one (``token_endpoint_auth_method:
none``) relies on PKCE alone, which binds the code to the backend that
started the flow. The confidential one authenticates with ``private_key_jwt``
against the deployment's published JWKS, and is used whenever the
authorization server supports that method. A vendor that insists on its own
registration is served by an admin-entered pre-registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from eneo.main.config import Settings

CLIENT_METADATA_PATH = "/mcp-oauth/client.json"
CONFIDENTIAL_CLIENT_METADATA_PATH = "/mcp-oauth/client-confidential.json"
JWKS_PATH = "/mcp-oauth/jwks.json"
CALLBACK_PATH = "/mcp-oauth/callback"
CONNECT_PATH = "/mcp-oauth/connect"
CLIENT_NAME = "Eneo"
SIGNING_ALGORITHM = "ES256"


def public_origin(settings: Settings) -> Optional[str]:
    origin = settings.public_origin
    return origin.rstrip("/") if origin else None


def _api_base(settings: Settings, *, https_only: bool) -> Optional[str]:
    origin = public_origin(settings)
    if origin is None or (https_only and not origin.startswith("https://")):
        return None
    return f"{origin}{settings.api_prefix.rstrip('/')}"


def client_metadata_url(
    settings: Settings, *, confidential: bool = False
) -> Optional[str]:
    """The CIMD URL, or None when the deployment has no public origin.

    Only an https URL is a valid client id (the spec and every authorization
    server require it), so a localhost deployment gets None and falls back to
    Dynamic Client Registration.
    """
    base = _api_base(settings, https_only=True)
    if base is None:
        return None
    path = CONFIDENTIAL_CLIENT_METADATA_PATH if confidential else CLIENT_METADATA_PATH
    return f"{base}{path}"


def jwks_url(settings: Settings) -> Optional[str]:
    """Where the authorization server fetches Eneo's public signing keys."""
    base = _api_base(settings, https_only=False)
    return f"{base}{JWKS_PATH}" if base is not None else None


def redirect_uri(settings: Settings) -> Optional[str]:
    origin = public_origin(settings)
    return f"{origin}{CALLBACK_PATH}" if origin else None


def connect_url(settings: Settings, mcp_server_id: object) -> Optional[str]:
    """Full-page connect route an API integrator can send a user to."""
    origin = public_origin(settings)
    return f"{origin}{CONNECT_PATH}?server={mcp_server_id}" if origin else None


def _client_description(settings: Settings, *, private_key_jwt: bool) -> dict[str, Any]:
    description: dict[str, Any] = {
        "client_name": CLIENT_NAME,
        "client_uri": public_origin(settings),
        "redirect_uris": [redirect_uri(settings)],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "private_key_jwt" if private_key_jwt else "none",
    }
    if private_key_jwt:
        description["jwks_uri"] = jwks_url(settings)
        description["token_endpoint_auth_signing_alg"] = SIGNING_ALGORITHM
    return description


def client_metadata_document(
    settings: Settings, *, confidential: bool = False
) -> Optional[dict[str, Any]]:
    """The document served at :func:`client_metadata_url`.

    ``client_id`` must equal the document URL byte for byte, and the
    authorization server validates redirect URIs against ``redirect_uris``.
    """
    url = client_metadata_url(settings, confidential=confidential)
    if url is None or redirect_uri(settings) is None:
        return None
    return {
        "client_id": url,
        **_client_description(settings, private_key_jwt=confidential),
    }


def dcr_registration_request(
    settings: Settings, *, private_key_jwt: bool = False
) -> Optional[dict[str, Any]]:
    """The RFC 7591 registration body, for authorization servers without CIMD."""
    if redirect_uri(settings) is None:
        return None
    return {
        **_client_description(settings, private_key_jwt=private_key_jwt),
        # OIDC-flavoured servers constrain redirect URIs by application type;
        # Eneo is a remote web application.
        "application_type": "web",
    }
