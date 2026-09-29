"""What a flow may connect to, and the vetting that enforces it.

The set is exact. Strict mode (the default) accepts public unicast addresses
only. Allow-private mode accepts those plus RFC 1918 (10/8, 172.16/12,
192.168/16) and unique-local IPv6 (fc00::/7), and nothing else. Every other
range is refused in both modes: loopback, link-local, carrier-grade NAT
(100.64/10), 0/8, 240/4, multicast, unspecified, IPv6 site-local, cloud
metadata and platform-service endpoints, and the IPv4-mapped (::ffff:0:0/96),
6to4 (2002::/16), Teredo (2001::/32) and NAT64 well-known (64:ff9b::/96)
prefixes. A network-specific NAT64 prefix (RFC 6052 section 3.4) inside global
unicast is an ordinary address to this policy: it does not look up translator
prefixes or the IPv4 address behind them.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

import anyio

from eneo.main.destination_policy import (
    IPAddress,
    is_ipv4_transition_form,
    is_local_or_multicast,
    is_metadata_endpoint,
)

logger = logging.getLogger(__name__)

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
# What "public unicast" excludes, listed here rather than left to a Python
# release's is_global table. IPv4: the non-global blocks of the IANA
# special-purpose registry (RFC 6890 and updates) and multicast. A block is
# refused whole, including the few addresses IANA lists inside it as globally
# reachable (192.0.0.9 PCP and 192.0.0.10 TURN anycast here; 2001:1::1,
# 2001:1::2, 2001:3::/32, 2001:4:112::/48, 2001:20::/28 and 2001:30::/28 in
# IPv6): no flow needs them and a whole block is the simpler rule.
_IPV4_NOT_PUBLIC = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
# IPv6: global unicast is 2000::/3; these special-purpose blocks inside it are
# not public (IETF assignments incl. Teredo, documentation, 6to4).
_GLOBAL_UNICAST_V6 = ipaddress.ip_network("2000::/3")
_IPV6_NOT_PUBLIC = tuple(
    ipaddress.ip_network(network)
    for network in ("2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20")
)

# The longest DNS answer that is used. No real name has this many addresses; a
# longer one is treated as unresolvable rather than cut, because cutting it would
# vet only part of the answer, and it is refused before it is read so a hostile
# answer costs nothing to scan.
MAX_ANSWER_ADDRESSES = 64


class DestinationRefused(Exception):
    """The policy does not allow the destination; the addresses are for logs."""

    def __init__(self, host: str, addresses: Sequence[str] = ()) -> None:
        super().__init__(f"Destination refused: {host}")
        self.host = host
        self.addresses = tuple(addresses)


class DestinationUnresolvable(Exception):
    def __init__(self, host: str) -> None:
        super().__init__(f"Destination did not resolve: {host}")
        self.host = host


class FlowDestinationPolicy:
    def __init__(self, *, allow_private_networks: bool) -> None:
        self.allow_private_networks = allow_private_networks

    def allows(self, ip: IPAddress) -> bool:
        if is_ipv4_transition_form(ip) or is_metadata_endpoint(ip):
            return False
        if self.allow_private_networks and any(ip in n for n in _PRIVATE_NETWORKS):
            return True
        return _is_public_unicast(ip)


def _is_public_unicast(ip: IPAddress) -> bool:
    if is_local_or_multicast(ip):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        return ip in _GLOBAL_UNICAST_V6 and not any(
            ip in network for network in _IPV6_NOT_PUBLIC
        )
    return not any(ip in network for network in _IPV4_NOT_PUBLIC)


class Deadline:
    """One monotonic budget shared by name resolution and every TCP connection
    attempt. It is the connect timeout: the TLS handshake that follows and each
    read and write are timed by httpx separately, with the same value."""

    def __init__(self, seconds: float | None) -> None:
        self._at = None if seconds is None else time.monotonic() + seconds

    def remaining(self) -> float | None:
        return None if self._at is None else self._at - time.monotonic()

    def share(self, attempts_left: int) -> float | None:
        remaining = self.remaining()
        return None if remaining is None else remaining / max(attempts_left, 1)


Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


def is_local_host_name(host: str) -> bool:
    name = host.strip().lower().removesuffix(".")
    return (
        name == "localhost"
        or name == "localhost.localdomain"
        or name.endswith(".localhost")
    )


async def vet_destination(
    host: str,
    port: int,
    *,
    policy: FlowDestinationPolicy,
    deadline: Deadline,
    resolver: Resolver,
) -> tuple[IPAddress, ...]:
    """The addresses a transport may connect to for ``host``, or an exception.

    IP literals are classified directly and every other name is resolved under
    ``deadline`` (``TimeoutError`` when it runs out). An answer longer than
    ``MAX_ANSWER_ADDRESSES`` is not used. Otherwise every entry is classified and
    the answer is released only when all of them are allowed, so a split answer
    that hides one internal address among public ones releases nothing.
    """
    if is_local_host_name(host):
        raise DestinationRefused(host)
    try:
        answered: Sequence[str] = [str(ipaddress.ip_address(host))]
    except ValueError:
        with anyio.fail_after(deadline.remaining()):
            answered = await resolver(host, port)
    if len(answered) > MAX_ANSWER_ADDRESSES:
        raise DestinationUnresolvable(host)
    unique: dict[IPAddress, None] = {}
    for text in answered:
        try:
            unique.setdefault(ipaddress.ip_address(text))
        except ValueError:
            continue
    addresses = _alternate_families(list(unique))
    if not addresses:
        raise DestinationUnresolvable(host)
    refused = [str(a) for a in addresses if not policy.allows(a)]
    if refused:
        logger.warning(
            "Flow HTTP refused destination %s (%s): not an allowed network",
            host,
            ", ".join(refused),
        )
        raise DestinationRefused(host, refused)
    return tuple(addresses)


def _alternate_families(addresses: list[IPAddress]) -> list[IPAddress]:
    """IPv6 and IPv4 addresses in turn, starting with the family the resolver
    listed first, so a dead prefix of one family cannot use up every attempt."""
    if not addresses:
        return addresses
    first = addresses[0].version
    same = [a for a in addresses if a.version == first]
    other = [a for a in addresses if a.version != first]
    ordered: list[IPAddress] = []
    for index in range(max(len(same), len(other))):
        if index < len(same):
            ordered.append(same[index])
        if index < len(other):
            ordered.append(other[index])
    return ordered
