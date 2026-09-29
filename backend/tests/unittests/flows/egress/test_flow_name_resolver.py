"""Flow name resolution has its own small pool: a burst of stalled names chosen by
flow authors must not use up the threads that everything else in the process
resolves names with."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from types import SimpleNamespace

import anyio
import httpx
import pytest

from eneo.flows.runtime.egress import resolver as resolver_module
from eneo.flows.runtime.egress.http import build_http_client
from eneo.flows.runtime.egress.policy import (
    DestinationUnresolvable,
    FlowDestinationPolicy,
)
from eneo.flows.runtime.egress.resolver import BoundedResolver, flow_name_resolver
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows.egress.egress_test_support import SpyConnector

PUBLIC = "93.184.216.34"


class _Dns:
    """A getaddrinfo whose names starting with ``slow`` block until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.blocked = 0
        self._lock = threading.Lock()

    def __call__(self, host, port, *args, **kwargs):
        if str(host).startswith("slow"):
            with self._lock:
                self.blocked += 1
            self.release.wait(10)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))]


@pytest.fixture
def dns(monkeypatch):
    fake = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    yield fake
    fake.release.set()


def _shutdown(resolver: BoundedResolver) -> None:
    resolver._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]


async def _wait_until(condition, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


async def test_a_lookup_returns_the_addresses_as_text(dns):
    resolver = BoundedResolver(workers=2)
    assert await resolver("fast.test", 443) == [PUBLIC]
    _shutdown(resolver)


async def test_a_failed_lookup_is_unresolvable(monkeypatch):
    def failing(host, port, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing)
    resolver = BoundedResolver(workers=2)
    with pytest.raises(DestinationUnresolvable):
        await resolver("missing.test", 443)
    _shutdown(resolver)


async def test_an_oversized_lookup_result_is_refused_before_it_is_read(monkeypatch):
    class Unread(list):
        def __iter__(self):
            raise AssertionError("the result must not be converted")

    huge = Unread([(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 80))] * 65)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: huge)
    resolver = BoundedResolver(workers=1)
    with pytest.raises(DestinationUnresolvable):
        await resolver("huge.test", 80)
    _shutdown(resolver)


async def test_a_lookup_fails_at_once_when_every_slot_is_taken(dns):
    resolver = BoundedResolver(workers=2)
    stalled = [asyncio.create_task(resolver(f"slow{i}.test", 80)) for i in range(2)]
    await _wait_until(lambda: dns.blocked == 2)

    started = time.monotonic()
    with pytest.raises(DestinationUnresolvable), anyio.fail_after(2):
        await resolver("fast.test", 80)
    assert time.monotonic() - started < 0.2

    dns.release.set()
    await asyncio.gather(*stalled)
    assert await resolver("fast.test", 80) == [PUBLIC]
    _shutdown(resolver)


async def test_a_slot_is_held_until_the_thread_ends_not_until_the_await_does(dns):
    """A deadline abandons the await; the thread keeps running. The slot must
    stay taken for as long as the thread does."""
    resolver = BoundedResolver(workers=1)
    with pytest.raises(TimeoutError), anyio.fail_after(0.1):
        await resolver("slow0.test", 80)
    await _wait_until(lambda: dns.blocked == 1)

    with pytest.raises(DestinationUnresolvable), anyio.fail_after(2):
        await resolver("fast.test", 80)

    dns.release.set()
    await _wait_until(lambda: resolver._slots.acquire(blocking=False))  # pyright: ignore[reportPrivateUsage]
    resolver._slots.release()  # pyright: ignore[reportPrivateUsage]
    assert await resolver("fast.test", 80) == [PUBLIC]
    _shutdown(resolver)


async def test_stalled_flow_names_leave_the_event_loop_executor_alone(dns):
    """Forty flow runs with names that never answer: another user of the loop's
    default executor still resolves at once, and flow lookups past the pool fail
    at once instead of queueing behind the stalled ones."""
    resolver = BoundedResolver(workers=4)
    connector = SpyConnector(stall=True)
    policy = FlowDestinationPolicy(allow_private_networks=False)

    async def attacker(index: int) -> str:
        async with build_http_client(
            policy=policy,
            timeout_seconds=0.3,
            resolver=resolver,
            connector=connector,
        ) as client:
            try:
                await client.get(f"http://slow{index}.test/")
            except DestinationUnresolvable:
                return "unresolvable"
            except httpx.ConnectTimeout:
                return "timeout"
        return "ok"

    attackers = [asyncio.create_task(attacker(index)) for index in range(40)]
    await _wait_until(lambda: dns.blocked == 4)

    loop = asyncio.get_running_loop()
    started = time.monotonic()
    await asyncio.wait_for(loop.getaddrinfo("fast.test", 443), 1)
    assert time.monotonic() - started < 0.5

    started = time.monotonic()
    with pytest.raises(DestinationUnresolvable), anyio.fail_after(2):
        await resolver("fast.test", 443)
    assert time.monotonic() - started < 0.2

    outcomes = await asyncio.wait_for(asyncio.gather(*attackers), 5)
    assert outcomes.count("timeout") == 4
    assert outcomes.count("unresolvable") == 36

    dns.release.set()
    await _wait_until(lambda: resolver._slots.acquire(blocking=False))  # pyright: ignore[reportPrivateUsage]
    resolver._slots.release()  # pyright: ignore[reportPrivateUsage]
    _shutdown(resolver)


async def test_a_full_pool_is_a_typed_connection_error_for_the_sender(dns):
    resolver = BoundedResolver(workers=1)
    helper = FlowHttpRuntimeHelper(
        variable_resolver=SimpleNamespace(),  # pyright: ignore[reportArgumentType]
        request_timeout_seconds=5,
        max_timeout_seconds=5,
        allow_private_networks=False,
        client_factory=lambda **kwargs: build_http_client(
            resolver=resolver, connector=SpyConnector(stall=True), **kwargs
        ),
    )

    async def send(host: str):
        return await helper.send_request(
            method="GET", url=f"http://{host}/", headers={}, timeout_seconds=0.3
        )

    stalled = asyncio.create_task(send("slow0.test"))
    await _wait_until(lambda: dns.blocked == 1)
    with pytest.raises(TypedIOValidationException) as exc, anyio.fail_after(2):
        await send("fast.test")
    assert exc.value.code == "typed_io_http_connection_error"
    with pytest.raises(httpx.ConnectTimeout):
        await stalled

    dns.release.set()
    await _wait_until(lambda: resolver._slots.acquire(blocking=False))  # pyright: ignore[reportPrivateUsage]
    resolver._slots.release()  # pyright: ignore[reportPrivateUsage]
    _shutdown(resolver)


async def test_the_process_pool_is_sized_by_the_setting(dns, monkeypatch):
    monkeypatch.setattr(
        resolver_module,
        "get_settings",
        lambda: SimpleNamespace(flow_http_dns_workers=3),
    )
    flow_name_resolver.cache_clear()
    try:
        resolver = flow_name_resolver()
        assert resolver is flow_name_resolver()
        stalled = [asyncio.create_task(resolver(f"slow{i}.test", 80)) for i in range(3)]
        await _wait_until(lambda: dns.blocked == 3)
        with pytest.raises(DestinationUnresolvable), anyio.fail_after(2):
            await resolver("fast.test", 80)
        dns.release.set()
        await asyncio.gather(*stalled)
        _shutdown(resolver)
    finally:
        flow_name_resolver.cache_clear()
