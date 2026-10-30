"""The type that reads the address an administrator registers for a server."""

from urllib.parse import urlsplit

from pydantic import AnyHttpUrl

# The admin API reads a server's address with this type and stores its text.
# The client asks the same type before its redirect message names an address
# to register instead.
MCPServerAddress = AnyHttpUrl

UNREADABLE_SERVER_ADDRESS = "(an address that cannot be read)"


def loggable_server_address(url: str) -> str:
    """How a log line, an error message or an audit record names the server
    at ``url``: its scheme, host and explicit port.

    The path and query of a registered address can carry a token and its
    user info a password, so neither is ever part of it.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return UNREADABLE_SERVER_ADDRESS
    if not parts.scheme or not host:
        return UNREADABLE_SERVER_ADDRESS
    shown_host = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown_host}" + ("" if port is None else f":{port}")
