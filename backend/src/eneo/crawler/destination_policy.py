"""Where the backend may connect: the website crawler and the requests to an
OpenID provider.

The crawler may connect to public and private (intranet) unicast addresses,
but never to loopback, link-local, unspecified, multicast, IPv4-in-IPv6
transition addresses or the known cloud metadata endpoints. Operators who do
not crawl intranet sites can set CRAWLER_BLOCK_PRIVATE_NETWORKS to also refuse
private ranges.

The Python crawler enforces the policy in its name resolver, so it applies to
the addresses a connection actually uses: start URLs, redirects, followed
links, sitemap entries, robots.txt and file downloads. A DNS answer is used
only when every address in it is allowed.

``PolicyResolver`` applies the policy the same way for any aiohttp session.
aiohttp does not resolve an IP literal, so a caller checks a literal host
itself.

This module deliberately has no application imports so it is identical on every
release branch.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Collection

from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# NAT64 well-known prefix (RFC 6052). It embeds an IPv4 destination, so a
# blocked IPv4 address could otherwise be reached through a NAT64 gateway.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

# Cloud instance metadata endpoints that are not link-local: AWS IMDS over
# IPv6 (unique-local) and Alibaba Cloud (carrier-grade NAT range). The
# link-local 169.254.169.254 is covered by the link-local rule.
_METADATA_ENDPOINTS = (
    ipaddress.ip_network("fd00:ec2::254/128"),
    ipaddress.ip_network("100.100.100.200/32"),
)


class DestinationPolicy:
    def __init__(self, block_private_networks: bool = False) -> None:
        self.block_private_networks = block_private_networks

    def allows(self, ip: IPAddress) -> bool:
        # Always refused, regardless of configuration.
        if isinstance(ip, ipaddress.IPv6Address) and (
            ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip in _NAT64
        ):
            return False
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            return False
        if any(ip in network for network in _METADATA_ENDPOINTS):
            return False
        if not self.block_private_networks:
            return True
        # Tightened mode: globally routable unicast only. is_global alone is
        # not enough: CPython reports IPv6 site-local (fec0::/10) as global.
        if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
            return False
        return ip.is_global and not ip.is_reserved


class DisallowedDestination(Exception):
    """A connection target whose address the policy refuses."""


class PolicyResolver(AbstractResolver):
    """Resolve names, refusing an answer with any address the policy refuses.

    A name in ``loopback_names`` may resolve to loopback addresses, and only to
    those: a session that serves a provider on this machine in development
    reaches it by name, while any other name pointing at loopback is refused.
    """

    def __init__(
        self, policy: DestinationPolicy, *, loopback_names: Collection[str] = ()
    ) -> None:
        self._delegate = DefaultResolver()
        self._policy = policy
        self._loopback_names = frozenset(loopback_names)

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        results = await self._delegate.resolve(host, port, family)
        if host in self._loopback_names:
            allowed = all(_address(r["host"]).is_loopback for r in results)
        else:
            allowed = all(self._policy.allows(_address(r["host"])) for r in results)
        if not results or not allowed:
            raise DisallowedDestination(host)
        return results

    async def close(self) -> None:
        await self._delegate.close()


def _address(address: str) -> IPAddress:
    # A resolver answers with addresses; anything else is refused as unspecified.
    try:
        return ipaddress.ip_address(address)
    except ValueError:
        return ipaddress.IPv4Address(0)
