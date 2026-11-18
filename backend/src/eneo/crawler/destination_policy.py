"""Destination policy for the website crawler.

The crawler may connect to public and private (intranet) unicast addresses,
but never to loopback, link-local, unspecified, multicast, IPv4-in-IPv6
transition addresses or the known cloud metadata endpoints. Operators who do
not crawl intranet sites can set CRAWLER_BLOCK_PRIVATE_NETWORKS to also refuse
private ranges.

The Python crawler enforces the policy in its name resolver, so it applies to
the addresses a connection actually uses: start URLs, redirects, followed
links, sitemap entries, robots.txt and file downloads. A DNS answer is used
only when every address in it is allowed.

The address classification itself is ``eneo.main.destination_policy``, kept apart
from the crawler so the flows egress can build its own accepted set from the same
primitives; the crawler imports the policy from here.

``PolicyResolver`` applies the policy to every address aiohttp resolves for a
name. Callers check IP literals because aiohttp does not resolve them.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Collection

from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver

from eneo.main.destination_policy import DestinationPolicy, IPAddress

__all__ = ["DestinationPolicy", "DisallowedDestination", "PolicyResolver"]


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
