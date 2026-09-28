"""Destination policy for the website crawler.

The crawler may connect to public and private (intranet) unicast addresses,
but never to loopback, link-local, unspecified, multicast, IPv4-in-IPv6
transition addresses or the known cloud metadata endpoints. Operators who do
not crawl intranet sites can set CRAWLER_BLOCK_PRIVATE_NETWORKS to also refuse
private ranges.

The policy is enforced in the reactor's name resolver, so it applies to the
addresses a connection actually uses: start URLs, redirects, followed links,
sitemap entries, robots.txt and file downloads. IP literals go through the same
resolver (twisted HostnameEndpoint.connect has no literal shortcut), and a DNS
answer is released only when every address in it is allowed.

This module deliberately has no application imports so it is identical on every
release branch.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from twisted.internet.interfaces import IHostnameResolver, IResolutionReceiver
from zope.interface import implementer  # pyright: ignore[reportMissingTypeStubs]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

logger = logging.getLogger(__name__)

# How many refused host names the guard remembers, so the downloader can tell a
# policy refusal apart from a genuine DNS failure. Bounded to keep memory flat.
_REFUSED_HOSTS_LIMIT = 1024

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


@implementer(IResolutionReceiver)  # pyright: ignore[reportUntypedClassDecorator]
class _PolicyReceiver:
    """Buffers a resolution and releases it only if every address is allowed."""

    def __init__(
        self, receiver: Any, guard: "GuardedNameResolver", host_name: str
    ) -> None:
        self._receiver = receiver
        self._guard = guard
        self._host_name = host_name
        self._addresses: list[Any] = []

    def resolutionBegan(self, resolutionInProgress: Any) -> None:
        self._receiver.resolutionBegan(resolutionInProgress)

    def addressResolved(self, address: Any) -> None:
        self._addresses.append(address)

    def resolutionComplete(self) -> None:
        refused = [
            str(getattr(a, "host", "?"))
            for a in self._addresses
            if not self._is_allowed(a)
        ]
        if self._addresses and not refused:
            for address in self._addresses:
                self._receiver.addressResolved(address)
        elif refused:
            self._guard.note_refusal(self._host_name, refused)
        self._receiver.resolutionComplete()

    def _is_allowed(self, address: Any) -> bool:
        try:
            return self._guard.policy.allows(
                ipaddress.ip_address(getattr(address, "host", ""))
            )
        except ValueError:
            return False


@implementer(IHostnameResolver)  # pyright: ignore[reportUntypedClassDecorator]
class GuardedNameResolver:
    def __init__(self, inner: Any, policy: DestinationPolicy) -> None:
        self._inner = inner
        self.policy = policy
        # host name -> addresses the policy refused, most recent last
        self.refused: dict[str, list[str]] = {}

    def note_refusal(self, host_name: str, addresses: list[str]) -> None:
        logger.warning(
            "Crawler refused destination %s (%s): not an allowed network",
            host_name,
            ", ".join(addresses),
        )
        self.refused.pop(host_name, None)
        self.refused[host_name] = addresses
        while len(self.refused) > _REFUSED_HOSTS_LIMIT:
            self.refused.pop(next(iter(self.refused)))

    def refused_addresses(self, host_name: str) -> list[str] | None:
        return self.refused.get(host_name)

    def resolveHostName(
        self,
        resolutionReceiver: Any,
        hostName: str,
        portNumber: int = 0,
        addressTypes: Any = None,
        transportSemantics: str = "TCP",
    ) -> Any:
        return self._inner.resolveHostName(
            _PolicyReceiver(resolutionReceiver, self, hostName),
            hostName,
            portNumber,
            addressTypes,
            transportSemantics,
        )


def install_destination_guard(reactor: Any, policy: DestinationPolicy) -> None:
    """Install the guard on the reactor once; later calls only replace the policy.

    Call from the reactor thread before any crawl connects (create_runner runs
    there). Twisted 24.7 captures the resolver when an endpoint is built.
    """
    current = reactor.nameResolver
    if isinstance(current, GuardedNameResolver):
        current.policy = policy
        return
    reactor.installNameResolver(GuardedNameResolver(current, policy))
