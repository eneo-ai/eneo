"""Which MCP server addresses may receive an admin-supplied credential."""

import pytest

from eneo.mcp_servers.domain.credential_transport import (
    CredentialTransportViolation,
    credential_transport_violation,
)

NOT_HTTPS = CredentialTransportViolation.NOT_HTTPS


# Kills: the rule never refusing http (returns None), flagging only one of the
# credential types, refusing https, dropping one of the three loopback hosts,
# matching the host by prefix, suffix or 127. range or on the raw netloc
# (userinfo), exempting an unknown auth type instead of failing closed, raising
# on an address the parser rejects, and ignoring a user name and password in
# the address (httpx sends them as Basic auth) when the auth type sends none.
# The Eneo-owned rows ("internal", "bundled") and "none" without userinfo send
# no admin-supplied credential and stay unaffected.
@pytest.mark.parametrize(
    ("auth_type", "url", "expected"),
    [
        ("bearer", "http://mcp.example.org/mcp", NOT_HTTPS),
        ("api_key_header", "http://mcp.example.org/mcp", NOT_HTTPS),
        ("future_auth_type", "http://mcp.example.org/mcp", NOT_HTTPS),
        ("bearer", "https://mcp.example.org/mcp", None),
        ("api_key_header", "HTTPS://MCP.example.org/mcp", None),
        ("bearer", "http://localhost:8080/mcp", None),
        ("bearer", "http://127.0.0.1/mcp", None),
        ("api_key_header", "http://[::1]:9000/mcp", None),
        ("bearer", "http://localhost.evil.example/mcp", NOT_HTTPS),
        ("bearer", "http://evil.localhost/mcp", NOT_HTTPS),
        ("bearer", "http://127.0.0.2/mcp", NOT_HTTPS),
        ("bearer", "http://0.0.0.0/mcp", NOT_HTTPS),
        ("bearer", "http://127.0.0.1@evil.example/mcp", NOT_HTTPS),
        ("bearer", "ftp://mcp.example.org/mcp", NOT_HTTPS),
        ("bearer", "http://[::1/mcp", NOT_HTTPS),
        ("none", "http://mcp.example.org/mcp", None),
        ("none", "http://alice:hunter2@mcp.example.org/mcp", NOT_HTTPS),
        ("none", "https://alice:hunter2@mcp.example.org/mcp", None),
        (
            "internal",
            "http://eneo-backend:8000/internal-mcp/image_generation/mcp",
            None,
        ),
        ("bundled", "http://tool-runtime:8080/mcp/compute", None),
    ],
)
def test_credential_needs_https_except_on_loopback(auth_type, url, expected):
    assert credential_transport_violation(auth_type, url) is expected
