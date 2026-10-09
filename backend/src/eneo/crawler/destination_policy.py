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

This module deliberately has no application imports so it is identical on every
release branch.
"""

from __future__ import annotations

import ipaddress

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
