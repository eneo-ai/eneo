"""Every request the backend sends to an OpenID provider.

Discovery, token and JWKS requests, at registration, at a test and at sign-in,
go through ``get_json`` and ``post_form`` on the shared session. Each request:

- uses https, or http only to this machine, which is a provider only in
  development (``loopback_allowed``);
- connects only to addresses ``PROVIDER_POLICY`` allows: private networks yes,
  never link-local, metadata or IPv4-in-IPv6 addresses. The session's
  resolver checks the addresses a name resolves to; aiohttp never resolves an
  IP literal, so ``check_url`` checks those, reading the URL as aiohttp reads
  it (yarl), so a literal spelled with full-width digits or dots is one too;
- does not follow redirects, so a 3xx cannot move a request carrying the code
  and the client secret elsewhere;
- reads at most 256 KiB of the answer.

The shared session's deadline ends a request that takes too long. That, a
provider that cannot be reached, and anything these rules refuse raise
``OidcFetchError`` with a fixed reason that names no address and repeats
nothing the provider sent, so each caller answers with its own fixed refusal.
"""

import ipaddress
import json
from collections.abc import Mapping
from typing import cast

import aiohttp
from yarl import URL

from eneo.crawler.destination_policy import DisallowedDestination
from eneo.main.aiohttp_client import (
    PROVIDER_POLICY,
    aiohttp_client,
    loopback_allowed,
)
from eneo.main.config import LOOPBACK_HOSTS

MAX_RESPONSE_BYTES = 256 * 1024
_CHUNK_BYTES = 64 * 1024

REFUSED_ADDRESS = "the provider's address is not allowed"
UNREACHABLE = "the provider could not be reached"
_TOO_LARGE = "the answer is larger than 256 KiB"


class OidcFetchError(Exception):
    """A request to the provider was refused by these rules."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def check_url(url: str) -> None:
    """Refuse a URL no request to a provider may go to."""
    try:
        parts = URL(url)
        host = parts.raw_host
        port = parts.port
    except ValueError as exc:  # UnicodeError is one too.
        raise OidcFetchError("the URL cannot be read") from exc
    if (
        not host
        or port is None
        or parts.raw_user is not None
        or parts.raw_password is not None
    ):
        raise OidcFetchError("the URL must name a host and no user")
    if host in LOOPBACK_HOSTS:
        if not loopback_allowed():
            raise OidcFetchError(REFUSED_ADDRESS)
        if parts.scheme not in ("https", "http"):
            raise OidcFetchError("the URL must use https")
        return
    if parts.scheme != "https":
        raise OidcFetchError("the URL must use https")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return  # A name: the session's resolver checks its addresses.
    if not PROVIDER_POLICY.allows(literal):
        raise OidcFetchError(REFUSED_ADDRESS)


async def _answer(
    response: aiohttp.ClientResponse,
) -> tuple[int, dict[str, object] | None]:
    status = response.status
    if 300 <= status < 400:
        raise OidcFetchError(
            "the provider answered with a redirect, which is not followed",
            status=status,
        )
    if (response.content_length or 0) > MAX_RESPONSE_BYTES:
        raise OidcFetchError(_TOO_LARGE, status=status)
    body = bytearray()
    async for chunk in response.content.iter_chunked(_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise OidcFetchError(_TOO_LARGE, status=status)
    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError):  # Nested deeper than the parser goes.
        return status, None
    return status, cast(dict[str, object], document) if isinstance(
        document, dict
    ) else None


async def _request(
    method: str,
    url: str,
    *,
    data: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, object] | None]:
    check_url(url)
    session = aiohttp_client()
    try:
        if method == "POST":
            async with session.post(
                url, data=data, headers=headers, allow_redirects=False
            ) as response:
                return await _answer(response)
        async with session.get(url, allow_redirects=False) as response:
            return await _answer(response)
    except DisallowedDestination as exc:
        raise OidcFetchError(REFUSED_ADDRESS) from exc
    except (aiohttp.ClientError, TimeoutError) as exc:
        # Includes aiohttp refusing a host before it connects, such as a
        # legacy numeric IPv4 form (2130706433, 127.1, 0177.0.0.1).
        raise OidcFetchError(UNREACHABLE) from exc


async def get_json(url: str) -> dict[str, object]:
    """GET a JSON object the provider answers with 200."""
    status, document = await _request("GET", url)
    if status != 200:
        raise OidcFetchError(f"HTTP {status}", status=status)
    if document is None:
        raise OidcFetchError("the answer is not a JSON object", status=status)
    return document


async def post_form(
    url: str, data: Mapping[str, str], headers: Mapping[str, str] | None = None
) -> tuple[int, dict[str, object] | None]:
    """POST a form; the status and the answer when it is a JSON object."""
    return await _request("POST", url, data=data, headers=headers)
