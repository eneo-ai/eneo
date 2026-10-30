"""Reusable address classification for destinations users can influence.

``DestinationPolicy`` is the website crawler's rule: it may reach public and
private (intranet) unicast addresses, but never loopback, link-local,
unspecified, multicast, IPv4-in-IPv6 transition addresses or the known cloud
metadata endpoints. It lives here, apart from the crawler, so that other code that
connects to user-influenced destinations can reuse it. The three primitives below,
which ``allows()`` itself uses, are the reusable pieces: code that accepts less than
the crawler builds its own set from them instead of copying their address lists,
and the flows egress is meant to.

The module imports only the standard library, so any layer can depend on it.
"""

from __future__ import annotations

import ipaddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# NAT64 well-known prefix (RFC 6052). It embeds an IPv4 destination, so a
# blocked IPv4 address could otherwise be reached through a NAT64 gateway.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

# Cloud instance metadata endpoints that are not link-local: AWS IMDS over
# IPv6 (unique-local), Alibaba Cloud (carrier-grade NAT range) and the Azure
# WireServer (a public-looking address that only the platform answers), plus the
# IETF protocol-assignments block 192.0.0.0/24 (RFC 6890): special-purpose
# addresses, not public hosts, that platforms use for internal services. IANA
# lists two of its addresses as globally reachable anycast services, PCP
# (192.0.0.9) and TURN (192.0.0.10); they stay allowed. The link-local
# 169.254.169.254 is covered by the link-local rule.
_METADATA_ENDPOINTS = (
    ipaddress.ip_network("fd00:ec2::254/128"),
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("168.63.129.16/32"),
    ipaddress.ip_network("192.0.0.0/24"),
)
_GLOBALLY_REACHABLE_EXCEPTIONS = (
    ipaddress.ip_network("192.0.0.9/32"),
    ipaddress.ip_network("192.0.0.10/32"),
)


def is_ipv4_transition_form(ip: IPAddress) -> bool:
    """The IPv4-mapped (::ffff:0:0/96), 6to4 (2002::/16), Teredo (2001::/32) and
    NAT64 well-known (64:ff9b::/96) prefixes: each embeds or tunnels an IPv4
    destination, so an IPv6 literal can name an address that is refused in its
    IPv4 spelling. A network-specific NAT64 prefix (RFC 6052 section 3.4) is not
    recognised: it is ordinary global unicast."""
    return isinstance(ip, ipaddress.IPv6Address) and bool(
        ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip in _NAT64
    )


def is_metadata_endpoint(ip: IPAddress) -> bool:
    """A cloud metadata or platform-service address that sits inside an otherwise
    allowed range."""
    return any(ip in network for network in _METADATA_ENDPOINTS) and not any(
        ip in network for network in _GLOBALLY_REACHABLE_EXCEPTIONS
    )


def is_local_or_multicast(ip: IPAddress) -> bool:
    """Loopback, link-local, unspecified or multicast: never a destination."""
    return ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast


class DestinationPolicy:
    def __init__(self, block_private_networks: bool = False) -> None:
        self.block_private_networks = block_private_networks

    def allows(self, ip: IPAddress) -> bool:
        # Always refused, regardless of configuration.
        if is_ipv4_transition_form(ip):
            return False
        if is_local_or_multicast(ip):
            return False
        if is_metadata_endpoint(ip):
            return False
        if not self.block_private_networks:
            return True
        # Tightened mode: globally routable unicast only. is_global alone is
        # not enough: CPython reports IPv6 site-local (fec0::/10) as global.
        if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
            return False
        return ip.is_global and not ip.is_reserved
