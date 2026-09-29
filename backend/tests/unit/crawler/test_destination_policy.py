"""The crawler never connects to loopback, link-local, unspecified, multicast or
IPv4-in-IPv6 transition addresses. Private (intranet) ranges are allowed by
default and refused only when the operator blocks them. Enforced in the
crawler's name resolver so it covers every connection the crawler makes."""

import ipaddress

import pytest

from eneo.crawler.destination_policy import DestinationPolicy

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


@pytest.mark.parametrize("block_private_networks", [False, True])
def test_worker_crawl_engine_applies_the_operator_setting(
    monkeypatch: pytest.MonkeyPatch, block_private_networks: bool
):
    from eneo.main.config import get_settings
    from eneo.main.container import container

    settings = get_settings().model_copy(
        update={"crawler_block_private_networks": block_private_networks}
    )
    monkeypatch.setattr(container, "get_settings", lambda: settings)

    policy = container._build_crawl_engine()._destination_policy

    assert policy is not None
    assert policy.allows(ipaddress.ip_address("10.0.0.1")) is not block_private_networks
    assert policy.allows(ipaddress.ip_address("127.0.0.1")) is False
