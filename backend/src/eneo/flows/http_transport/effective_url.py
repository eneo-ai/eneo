"""The one reading of an HTTP URL a flow may send to.

The same function serves authoring (a stored URL, the test endpoint) and the
runtime sender, and its result is what httpx sends to: the sender passes the
parsed ``url`` on instead of the original text, so no second parser can read a
different host or port. Anything that is not an http(s) URL with a plain host
name or IP literal, a valid port and no credentials is refused before any
transport exists.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

import httpx

# The transports flows speak today. A new transport gets its own constant next
# to its egress adapter; there is no registry to consult.
HTTP_URL_SCHEMES = frozenset({"http", "https"})

_MAX_HOST_LENGTH = 253
_HOST_LABEL = re.compile(r"[a-z0-9_-]{1,63}")


class InvalidHttpUrl(ValueError):
    """The text is not a URL a flow may send to; ``str()`` is the reason."""


@dataclass(frozen=True)
class EffectiveHttpUrl:
    url: httpx.URL
    scheme: str
    # ASCII (IDNA) host, lower case, IPv6 without brackets: exactly what the
    # transport connects to.
    host: str
    # Explicit or default port, always 1..65535.
    port: int


def parse_effective_http_url(value: str) -> EffectiveHttpUrl:
    try:
        url = httpx.URL(value.strip())
        # httpx decodes an internationalised host lazily, when it builds the
        # request; malformed punycode raises there, after a client exists.
        _ = url.host
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise InvalidHttpUrl("HTTP URL is not valid.") from exc
    scheme = url.scheme
    if scheme not in HTTP_URL_SCHEMES:
        raise InvalidHttpUrl(f"Unsupported HTTP URL scheme: '{scheme}'.")
    host = url.raw_host.decode("ascii").lower()
    if not host:
        raise InvalidHttpUrl("HTTP URL must include a hostname.")
    if url.userinfo:
        raise InvalidHttpUrl("HTTP URL must not contain credentials.")
    if not _is_plain_host(host):
        raise InvalidHttpUrl("HTTP URL host is not valid.")
    explicit_port = url.port
    if explicit_port is not None and not 1 <= explicit_port <= 65535:
        raise InvalidHttpUrl("HTTP URL port is not valid.")
    port = explicit_port or (443 if scheme == "https" else 80)
    return EffectiveHttpUrl(url=url, scheme=scheme, host=host, port=port)


def _is_plain_host(host: str) -> bool:
    if ":" in host:
        # An IPv6 literal. A zone identifier names a local interface and has no
        # meaning for a remote destination.
        if "%" in host:
            return False
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
        return True
    name = host[:-1] if host.endswith(".") else host
    return 0 < len(name) <= _MAX_HOST_LENGTH and all(
        _HOST_LABEL.fullmatch(label) for label in name.split(".")
    )
