"""The flow HTTP client: it connects only to addresses the policy vetted.

Vetting happens inside the connection the client opens (httpcore's network
backend), not before it. Resolution, classification and connect are one step,
so a DNS answer that changes between "checked" and "used" cannot exist, and no
byte is sent unless the connection is to a vetted IP literal. httpcore still
gives the URL's host name to TLS, so SNI, certificate verification and the Host
header are those of the URL.

The connect timeout is one deadline for name resolution and every TCP connection
attempt. The TLS handshake that follows (httpcore gives it the connect timeout
again) and each read and write are timed separately by httpx.

The client ignores proxy environment variables: a proxy would connect for us,
and the policy could only vet the proxy, not the destination.
"""

from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Callable, Iterable
from typing import Protocol, cast

import httpcore
import httpx

from eneo.flows.runtime.egress.policy import (
    Deadline,
    DestinationRefused,
    FlowDestinationPolicy,
    Resolver,
    connect_to_first_answering,
    vet_destination,
)
from eneo.flows.runtime.egress.resolver import flow_name_resolver

logger = logging.getLogger(__name__)

_PROXY_ENVIRONMENT_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_proxy_environment_warned = False


class VettedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        policy: FlowDestinationPolicy,
        *,
        resolver: Resolver | None = None,
        connector: httpcore.AsyncNetworkBackend | None = None,
        on_refused: Callable[[], None] | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver or flow_name_resolver()
        self._on_refused = on_refused
        # httpcore.AnyIOBackend is a real network backend; its conditional export
        # hides that from the type checker.
        self._connector = connector or cast(
            httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend()
        )

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        deadline = Deadline(timeout)
        try:
            addresses = await vet_destination(
                host,
                port,
                policy=self._policy,
                deadline=deadline,
                resolver=self._resolver,
            )
        except DestinationRefused:
            if self._on_refused is not None:
                self._on_refused()
            raise
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(
                f"Resolving {host} exceeded the connect timeout"
            ) from exc
        return await connect_to_first_answering(
            addresses,
            deadline=deadline,
            connect=lambda address, budget: self._connector.connect_tcp(
                str(address),
                port,
                timeout=budget,
                local_address=local_address,
                socket_options=socket_options,
            ),
            retry_on=(httpcore.ConnectError, httpcore.ConnectTimeout),
            timed_out=lambda: httpcore.ConnectTimeout(
                f"Connecting to {host} exceeded the connect timeout"
            ),
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise DestinationRefused(path)

    async def sleep(self, seconds: float) -> None:
        await self._connector.sleep(seconds)


class VettedAsyncTransport(httpx.AsyncHTTPTransport):
    """httpx's transport with its connection pool opening vetted connections.

    httpx does not expose the pool's network backend, so the pool is replaced
    after construction; a contract test fails if a future httpx stops using it.
    """

    def __init__(
        self,
        *,
        policy: FlowDestinationPolicy,
        ssl_context: ssl.SSLContext,
        resolver: Resolver | None = None,
        connector: httpcore.AsyncNetworkBackend | None = None,
        on_refused: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(verify=ssl_context, trust_env=False, retries=0)
        if not isinstance(getattr(self, "_pool", None), httpcore.AsyncConnectionPool):
            raise RuntimeError(
                "httpx no longer keeps an httpcore.AsyncConnectionPool at "
                "AsyncHTTPTransport._pool; the vetted transport has to be reviewed "
                "against this httpx version"
            )
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            http1=True,
            http2=False,
            retries=0,
            network_backend=VettedNetworkBackend(
                policy, resolver=resolver, connector=connector, on_refused=on_refused
            ),
        )


class ClientFactory(Protocol):
    def __call__(
        self, *, policy: FlowDestinationPolicy, timeout_seconds: float
    ) -> httpx.AsyncClient: ...


def build_http_client(
    *,
    policy: FlowDestinationPolicy,
    timeout_seconds: float,
    ssl_context: ssl.SSLContext | None = None,
    resolver: Resolver | None = None,
    connector: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncClient:
    return _vetted_client(
        policy=policy,
        timeout=httpx.Timeout(timeout_seconds),
        headers=None,
        ssl_context=ssl_context,
        resolver=resolver,
        connector=connector,
        on_refused=None,
    )


class VettedClientFactory:
    """Builds, for a library that sends its requests through a client it is
    given (the MCP client of a tool step), clients whose every connection is
    to an address ``policy`` allows for the name as ``resolver`` answers it
    at that connection, and says whether it refused one."""

    def __init__(self, *, policy: FlowDestinationPolicy, resolver: Resolver) -> None:
        self._policy = policy
        self._resolver = resolver
        self._refused = False

    def __call__(
        self, *, headers: dict[str, str], timeout: httpx.Timeout
    ) -> httpx.AsyncClient:
        return _vetted_client(
            policy=self._policy,
            timeout=timeout,
            headers=headers,
            ssl_context=None,
            resolver=self._resolver,
            connector=None,
            on_refused=self._note_refused,
        )

    def refused_a_connection(self) -> bool:
        """Whether a client of this factory was refused a connection by the
        policy."""
        return self._refused

    def _note_refused(self) -> None:
        self._refused = True


def _vetted_client(
    *,
    policy: FlowDestinationPolicy,
    timeout: httpx.Timeout,
    headers: dict[str, str] | None,
    ssl_context: ssl.SSLContext | None,
    resolver: Resolver | None,
    connector: httpcore.AsyncNetworkBackend | None,
    on_refused: Callable[[], None] | None,
) -> httpx.AsyncClient:
    _warn_once_if_proxy_environment_is_set()
    return httpx.AsyncClient(
        transport=VettedAsyncTransport(
            policy=policy,
            # trust_env=True keeps SSL_CERT_FILE / SSL_CERT_DIR (an enterprise CA
            # bundle); trust_env=False below is about proxies, not trust anchors.
            ssl_context=ssl_context or httpx.create_ssl_context(trust_env=True),
            resolver=resolver,
            connector=connector,
            on_refused=on_refused,
        ),
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )


def _warn_once_if_proxy_environment_is_set() -> None:
    global _proxy_environment_warned
    if _proxy_environment_warned:
        return
    names = sorted(
        name
        for name in os.environ
        if name.upper() in _PROXY_ENVIRONMENT_VARIABLES and os.environ[name]
    )
    if names:
        _proxy_environment_warned = True
        logger.warning(
            "Flow HTTP requests and MCP tool calls ignore proxy environment "
            "variables (%s are set): they connect directly, under the "
            "destination policy.",
            ", ".join(names),
        )
