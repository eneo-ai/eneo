"""The flow HTTP sender end to end: what a request to a destination the policy
does or does not allow does, seen from the callers (HTTP input, webhook
delivery, the authoring test endpoint), which all use ``send_request``."""

from __future__ import annotations

import pytest

from eneo.flows.runtime.egress.http import build_http_client
from eneo.flows.runtime.egress.policy import DestinationUnresolvable
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows.egress.egress_test_support import (
    INVALID_URLS,
    FixedResolver,
    SpyConnector,
    recording_server,
)

PUBLIC = "93.184.216.34"


class _Interpolator:
    def interpolate(self, value: str, context: dict) -> str:
        return value


def _helper(
    *, allow_private: bool = False, client_factory=None
) -> FlowHttpRuntimeHelper:
    kwargs = {} if client_factory is None else {"client_factory": client_factory}
    return FlowHttpRuntimeHelper(
        variable_resolver=_Interpolator(),
        request_timeout_seconds=5,
        max_timeout_seconds=30,
        allow_private_networks=allow_private,
        **kwargs,
    )


def _scripted(resolver, connector):
    def factory(**kwargs):
        return build_http_client(resolver=resolver, connector=connector, **kwargs)

    return factory


async def _get(helper: FlowHttpRuntimeHelper, url: str):
    return await helper.send_request(
        method="GET", url=url, headers={}, timeout_seconds=3
    )


@pytest.mark.parametrize("url", INVALID_URLS, ids=repr)
async def test_an_invalid_url_is_typed_and_no_client_is_built(url):
    def factory(**_kwargs):
        raise AssertionError("a client must not exist for an invalid URL")

    with pytest.raises(TypedIOValidationException) as exc:
        await _get(_helper(client_factory=factory), url)
    assert exc.value.code == "typed_io_http_invalid_url"


@pytest.mark.parametrize(
    ("answer", "allow_private", "allowed"),
    [
        (["93.184.216.34"], False, True),
        (["10.0.0.5"], False, False),
        (["10.0.0.5"], True, True),
        (["fd12::1"], True, True),
        (["127.0.0.1"], False, False),
        (["127.0.0.1"], True, False),
        (["169.254.169.254"], True, False),
        (["100.64.0.1"], True, False),
        (["100.100.100.200"], True, False),
        (["fd00:ec2::254"], True, False),
        (["::ffff:10.0.0.1"], True, False),
    ],
)
async def test_the_setting_widens_only_to_private_ranges(
    answer, allow_private, allowed
):
    async with recording_server() as origin:
        connector = SpyConnector(forward_to=origin.port)
        helper = _helper(
            allow_private=allow_private,
            client_factory=_scripted(FixedResolver(answer), connector),
        )
        if allowed:
            assert (
                await _get(helper, "http://svc.example.test:8080/")
            ).status_code == 200
        else:
            with pytest.raises(TypedIOValidationException) as exc:
                await _get(helper, "http://svc.example.test:8080/")
            assert exc.value.code == "typed_io_http_ssrf_blocked"
            assert connector.calls == []
            assert origin.connections == 0


async def test_an_unresolvable_host_is_a_connection_error():
    async def unresolvable(host: str, port: int):
        raise DestinationUnresolvable(host)

    helper = _helper(client_factory=_scripted(unresolvable, SpyConnector()))
    with pytest.raises(TypedIOValidationException) as exc:
        await _get(helper, "http://missing.example.test/")
    assert exc.value.code == "typed_io_http_connection_error"
    assert "missing.example.test" in str(exc.value)


@pytest.mark.parametrize("allow_private", [False, True])
@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.1", "2130706433", "0x7f000001", "localhost", "localhost."],
)
async def test_loopback_in_any_spelling_reaches_nothing(allow_private, host):
    """Real resolver, real socket layer: whichever way the host is spelled, the
    loopback server must see no connection."""
    async with recording_server() as internal:
        helper = _helper(allow_private=allow_private)
        with pytest.raises(TypedIOValidationException) as exc:
            await _get(helper, f"http://{host}:{internal.port}/")
        assert exc.value.code in {
            "typed_io_http_ssrf_blocked",
            "typed_io_http_connection_error",
        }
        assert internal.connections == 0
        assert bytes(internal.received) == b""


async def test_the_request_goes_to_the_parsed_url():
    async with recording_server() as origin:
        connector = SpyConnector(forward_to=origin.port)
        helper = _helper(client_factory=_scripted(FixedResolver([PUBLIC]), connector))
        await _get(helper, "  HTTP://Pinned.Example.Test:8080/Data?x=1  ")
    assert b"GET /Data?x=1 HTTP/1.1" in bytes(origin.received)
    assert b"Host: pinned.example.test:8080" in bytes(origin.received)
    assert [host for host, _, _ in connector.calls] == [PUBLIC]


async def test_the_default_policy_is_strict_and_the_setting_selects_the_mode():
    assert _helper().destination_policy.allow_private_networks is False
    assert _helper(allow_private=True).destination_policy.allow_private_networks is True
