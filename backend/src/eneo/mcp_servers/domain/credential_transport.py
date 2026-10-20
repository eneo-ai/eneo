"""Which MCP server addresses may receive an admin-supplied credential.

A bearer token or API key sent over plain http can be read and replayed by
anyone on the network path. RFC 6750 section 5.3 requires TLS for bearer
tokens, and the MCP security best practices ask clients to require https and
to accept http only for loopback during development. Here the unattended
tool decision (server_credential_needs_https) applies the rule.
"""

from enum import Enum
from urllib.parse import urlsplit

from eneo.mcp_servers.domain.entities.mcp_server import (
    BUNDLED_AUTH_TYPE,
    INTERNAL_AUTH_TYPE,
)

# Auth types that send no admin-supplied credential: "none" sends nothing, a
# built-in provider gets a token Eneo mints for its own loopback endpoint, and
# a bundled server gets the deployment's runtime token at the runtime URL the
# deployment configures. Every other auth type, including one added later,
# sends the credential an admin stored, so it fails closed.
_AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL = frozenset(
    {"none", INTERNAL_AUTH_TYPE, BUNDLED_AUTH_TYPE}
)

# The hosts public_origin also accepts over http (main/config.py), plus the
# IPv6 loopback. The MCP client sends requests to them directly, never through
# a proxy from the environment, so a request to them stays on the machine.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class CredentialTransportViolation(Enum):
    NOT_HTTPS = "not_https"


def credential_transport_violation(
    http_auth_type: str, http_url: str
) -> CredentialTransportViolation | None:
    """Why ``http_url`` may not receive the credential the server sends.

    None when neither the auth type nor the address carries an admin-supplied
    credential, the address is https, or it is plain http to a loopback host.
    """
    try:
        parts = urlsplit(http_url)
    except ValueError:
        # An address the parser rejects is not proven to be https or loopback.
        return CredentialTransportViolation.NOT_HTTPS
    # A user name or password in the address is a credential whatever the auth
    # type, because httpx sends it as an Authorization: Basic header.
    carries_userinfo = parts.username is not None or parts.password is not None
    if http_auth_type in _AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL and not carries_userinfo:
        return None
    if parts.scheme == "https":
        return None
    if parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS:
        return None
    return CredentialTransportViolation.NOT_HTTPS
