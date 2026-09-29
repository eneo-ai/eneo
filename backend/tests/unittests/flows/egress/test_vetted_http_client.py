"""The flow HTTP client connects only to addresses the policy vetted, and sends
nothing until such a connection exists. These tests drive real httpx requests
through the real transport; only the socket layer and the resolver are scripted."""

from __future__ import annotations

import logging
import ssl
import time

import anyio
import httpcore
import httpx
import pytest

from eneo.flows.runtime.egress import http as egress_http
from eneo.flows.runtime.egress.http import (
    MAX_CONNECT_ATTEMPTS,
    VettedAsyncTransport,
    VettedNetworkBackend,
    build_http_client,
)
from eneo.flows.runtime.egress.policy import DestinationRefused, FlowDestinationPolicy
from tests.unittests.flows.egress.egress_test_support import (
    FixedResolver,
    SpyConnector,
    client_ssl_context,
    recording_server,
    self_signed_certificate,
    server_ssl_context,
)

STRICT = FlowDestinationPolicy(allow_private_networks=False)
PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:4700::1"
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def _client(
    resolver,
    connector,
    *,
    timeout: float = 5,
    policy: FlowDestinationPolicy = STRICT,
    **kwargs,
) -> httpx.AsyncClient:
    return build_http_client(
        policy=policy,
        timeout_seconds=timeout,
        resolver=resolver,
        connector=connector,
        **kwargs,
    )


async def test_connects_to_the_vetted_ip_literal_and_keeps_the_host_header():
    async with recording_server() as origin:
        resolver = FixedResolver([PUBLIC])
        connector = SpyConnector(forward_to=origin.port)
        async with _client(resolver, connector) as client:
            response = await client.get("http://pinned.example.test:8080/data")

        assert response.status_code == 200
        assert [(host, port) for host, port, _ in connector.calls] == [(PUBLIC, 8080)]
        assert resolver.calls == [("pinned.example.test", 8080)]
        assert b"Host: pinned.example.test:8080" in bytes(origin.received)


async def test_ipv6_is_connected_as_a_bare_literal():
    async with recording_server() as origin:
        connector = SpyConnector(forward_to=origin.port)
        async with _client(FixedResolver([PUBLIC_V6]), connector) as client:
            await client.get("http://v6.example.test:8080/")
        assert [host for host, _, _ in connector.calls] == [PUBLIC_V6]


async def test_a_literal_url_is_vetted_without_resolving():
    async with recording_server() as origin:
        resolver = FixedResolver(["127.0.0.1"])
        connector = SpyConnector(forward_to=origin.port)
        async with _client(resolver, connector) as client:
            await client.get(f"http://{PUBLIC}:8080/")
        assert resolver.calls == []
        assert [host for host, _, _ in connector.calls] == [PUBLIC]


async def test_a_name_that_changes_to_an_internal_address_sends_nothing():
    """DNS rebinding: the name is public the first time and loopback after.
    Each connection resolves and vets in one step, so the second request never
    reaches the internal host, not even for a blind request."""
    async with recording_server() as public, recording_server() as internal:
        resolver = FixedResolver([PUBLIC], ["127.0.0.1"])
        async with _client(resolver, SpyConnector(forward_to=public.port)) as client:
            first = await client.get("http://rebind.example.test:8080/")
        assert first.status_code == 200
        assert public.connections == 1

        # The second request uses the real socket layer, which would connect
        # to the internal server if the policy let it.
        async with _client(resolver, None) as client:
            with pytest.raises(DestinationRefused):
                await client.get(f"http://rebind.example.test:{internal.port}/")

        assert internal.connections == 0
        assert bytes(internal.received) == b""


async def test_a_split_answer_connects_to_nothing():
    connector = SpyConnector(forward_to=1)
    async with _client(FixedResolver([PUBLIC, "127.0.0.1"]), connector) as client:
        with pytest.raises(DestinationRefused):
            await client.get("http://split.example.test/")
    assert connector.calls == []


async def test_a_redirect_is_returned_and_not_followed():
    async with recording_server() as internal:
        redirect = (
            b"HTTP/1.1 302 Found\r\n"
            + f"Location: http://127.0.0.1:{internal.port}/secret\r\n".encode()
            + b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
        async with recording_server(redirect) as origin:
            connector = SpyConnector(forward_to=origin.port)
            async with _client(FixedResolver([PUBLIC]), connector) as client:
                response = await client.get("http://redirect.example.test:8080/")

        assert response.status_code == 302
        assert len(connector.calls) == 1
        assert internal.connections == 0


@pytest.mark.parametrize("variable_case", [str.upper, str.lower])
async def test_proxy_environment_variables_are_ignored(monkeypatch, variable_case):
    async with recording_server() as proxy, recording_server() as origin:
        for name in PROXY_VARIABLES:
            monkeypatch.setenv(variable_case(name), f"http://127.0.0.1:{proxy.port}")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        connector = SpyConnector(forward_to=origin.port)
        async with _client(FixedResolver([PUBLIC]), connector) as client:
            response = await client.get("http://proxied.example.test:8080/")

        assert response.status_code == 200
        assert proxy.connections == 0
        assert [host for host, _, _ in connector.calls] == [PUBLIC]


async def test_tls_uses_the_url_host_for_sni_and_certificate_verification(tmp_path):
    pem = self_signed_certificate(tmp_path, "pinned.example.test")
    async with recording_server(ssl_context=server_ssl_context(pem)) as origin:
        connector = SpyConnector(forward_to=origin.port)
        async with _client(
            FixedResolver([PUBLIC]), connector, ssl_context=client_ssl_context(pem)
        ) as client:
            response = await client.get("https://pinned.example.test:8443/")

        assert response.status_code == 200
        assert origin.server_names == ["pinned.example.test"]
        assert [host for host, _, _ in connector.calls] == [PUBLIC]


async def test_tls_still_rejects_a_certificate_for_another_host(tmp_path):
    pem = self_signed_certificate(tmp_path, "pinned.example.test")
    async with recording_server(ssl_context=server_ssl_context(pem)) as origin:
        connector = SpyConnector(forward_to=origin.port)
        async with _client(
            FixedResolver([PUBLIC]), connector, ssl_context=client_ssl_context(pem)
        ) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("https://other.example.test:8443/")


async def test_ssl_cert_file_stays_honoured_for_an_enterprise_ca(tmp_path, monkeypatch):
    pem = self_signed_certificate(tmp_path, "corp.example.test")
    async with recording_server(ssl_context=server_ssl_context(pem)) as origin:
        connector = SpyConnector(forward_to=origin.port)
        url = "https://corp.example.test:8443/"

        async with _client(FixedResolver([PUBLIC]), connector) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(url)

        monkeypatch.setenv("SSL_CERT_FILE", str(pem))
        async with _client(FixedResolver([PUBLIC]), connector) as client:
            assert (await client.get(url)).status_code == 200


async def test_the_first_reachable_vetted_address_is_used():
    async with recording_server() as origin:
        connector = SpyConnector(forward_to=origin.port, fail_hosts=[PUBLIC])
        resolver = FixedResolver([PUBLIC, "93.184.216.35"])
        async with _client(resolver, connector) as client:
            response = await client.get("http://fallback.example.test:8080/")
        assert response.status_code == 200
        assert [host for host, _, _ in connector.calls] == [PUBLIC, "93.184.216.35"]


async def test_a_dead_ipv6_prefix_does_not_hide_a_live_ipv4_address():
    v6 = ["2606:4700::1", "2606:4700::2", "2606:4700::3"]
    async with recording_server() as origin:
        connector = SpyConnector(forward_to=origin.port, fail_hosts=v6)
        async with _client(FixedResolver(v6 + [PUBLIC]), connector) as client:
            response = await client.get("http://dual.example.test:8080/")
        assert response.status_code == 200
        assert [host for host, _, _ in connector.calls] == [v6[0], PUBLIC]
        assert origin.connections == 1


async def test_attempts_are_capped():
    addresses = [f"93.184.216.{n}" for n in range(30, 35)]
    connector = SpyConnector(fail_hosts=addresses)
    async with _client(FixedResolver(addresses), connector) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("http://down.example.test:8080/")
    assert len(connector.calls) == MAX_CONNECT_ATTEMPTS == 3


async def test_one_deadline_bounds_every_stalled_attempt():
    budget = 0.9
    connector = SpyConnector(stall=True)
    addresses = [f"93.184.216.{n}" for n in range(30, 35)]
    started = time.monotonic()
    async with _client(FixedResolver(addresses), connector, timeout=budget) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.get("http://stalled.example.test:8080/")
    elapsed = time.monotonic() - started

    assert len(connector.calls) == 3
    assert sum(timeout for _, _, timeout in connector.calls) <= budget
    assert elapsed < budget + 0.5


async def test_the_deadline_also_covers_name_resolution():
    budget = 0.9
    connector = SpyConnector(stall=True)
    addresses = [f"93.184.216.{n}" for n in range(30, 35)]

    async def slow_resolver(host: str, port: int):
        await connector.sleep(0.5)
        return addresses

    started = time.monotonic()
    async with _client(slow_resolver, connector, timeout=budget) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.get("http://slowdns.example.test:8080/")
    elapsed = time.monotonic() - started

    assert sum(timeout for _, _, timeout in connector.calls) <= budget - 0.4
    assert elapsed < budget + 0.5


async def test_a_resolver_that_never_answers_ends_at_the_deadline():
    connector = SpyConnector(stall=True)

    async def never(host: str, port: int):
        await connector.sleep(3600)
        return [PUBLIC]

    started = time.monotonic()
    async with _client(never, connector, timeout=0.4) as client:
        with pytest.raises(httpx.ConnectTimeout), anyio.fail_after(5):
            await client.get("http://never.example.test/")
    assert time.monotonic() - started < 0.4 + 0.5
    assert connector.calls == []


async def test_a_unix_socket_is_refused():
    backend = VettedNetworkBackend(STRICT)
    with pytest.raises(DestinationRefused):
        await backend.connect_unix_socket("/var/run/docker.sock")


def test_the_client_is_built_on_the_vetted_pool():
    """httpx does not expose the pool's network backend, so the transport swaps
    the pool. If a future httpx stops using it, this and the rebinding test fail."""
    client = build_http_client(policy=STRICT, timeout_seconds=5)
    transport = client._transport  # pyright: ignore[reportPrivateUsage]
    assert isinstance(transport, VettedAsyncTransport)
    pool = transport._pool  # pyright: ignore[reportPrivateUsage]
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    backend = pool._network_backend  # pyright: ignore[reportPrivateUsage]
    assert isinstance(backend, VettedNetworkBackend)
    assert client.trust_env is False
    assert client.follow_redirects is False


@pytest.mark.parametrize("pool", ["missing", "wrong-type"])
def test_an_httpx_without_the_expected_pool_is_refused_at_construction(
    monkeypatch, pool
):
    def stub(self, *args, **kwargs):
        if pool == "wrong-type":
            self._pool = object()

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", stub)
    with pytest.raises(RuntimeError, match="_pool"):
        VettedAsyncTransport(policy=STRICT, ssl_context=ssl.create_default_context())


def _proxy_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == egress_http.logger.name
    ]


def test_an_ignored_proxy_environment_is_reported_once(monkeypatch, caplog):
    monkeypatch.setattr(egress_http, "_proxy_environment_warned", False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    with caplog.at_level(logging.WARNING, logger=egress_http.logger.name):
        build_http_client(policy=STRICT, timeout_seconds=5)
        build_http_client(policy=STRICT, timeout_seconds=5)
    messages = _proxy_warnings(caplog)
    assert len(messages) == 1
    assert "HTTPS_PROXY" in messages[0]


def test_no_proxy_environment_means_no_warning(monkeypatch, caplog):
    monkeypatch.setattr(egress_http, "_proxy_environment_warned", False)
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    with caplog.at_level(logging.WARNING, logger=egress_http.logger.name):
        build_http_client(policy=STRICT, timeout_seconds=5)
    assert _proxy_warnings(caplog) == []
