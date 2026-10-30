"""How logs, error messages and audit records name an MCP server."""

import pytest

from eneo.mcp_servers.domain.server_address import (
    UNREADABLE_SERVER_ADDRESS,
    loggable_server_address,
)


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://mcp.example.org/mcp?key=s3cret#part", "https://mcp.example.org"),
        (
            "http://user:s3cret@mcp.example.org:8443/t/s3cret",
            "http://mcp.example.org:8443",
        ),
        ("https://MCP.Example.org", "https://mcp.example.org"),
        ("http://[fd00::5]:9000/mcp", "http://[fd00::5]:9000"),
        ("http://mcp.example.org:not-a-port/mcp", UNREADABLE_SERVER_ADDRESS),
        ("http://[fd00::5/mcp", UNREADABLE_SERVER_ADDRESS),
        ("/mcp?key=s3cret", UNREADABLE_SERVER_ADDRESS),
    ],
)
def test_a_server_is_named_by_its_scheme_host_and_port_only(url: str, shown: str):
    # Kills the mutants that keep the path, query, fragment or user info
    # (where a token or password can be), drop an explicit port, leave an IPv6
    # host without brackets, or let an address that cannot be read raise.
    assert loggable_server_address(url) == shown
