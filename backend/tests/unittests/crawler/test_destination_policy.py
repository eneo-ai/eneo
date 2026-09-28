"""The crawler never connects to loopback, link-local, unspecified, multicast or
IPv4-in-IPv6 transition addresses. Private (intranet) ranges are allowed by
default and refused only when the operator blocks them. Enforced in the
reactor name resolver so it covers every connection the crawler makes."""

import ipaddress

import pytest
from twisted.internet.address import IPv4Address, IPv6Address
from twisted.internet.interfaces import IHostnameResolver, IResolutionReceiver
from zope.interface import implementer

from intric.crawler.destination_policy import (
    DestinationPolicy,
    GuardedNameResolver,
    install_destination_guard,
)

PUBLIC = ["8.8.8.8", "93.184.216.34", "2606:4700::1", "2a00:1450:400f:80d::200e"]
PRIVATE = [
    "10.0.0.1",
    "172.16.0.1",
    "192.168.1.1",
    "100.64.0.1",  # carrier-grade NAT
    "fc00::1",  # unique local
    "fec0::1",  # site-local
]
ALWAYS_DENIED = [
    "127.0.0.1",  # loopback
    "127.1.2.3",
    "::1",
    "169.254.169.254",  # link-local / cloud metadata
    "169.254.1.1",
    "fe80::1",
    "0.0.0.0",  # unspecified
    "::",
    "224.0.0.1",  # multicast
    "ff02::1",
    "::ffff:127.0.0.1",  # IPv4-mapped
    "::ffff:10.0.0.1",
    "2002:7f00:1::1",  # 6to4 wrapping 127.0.0.1
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    "64:ff9b::a00:1",  # NAT64 wrapping 10.0.0.1
    "fd00:ec2::254",  # AWS IMDS over IPv6 (inside unique-local space)
    "100.100.100.200",  # Alibaba Cloud metadata (inside CGNAT space)
]


@pytest.mark.parametrize("ip", PUBLIC + PRIVATE)
def test_public_and_private_are_allowed_by_default(ip: str):
    assert DestinationPolicy().allows(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ALWAYS_DENIED)
def test_dangerous_destinations_are_always_denied(ip: str):
    assert DestinationPolicy().allows(ipaddress.ip_address(ip)) is False
    assert (
        DestinationPolicy(block_private_networks=True).allows(ipaddress.ip_address(ip))
        is False
    )


@pytest.mark.parametrize("ip", PRIVATE + ["240.0.0.1"])
def test_private_is_denied_when_blocked(ip: str):
    policy = DestinationPolicy(block_private_networks=True)
    assert policy.allows(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize("ip", PUBLIC)
def test_public_stays_allowed_when_private_is_blocked(ip: str):
    policy = DestinationPolicy(block_private_networks=True)
    assert policy.allows(ipaddress.ip_address(ip)) is True


# --- resolver ---------------------------------------------------------------


@implementer(IHostnameResolver)
class _FakeInner:
    def __init__(self, hosts: list[str]) -> None:
        self.hosts = hosts

    def resolveHostName(
        self,
        receiver,
        hostName,
        portNumber=0,
        addressTypes=None,
        transportSemantics="TCP",
    ):
        receiver.resolutionBegan(None)
        for host in self.hosts:
            addr = (
                IPv6Address("TCP", host, portNumber)
                if ":" in host
                else IPv4Address("TCP", host, portNumber)
            )
            receiver.addressResolved(addr)
        receiver.resolutionComplete()


@implementer(IResolutionReceiver)
class _Collect:
    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.complete = False

    def resolutionBegan(self, resolution):
        pass

    def addressResolved(self, address):
        self.hosts.append(address.host)

    def resolutionComplete(self):
        self.complete = True


def _resolve(answer: list[str], policy: DestinationPolicy | None = None) -> _Collect:
    out = _Collect()
    GuardedNameResolver(
        _FakeInner(answer), policy or DestinationPolicy()
    ).resolveHostName(out, "host.example", 80)
    assert out.complete
    return out


def test_allowed_answer_is_released():
    assert _resolve(["8.8.8.8", "10.0.0.5"]).hosts == ["8.8.8.8", "10.0.0.5"]


def test_mixed_answer_releases_nothing():
    # One denied address poisons the whole answer (DNS rebinding / split answers).
    assert _resolve(["8.8.8.8", "127.0.0.1"]).hosts == []


def test_refusal_is_recorded_on_the_guard():
    out = _Collect()
    guard = GuardedNameResolver(_FakeInner(["127.0.0.1"]), DestinationPolicy())
    guard.resolveHostName(out, "host.example", 80)
    assert out.hosts == []
    assert guard.refused_addresses("host.example") == ["127.0.0.1"]
    assert guard.refused_addresses("other.example") is None


def test_loopback_answer_releases_nothing():
    assert _resolve(["127.0.0.1"]).hosts == []


def test_empty_answer_stays_empty():
    assert _resolve([]).hosts == []


def test_blocked_private_applies_in_resolver():
    policy = DestinationPolicy(block_private_networks=True)
    assert _resolve(["10.20.0.5"], policy).hosts == []
    assert _resolve(["8.8.8.8"], policy).hosts == ["8.8.8.8"]


class _FakeReactor:
    def __init__(self) -> None:
        self.nameResolver = _FakeInner([])
        self.installs = 0

    def installNameResolver(self, resolver):
        self.nameResolver = resolver
        self.installs += 1


def test_guard_installs_once_and_swaps_policy():
    reactor = _FakeReactor()
    first = DestinationPolicy()
    second = DestinationPolicy(block_private_networks=True)

    install_destination_guard(reactor, first)
    install_destination_guard(reactor, second)

    assert reactor.installs == 1
    guard = reactor.nameResolver
    assert isinstance(guard, GuardedNameResolver)
    assert guard.policy is second
    assert not isinstance(guard._inner, GuardedNameResolver)
