"""Which MCP server addresses may receive an admin-supplied credential.

A bearer token or API key sent over plain http can be read and replayed by
anyone on the network path. RFC 6750 section 5.3 requires TLS for bearer
tokens, and the MCP security best practices ask clients to require https and
to accept http only for loopback during development. Registration and every
connection the assistant MCP client opens apply this one rule.
"""

from enum import Enum
from urllib.parse import urlsplit

from eneo.main.config import LOOPBACK_HOSTS
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

# Shown to the admin at registration and when a server saved before this rule
# is used; it names neither the address nor the credential.
CREDENTIAL_TRANSPORT_REQUIREMENT = (
    "Eneo sends an MCP server's credential (a bearer token, an API key, or a "
    "user name and password in the address) only over https. Change the "
    "server URL to https://. Plain http is accepted only for localhost, "
    "127.0.0.1 and [::1]."
)


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
    # type: httpx sends it as an Authorization: Basic header.
    carries_userinfo = parts.username is not None or parts.password is not None
    if http_auth_type in _AUTH_TYPES_WITHOUT_ADMIN_CREDENTIAL and not carries_userinfo:
        return None
    if parts.scheme == "https":
        return None
    if parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS:
        return None
    return CredentialTransportViolation.NOT_HTTPS
