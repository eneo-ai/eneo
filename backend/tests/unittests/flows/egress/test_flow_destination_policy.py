"""The exact set of addresses a flow may connect to.

Strict mode (the default) accepts public unicast only. Allow-private mode adds
RFC 1918 and unique-local IPv6, and nothing else. Every other range is refused
in both modes, including the IPv4-in-IPv6 forms of any address.
"""

from __future__ import annotations

import ipaddress

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eneo.flows.runtime.egress import policy as policy_module
from eneo.flows.runtime.egress.policy import (
    MAX_ANSWER_ADDRESSES,
    Deadline,
    DestinationRefused,
    DestinationUnresolvable,
    FlowDestinationPolicy,
    is_local_host_name,
    vet_destination,
)
from eneo.main.destination_policy import is_ipv4_transition_form

PUBLIC = [
    "8.8.8.8",
    "93.184.216.34",
    "1.1.1.1",
    "11.0.0.1",
    "172.15.255.255",  # just below 172.16/12
    "172.32.0.0",  # just above it
    "192.167.255.255",
    "192.169.0.1",
    "192.0.1.1",  # between the 192.0.0/24 and 192.0.2/24 special-purpose blocks
    "192.88.98.255",  # just below 192.88.99/24
    "192.88.100.1",  # just above it
    "100.63.255.255",  # just below 100.64/10
    "100.128.0.1",  # just above it
    "198.17.255.255",  # just below 198.18/15
    "198.20.0.1",  # just above it
    "223.255.255.255",  # just below multicast
    "2606:4700::1",
    "2a00:1450:400f:80d::200e",
]
# Refused in strict mode, allowed only when private networks are allowed.
PRIVATE = [
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "192.168.255.255",
    "fc00::1",
    "fd12:3456:789a::1",
    "fdff:ffff::1",
]
# Refused in both modes.
NEVER = [
    ("127.0.0.1", "loopback"),
    ("127.255.255.255", "loopback"),
    ("::1", "loopback"),
    ("169.254.169.254", "link-local, cloud metadata"),
    ("169.254.1.1", "link-local"),
    ("fe80::1", "link-local"),
    ("fe80::1%eth0", "link-local with a zone"),
    ("100.64.0.1", "carrier-grade NAT"),
    ("100.127.255.255", "carrier-grade NAT"),
    ("100.100.100.200", "Alibaba metadata"),
    ("fd00:ec2::254", "AWS IMDS over IPv6, inside unique-local"),
    ("0.0.0.0", "unspecified"),
    ("0.1.2.3", "0/8"),
    ("0.255.255.255", "0/8"),
    ("::", "unspecified"),
    ("240.0.0.1", "240/4 reserved"),
    ("255.255.255.255", "broadcast"),
    ("224.0.0.1", "multicast"),
    ("239.255.255.255", "multicast"),
    ("ff02::1", "multicast"),
    ("fec0::1", "IPv6 site-local"),
    ("::ffff:127.0.0.1", "IPv4-mapped loopback"),
    ("::ffff:10.0.0.1", "IPv4-mapped private"),
    ("::ffff:8.8.8.8", "IPv4-mapped public"),
    ("2002:7f00:1::1", "6to4 wrapping loopback"),
    ("2002:0808:0808::1", "6to4 wrapping public"),
    ("2001:0:4136:e378:8000:63bf:3fff:fdd2", "Teredo"),
    ("64:ff9b::a00:1", "NAT64 wrapping private"),
    ("64:ff9b::808:808", "NAT64 wrapping public"),
    ("64:ff9b:1::7f00:1", "NAT64 local-use wrapping loopback"),
    ("::7f00:1", "IPv4-compatible loopback"),
    ("::ffff:0:7f00:1", "SIIT wrapping loopback"),
    ("100::1", "IPv6 discard prefix"),
    ("2001:db8::1", "IPv6 documentation"),
    ("192.0.2.1", "IPv4 documentation"),
    ("198.51.100.1", "IPv4 documentation"),
    ("203.0.113.1", "IPv4 documentation"),
    ("198.18.0.1", "benchmarking"),
    ("192.0.0.1", "IETF protocol assignments"),
    ("192.0.0.192", "IETF protocol assignments"),
    ("192.0.0.9", "PCP anycast, refused with the rest of 192.0.0.0/24"),
    ("192.0.0.10", "TURN anycast, refused with the rest of 192.0.0.0/24"),
    ("168.63.129.16", "Azure WireServer"),
    ("192.88.99.1", "6to4 relay anycast"),
    ("2001:1::1", "IETF protocol assignments, 2001::/23"),
    ("3fff::1", "IPv6 documentation, 3fff::/20"),
]

STRICT = FlowDestinationPolicy(allow_private_networks=False)
PRIVATE_ALLOWED = FlowDestinationPolicy(allow_private_networks=True)


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(text)


@pytest.mark.parametrize("ip", PUBLIC)
def test_public_unicast_is_allowed_in_both_modes(ip: str):
    assert STRICT.allows(_ip(ip)) is True
    assert PRIVATE_ALLOWED.allows(_ip(ip)) is True


@pytest.mark.parametrize("ip", PRIVATE)
def test_private_ranges_need_the_allow_private_setting(ip: str):
    assert STRICT.allows(_ip(ip)) is False
    assert PRIVATE_ALLOWED.allows(_ip(ip)) is True


@pytest.mark.parametrize(("ip", "why"), NEVER, ids=[ip for ip, _ in NEVER])
def test_everything_else_is_refused_in_both_modes(ip: str, why: str):
    assert STRICT.allows(_ip(ip)) is False, why
    assert PRIVATE_ALLOWED.allows(_ip(ip)) is False, why


_ANY_ADDRESS = st.one_of(
    st.builds(ipaddress.IPv4Address, st.integers(0, 2**32 - 1)),
    st.builds(ipaddress.IPv6Address, st.integers(0, 2**128 - 1)),
    st.builds(
        lambda prefix, rest: ipaddress.IPv6Address((prefix << 112) | rest),
        st.sampled_from([0x0, 0x64, 0x100, 0x2001, 0x2002, 0xFC00, 0xFEC0, 0xFF02]),
        st.integers(0, 2**112 - 1),
    ),
)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
]


@given(_ANY_ADDRESS)
def test_the_two_modes_differ_only_by_the_private_ranges(ip):
    strict = STRICT.allows(ip)
    private = PRIVATE_ALLOWED.allows(ip)
    assert not strict or private
    if private and not strict:
        assert any(ip in network for network in _PRIVATE_NETWORKS)
    if is_ipv4_transition_form(ip):
        assert not private


@pytest.mark.parametrize("stdlib_says", [True, False])
@pytest.mark.parametrize("policy", [STRICT, PRIVATE_ALLOWED], ids=["strict", "private"])
def test_the_table_does_not_depend_on_the_stdlib_global_flag(
    monkeypatch, policy, stdlib_says
):
    """Public unicast is defined here, by the special-purpose registries, not by
    whatever one Python release's is_global table happens to say."""
    for version in (ipaddress.IPv4Address, ipaddress.IPv6Address):
        monkeypatch.setattr(version, "is_global", property(lambda self: stdlib_says))
    allowed_private = policy.allow_private_networks
    for ip in PUBLIC:
        assert policy.allows(_ip(ip)) is True, ip
    for ip in PRIVATE:
        assert policy.allows(_ip(ip)) is allowed_private, ip
    for ip, why in NEVER:
        assert policy.allows(_ip(ip)) is False, why


@pytest.mark.parametrize(
    "primitive",
    ["is_ipv4_transition_form", "is_metadata_endpoint", "is_local_or_multicast"],
)
@pytest.mark.parametrize("policy", [STRICT, PRIVATE_ALLOWED], ids=["strict", "private"])
def test_the_policy_asks_the_shared_owner_of_each_always_refused_rule(
    monkeypatch, primitive, policy
):
    """The three rules exist once, in eneo.main.destination_policy; the flow
    policy consults them rather than keeping its own copy."""
    assert policy.allows(_ip("8.8.8.8")) is True
    monkeypatch.setattr(policy_module, primitive, lambda ip: True)
    assert policy.allows(_ip("8.8.8.8")) is False


@pytest.mark.parametrize(
    "name",
    ["localhost", "LOCALHOST", "localhost.", "app.localhost", "localhost.localdomain"],
)
def test_local_names_are_recognised(name: str):
    assert is_local_host_name(name) is True


@pytest.mark.parametrize("name", ["example.com", "notlocalhost", "localhost.example"])
def test_other_names_are_not_local(name: str):
    assert is_local_host_name(name) is False


def _resolver(answer: list[str]):
    calls: list[tuple[str, int]] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append((host, port))
        return answer

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


async def test_a_split_answer_releases_nothing():
    resolver = _resolver(["93.184.216.34", "127.0.0.1"])
    with pytest.raises(DestinationRefused) as exc:
        await vet_destination(
            "split.example.test",
            80,
            policy=STRICT,
            deadline=Deadline(5),
            resolver=resolver,
        )
    assert exc.value.addresses == ("127.0.0.1",)


async def test_an_allowed_answer_is_released_without_duplicates():
    resolver = _resolver(["93.184.216.34", "2606:4700::1", "93.184.216.34"])
    addresses = await vet_destination(
        "ok.example.test", 443, policy=STRICT, deadline=Deadline(5), resolver=resolver
    )
    assert addresses == (_ip("93.184.216.34"), _ip("2606:4700::1"))


@pytest.mark.parametrize("literal", ["93.184.216.34", "2606:4700::1"])
async def test_an_allowed_literal_is_not_resolved(literal: str):
    resolver = _resolver(["127.0.0.1"])
    addresses = await vet_destination(
        literal, 80, policy=STRICT, deadline=Deadline(5), resolver=resolver
    )
    assert addresses == (_ip(literal),)
    assert resolver.calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("literal", ["127.0.0.1", "::1", "100.100.100.200", "10.0.0.1"])
async def test_a_refused_literal_never_reaches_the_resolver(literal: str):
    resolver = _resolver(["93.184.216.34"])
    with pytest.raises(DestinationRefused):
        await vet_destination(
            literal, 80, policy=STRICT, deadline=Deadline(5), resolver=resolver
        )
    assert resolver.calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("spelling", "resolves_to"),
    [("127.1", "127.0.0.1"), ("2130706433", "127.0.0.1"), ("0x7f000001", "127.0.0.1")],
)
async def test_odd_ipv4_spellings_are_judged_by_what_they_resolve_to(
    spelling: str, resolves_to: str
):
    with pytest.raises(DestinationRefused):
        await vet_destination(
            spelling,
            80,
            policy=PRIVATE_ALLOWED,
            deadline=Deadline(5),
            resolver=_resolver([resolves_to]),
        )


@pytest.mark.parametrize("name", ["localhost", "localhost.", "a.localhost"])
async def test_local_names_are_refused_before_resolution(name: str):
    resolver = _resolver(["93.184.216.34"])
    with pytest.raises(DestinationRefused):
        await vet_destination(
            name, 80, policy=PRIVATE_ALLOWED, deadline=Deadline(5), resolver=resolver
        )
    assert resolver.calls == []  # type: ignore[attr-defined]


class _NeverScanned(list):
    """An answer that fails the test if anything iterates it."""

    def __iter__(self):
        raise AssertionError("an oversized answer must be refused before it is read")


@pytest.mark.parametrize("size", [MAX_ANSWER_ADDRESSES + 1, 10_000, 200_000], ids=str)
async def test_an_answer_over_the_bound_is_not_used_and_not_read(size: int):
    answer = _NeverScanned(["93.184.216.34"] * size)
    with pytest.raises(DestinationUnresolvable):
        await vet_destination(
            "many.example.test",
            80,
            policy=STRICT,
            deadline=Deadline(5),
            resolver=_resolver(answer),
        )


async def test_an_answer_at_the_bound_is_used():
    answer = [f"93.184.216.{n}" for n in range(1, MAX_ANSWER_ADDRESSES + 1)]
    vetted = await vet_destination(
        "many.example.test",
        80,
        policy=STRICT,
        deadline=Deadline(5),
        resolver=_resolver(answer),
    )
    assert MAX_ANSWER_ADDRESSES == 64
    assert len(vetted) == 64


async def test_a_duplicate_heavy_answer_within_the_bound_is_deduplicated():
    answer = ["93.184.216.34", "93.184.216.35"] * (MAX_ANSWER_ADDRESSES // 2)
    vetted = await vet_destination(
        "dupes.example.test",
        80,
        policy=STRICT,
        deadline=Deadline(5),
        resolver=_resolver(answer),
    )
    assert [str(a) for a in vetted] == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.parametrize("position", [0, 31, MAX_ANSWER_ADDRESSES - 1])
async def test_every_entry_within_the_bound_is_classified(position: int):
    answer = [f"93.184.216.{n}" for n in range(1, MAX_ANSWER_ADDRESSES + 1)]
    answer[position] = "127.0.0.1"
    with pytest.raises(DestinationRefused):
        await vet_destination(
            "split.example.test",
            80,
            policy=STRICT,
            deadline=Deadline(5),
            resolver=_resolver(answer),
        )


async def test_a_live_ipv4_address_is_reached_after_a_wall_of_ipv6_ones():
    answer = [f"2606:4700::{n:x}" for n in range(1, MAX_ANSWER_ADDRESSES)]
    answer.append("93.184.216.34")
    vetted = await vet_destination(
        "dual.example.test",
        80,
        policy=STRICT,
        deadline=Deadline(5),
        resolver=_resolver(answer),
    )
    assert len(vetted) == MAX_ANSWER_ADDRESSES
    assert vetted[1] == _ip("93.184.216.34")


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            [
                "2606:4700::1",
                "2606:4700::2",
                "2606:4700::3",
                "93.184.216.34",
                "93.184.216.35",
            ],
            [
                "2606:4700::1",
                "93.184.216.34",
                "2606:4700::2",
                "93.184.216.35",
                "2606:4700::3",
            ],
        ),
        (
            ["93.184.216.34", "2606:4700::1", "93.184.216.35"],
            ["93.184.216.34", "2606:4700::1", "93.184.216.35"],
        ),
        (
            ["93.184.216.34", "93.184.216.35", "2606:4700::1"],
            ["93.184.216.34", "2606:4700::1", "93.184.216.35"],
        ),
        (["93.184.216.34", "93.184.216.35"], ["93.184.216.34", "93.184.216.35"]),
    ],
)
async def test_families_alternate_starting_with_the_first_answer(answer, expected):
    vetted = await vet_destination(
        "dual.example.test",
        80,
        policy=STRICT,
        deadline=Deadline(5),
        resolver=_resolver(answer),
    )
    assert [str(a) for a in vetted] == expected


async def test_an_empty_answer_is_unresolvable():
    with pytest.raises(DestinationUnresolvable):
        await vet_destination(
            "empty.example.test",
            80,
            policy=STRICT,
            deadline=Deadline(5),
            resolver=_resolver([]),
        )
