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
from collections.abc import Iterable
from typing import Protocol, cast

import httpcore
import httpx

from eneo.flows.runtime.egress.policy import (
    Deadline,
    DestinationRefused,
    FlowDestinationPolicy,
    Resolver,
    vet_destination,
)
from eneo.flows.runtime.egress.resolver import flow_name_resolver

logger = logging.getLogger(__name__)

# More attempts would only spend the shared deadline on hosts that are down.
MAX_CONNECT_ATTEMPTS = 3

_PROXY_ENVIRONMENT_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_proxy_environment_warned = False


class VettedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        policy: FlowDestinationPolicy,
        *,
        resolver: Resolver | None = None,
        connector: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver or flow_name_resolver()
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
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(
                f"Resolving {host} exceeded the connect timeout"
            ) from exc
        attempts = addresses[:MAX_CONNECT_ATTEMPTS]
        failure: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for index, address in enumerate(attempts):
            budget = deadline.share(len(attempts) - index)
            if budget is not None and budget <= 0:
                break
            try:
                return await self._connector.connect_tcp(
                    str(address),
                    port,
                    timeout=budget,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                failure = exc
        raise failure or httpcore.ConnectTimeout(
            f"Connecting to {host} exceeded the connect timeout"
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
                policy, resolver=resolver, connector=connector
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
    _warn_once_if_proxy_environment_is_set()
    return httpx.AsyncClient(
        transport=VettedAsyncTransport(
            policy=policy,
            # trust_env=True keeps SSL_CERT_FILE / SSL_CERT_DIR (an enterprise CA
            # bundle); trust_env=False below is about proxies, not trust anchors.
            ssl_context=ssl_context or httpx.create_ssl_context(trust_env=True),
            resolver=resolver,
            connector=connector,
        ),
        timeout=httpx.Timeout(timeout_seconds),
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
            "Flow HTTP ignores proxy environment variables (%s are set): flow "
            "requests connect directly, under the destination policy.",
            ", ".join(names),
        )
