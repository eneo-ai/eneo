"""The address classification has one owner, ``eneo.main.destination_policy``,
which the crawler re-exports and other outbound-network code, the flows egress
among it, is meant to build on."""

import ast
import ipaddress
import random
import sys
from pathlib import Path

import pytest

import eneo.crawler.destination_policy as crawler_policy
import eneo.main.destination_policy as shared
from eneo.main.destination_policy import (
    DestinationPolicy,
    is_ipv4_transition_form,
    is_local_or_multicast,
    is_metadata_endpoint,
)

TRANSITION_FORMS = [
    "::ffff:127.0.0.1",
    "::ffff:8.8.8.8",
    "2002:7f00:1::1",
    "2002:0808:0808::1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    "64:ff9b::a00:1",
    "64:ff9b::808:808",
]
METADATA = [
    "fd00:ec2::254",
    "100.100.100.200",
    "168.63.129.16",  # Azure WireServer
    "192.0.0.0",  # IETF protocol assignments, 192.0.0.0/24 ...
    "192.0.0.8",
    "192.0.0.11",
    "192.0.0.170",
    "192.0.0.192",
    "192.0.0.255",  # ... except the globally reachable anycast .9 and .10
]
# IANA lists these two addresses of 192.0.0.0/24 as globally reachable.
GLOBALLY_REACHABLE_IN_THE_BLOCK = ["192.0.0.9", "192.0.0.10"]
LOCAL_OR_MULTICAST = [
    "127.0.0.1",
    "::1",
    "169.254.169.254",
    "fe80::1",
    "0.0.0.0",
    "::",
    "224.0.0.1",
    "239.255.255.255",
    "ff02::1",
]
NEITHER = [
    "8.8.8.8",
    "168.63.129.15",
    "168.63.129.17",
    "192.0.1.1",
    "191.255.255.255",
    *GLOBALLY_REACHABLE_IN_THE_BLOCK,
    "10.0.0.1",
    "127.0.0.1",
    "169.254.169.254",
    "100.64.0.1",
    "100.100.100.201",
    "2606:4700::1",
    "fd00:ec2::255",
    "fc00::1",
    "::1",
    "fe80::1",
    "64:ff9b:1::7f00:1",
    "::7f00:1",
]


def test_crawler_reexports_the_shared_policy():
    assert crawler_policy.DestinationPolicy is shared.DestinationPolicy


def test_shared_module_imports_only_the_standard_library():
    source = Path(shared.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            imported.add((node.module or "").split(".")[0])
    outside = imported - set(sys.stdlib_module_names)
    assert not outside, f"non-stdlib imports in destination_policy: {sorted(outside)}"


@pytest.mark.parametrize("ip", TRANSITION_FORMS)
def test_transition_forms_are_recognised(ip: str):
    assert is_ipv4_transition_form(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", METADATA)
def test_metadata_endpoints_are_recognised(ip: str):
    assert is_metadata_endpoint(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", NEITHER)
def test_other_addresses_are_not_transition_or_metadata(ip: str):
    parsed = ipaddress.ip_address(ip)
    assert is_ipv4_transition_form(parsed) is False
    assert is_metadata_endpoint(parsed) is False


@pytest.mark.parametrize("ip", LOCAL_OR_MULTICAST)
def test_local_and_multicast_addresses_are_recognised(ip: str):
    assert is_local_or_multicast(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "10.0.0.1", "2606:4700::1", "fc00::1"])
def test_routable_addresses_are_not_local_or_multicast(ip: str):
    assert is_local_or_multicast(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize(
    "ip", ["168.63.129.16", "192.0.0.0", "192.0.0.8", "192.0.0.11", "192.0.0.192"]
)
@pytest.mark.parametrize("block_private_networks", [False, True])
def test_platform_service_addresses_are_refused_in_both_modes(
    ip: str, block_private_networks: bool
):
    policy = DestinationPolicy(block_private_networks=block_private_networks)
    assert policy.allows(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize("ip", GLOBALLY_REACHABLE_IN_THE_BLOCK)
@pytest.mark.parametrize("block_private_networks", [False, True])
def test_the_two_globally_reachable_addresses_of_the_block_stay_allowed(
    ip: str, block_private_networks: bool
):
    policy = DestinationPolicy(block_private_networks=block_private_networks)
    assert policy.allows(ipaddress.ip_address(ip)) is True


def _sample() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses = [
        ipaddress.ip_address(text)
        for text in TRANSITION_FORMS + METADATA + NEITHER + ["0.0.0.0", "::", "ff02::1"]
    ]
    for prefix in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "168.63.129.0/24",
        "169.254.0.0/16",
        "192.0.0.0/24",
        "192.0.0.8/29",
        "192.0.1.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "2001::/32",
        "2002::/16",
        "fc00::/7",
        "fe80::/10",
    ):
        network = ipaddress.ip_network(prefix)
        addresses.append(network[0])
        addresses.append(network[network.num_addresses // 2])
        addresses.append(network[-1])
    return addresses


# The crawler's rule as it was before allows() called the primitives, frozen
# here with its own copies of the constants, so the comparison below fails if the
# shared module's behaviour drifts from it. The one deliberate difference is
# _REFERENCE_ADDED: what the crawler now also refuses in both modes, the Azure
# WireServer address and the IETF protocol-assignments block 192.0.0.0/24, minus
# the two addresses IANA lists as globally reachable (_REFERENCE_STILL_ALLOWED).
_REFERENCE_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_REFERENCE_METADATA = (
    ipaddress.ip_network("fd00:ec2::254/128"),
    ipaddress.ip_network("100.100.100.200/32"),
)
_REFERENCE_ADDED = (
    ipaddress.ip_network("168.63.129.16/32"),
    ipaddress.ip_network("192.0.0.0/24"),
)
_REFERENCE_STILL_ALLOWED = (
    ipaddress.ip_network("192.0.0.9/32"),
    ipaddress.ip_network("192.0.0.10/32"),
)


def _reference_allows(ip, block_private_networks: bool) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and (
        ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip in _REFERENCE_NAT64
    ):
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    if any(ip in network for network in _REFERENCE_METADATA):
        return False
    if any(ip in network for network in _REFERENCE_ADDED) and not any(
        ip in network for network in _REFERENCE_STILL_ALLOWED
    ):
        return False
    if not block_private_networks:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return False
    return ip.is_global and not ip.is_reserved


_V6_PREFIXES = (
    0x0,
    0x64,
    0x100,
    0x2001,
    0x2002,
    0x2606,
    0xFD00,
    0xFE80,
    0xFEC0,
    0xFF02,
)


def _random_sample() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    rng = random.Random(20260929)
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _ in range(17_000):
        addresses.append(ipaddress.IPv4Address(rng.getrandbits(32)))
        addresses.append(ipaddress.IPv6Address(rng.getrandbits(128)))
        prefix = rng.choice(_V6_PREFIXES)
        addresses.append(ipaddress.IPv6Address((prefix << 112) | rng.getrandbits(112)))
    return addresses


@pytest.mark.parametrize("block_private_networks", [False, True])
def test_allows_decides_exactly_as_the_frozen_reference(block_private_networks: bool):
    policy = DestinationPolicy(block_private_networks=block_private_networks)
    differing = [
        str(ip)
        for ip in _sample() + _random_sample()
        if policy.allows(ip) != _reference_allows(ip, block_private_networks)
    ]
    assert not differing, f"allows() drifted from the crawler rule: {differing[:5]}"
