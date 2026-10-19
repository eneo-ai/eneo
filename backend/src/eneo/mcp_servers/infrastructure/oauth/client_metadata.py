"""Eneo's OAuth client identity.

Per the MCP authorization spec, a client that has no prior relationship with
an authorization server identifies itself with a Client ID Metadata Document:
an HTTPS URL that is both its ``client_id`` and the location of a JSON
document describing it. Eneo serves that document from the backend under the
deployment's public origin. Dynamic Client Registration is the fallback for
authorization servers that do not support metadata documents.

Eneo is a public client here (``token_endpoint_auth_method: none``): PKCE
binds the code to the backend that started the flow, and a vendor that insists
on client authentication is served by an admin-entered pre-registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from eneo.main.config import Settings

CLIENT_METADATA_PATH = "/mcp-oauth/client.json"
CALLBACK_PATH = "/mcp-oauth/callback"
CONNECT_PATH = "/mcp-oauth/connect"
CLIENT_NAME = "Eneo"


def public_origin(settings: Settings) -> Optional[str]:
    origin = settings.public_origin
    return origin.rstrip("/") if origin else None


def client_metadata_url(settings: Settings) -> Optional[str]:
    """The CIMD URL, or None when the deployment has no public origin.

    Only an https URL is a valid client id (the spec and every authorization
    server require it), so a localhost deployment gets None and falls back to
    Dynamic Client Registration.
    """
    origin = public_origin(settings)
    if origin is None or not origin.startswith("https://"):
        return None
    return f"{origin}{settings.api_prefix.rstrip('/')}{CLIENT_METADATA_PATH}"


def redirect_uri(settings: Settings) -> Optional[str]:
    origin = public_origin(settings)
    return f"{origin}{CALLBACK_PATH}" if origin else None


def connect_url(settings: Settings, mcp_server_id: object) -> Optional[str]:
    """Full-page connect route an API integrator can send a user to."""
    origin = public_origin(settings)
    return f"{origin}{CONNECT_PATH}?server={mcp_server_id}" if origin else None


def client_metadata_document(settings: Settings) -> Optional[dict[str, Any]]:
    """The document served at :func:`client_metadata_url`.

    ``client_id`` must equal the document URL byte for byte, and the
    authorization server validates redirect URIs against ``redirect_uris``.
    """
    url = client_metadata_url(settings)
    callback = redirect_uri(settings)
    if url is None or callback is None:
        return None
    return {
        "client_id": url,
        "client_name": CLIENT_NAME,
        "client_uri": public_origin(settings),
        "redirect_uris": [callback],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


def dcr_registration_request(settings: Settings) -> Optional[dict[str, Any]]:
    """The RFC 7591 registration body, for authorization servers without CIMD."""
    callback = redirect_uri(settings)
    if callback is None:
        return None
    return {
        "client_name": CLIENT_NAME,
        "client_uri": public_origin(settings),
        "redirect_uris": [callback],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        # OIDC-flavoured servers constrain redirect URIs by application type;
        # Eneo is a remote web application.
        "application_type": "web",
    }
