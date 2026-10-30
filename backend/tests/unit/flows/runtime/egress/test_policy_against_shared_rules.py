"""The flow destination policy never allows an address that the shared
destination policy (``eneo.main.destination_policy``, the crawler's rule)
refuses in the matching mode: strict flow HTTP matches the crawler with
private networks blocked, and allow-private flow HTTP matches the crawler's
default. A rule added to the shared policy therefore reaches flows, or this
test names the address it would let through."""

from __future__ import annotations

import ipaddress

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eneo.flows.runtime.egress.policy import FlowDestinationPolicy
from eneo.main.destination_policy import DestinationPolicy

_MODES = [
    (
        FlowDestinationPolicy(allow_private_networks=False),
        DestinationPolicy(block_private_networks=True),
    ),
    (
        FlowDestinationPolicy(allow_private_networks=True),
        DestinationPolicy(block_private_networks=False),
    ),
]

# Every IPv4 address, every IPv6 address, and IPv6 addresses under the
# prefixes where the two rule sets are most likely to part: embedded IPv4,
# documentation, unique-local, link-local, site-local, multicast and the
# special-purpose blocks inside global unicast.
_ANY_ADDRESS = st.one_of(
    st.builds(ipaddress.IPv4Address, st.integers(0, 2**32 - 1)),
    st.builds(ipaddress.IPv6Address, st.integers(0, 2**128 - 1)),
    st.builds(
        lambda prefix, rest: ipaddress.IPv6Address((prefix << 112) | rest),
        st.sampled_from(
            [0x0, 0x64, 0x100, 0x2001, 0x2002, 0x3FFF, 0xFC00, 0xFD00, 0xFE80]
            + [0xFEC0, 0xFF02]
        ),
        st.integers(0, 2**112 - 1),
    ),
)

# Addresses on either side of the shared policy's own boundaries.
_BOUNDARY_ADDRESSES = [
    "0.0.0.1",
    "10.0.0.1",
    "100.64.0.1",
    "100.100.100.200",
    "127.0.0.1",
    "168.63.129.16",
    "169.254.169.254",
    "172.16.0.1",
    "192.0.0.9",
    "192.0.0.10",
    "192.0.0.170",
    "192.88.99.1",
    "192.168.1.1",
    "198.18.0.1",
    "224.0.0.1",
    "240.0.0.1",
    "255.255.255.255",
    "::",
    "::1",
    "::ffff:10.0.0.1",
    "::ffff:93.184.216.34",
    "64:ff9b::a00:1",
    "2001::1",
    "2001:db8::1",
    "2002:a00:1::1",
    "fc00::1",
    "fd00:ec2::254",
    "fe80::1",
    "fec0::1",
    "ff02::1",
]


@settings(max_examples=2000)
@given(_ANY_ADDRESS)
def test_flows_allow_nothing_the_shared_policy_refuses(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> None:
    for flow_policy, shared_policy in _MODES:
        if flow_policy.allows(ip):
            assert shared_policy.allows(ip), (
                f"{ip} is allowed for flows (allow_private_networks="
                f"{flow_policy.allow_private_networks}) but refused by the shared "
                f"policy (block_private_networks="
                f"{shared_policy.block_private_networks})"
            )


@pytest.mark.parametrize("text", _BOUNDARY_ADDRESSES)
def test_flows_allow_no_boundary_address_the_shared_policy_refuses(text: str) -> None:
    ip = ipaddress.ip_address(text)
    for flow_policy, shared_policy in _MODES:
        assert not flow_policy.allows(ip) or shared_policy.allows(ip), text
