from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.parse import urlsplit

import httpx

from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.main.config import get_settings
from intric.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from intric.flows.variable_resolver import FlowVariableResolver

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class AssertConnectedPeerAllowedFn(Protocol):
    def __call__(
        self,
        *,
        response: httpx.Response,
        preflight_resolved_ips: set[IPAddress] | None,
    ) -> None: ...


class FlowHttpRuntimeHelper:
    """Flow-only HTTP helper utilities for input/webhook execution paths."""

    def __init__(
        self,
        *,
        variable_resolver: "FlowVariableResolver",
        request_timeout_seconds: float,
        max_timeout_seconds: float,
        allow_private_networks: bool,
    ) -> None:
        self.variable_resolver = variable_resolver
        self.request_timeout_seconds = request_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.allow_private_networks = allow_private_networks

    def resolve_timeout_seconds(
        self,
        timeout_value: Any,
        *,
        step_order: int,
        config_label: str,
    ) -> float:
        if timeout_value is None:
            return self.request_timeout_seconds
        if not isinstance(timeout_value, (int, float)):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be a number.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be greater than zero.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        if timeout_seconds > self.max_timeout_seconds:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds cannot exceed {self.max_timeout_seconds:g}.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            )
        return timeout_seconds

    @staticmethod
    def read_response_text(
        *,
        response: httpx.Response,
        step_order: int,
        code: str,
    ) -> str:
        response_bytes = response.content
        if len(response_bytes) > get_settings().flow_max_inline_text_bytes:
            raise TypedIOValidationException(
                f"Step {step_order}: HTTP response exceeded max inline text bytes.",
                code=code,
            )
        return response.text

    async def send_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        read_response_body: bool = True,
        preflight_resolved_ips: set[IPAddress] | None = None,
        assert_connected_peer_allowed: AssertConnectedPeerAllowedFn,
    ) -> httpx.Response:
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            request = client.build_request(
                method,
                url,
                headers=headers,
                content=body_bytes,
                json=json_body,
            )
            response = await client.send(request, stream=True)
            try:
                assert_connected_peer_allowed(
                    response=response,
                    preflight_resolved_ips=preflight_resolved_ips,
                )
            except Exception:
                await response.aclose()
                raise

            if not read_response_body:
                detached = httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    request=request,
                )
                await response.aclose()
                return detached

            max_bytes = get_settings().flow_max_inline_text_bytes
            response_bytes = bytearray()
            async for chunk in response.aiter_bytes():
                response_bytes.extend(chunk)
                if len(response_bytes) > max_bytes:
                    await response.aclose()
                    raise TypedIOValidationException(
                        "HTTP response exceeded max inline text bytes.",
                        code=FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE.value,
                    )

            detached = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(response_bytes),
                request=request,
            )
            await response.aclose()
            return detached

    async def assert_url_allowed(self, url: str) -> set[IPAddress] | None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise TypedIOValidationException(
                f"Unsupported HTTP URL scheme: '{parsed.scheme}'.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL.value,
            )
        host = parsed.hostname
        if not host:
            raise TypedIOValidationException(
                "HTTP URL must include a hostname.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL.value,
            )
        host_lower = host.strip().lower()
        if host_lower in {"localhost", "localhost.localdomain"}:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
            )
        if self.allow_private_networks:
            return None

        resolved_ips: list[IPAddress]
        try:
            resolved_ips = self.resolve_ip_literal(host_lower)
        except ValueError:
            resolved_ips = await self.resolve_host_ips(
                host=host_lower,
                port=parsed.port or (443 if parsed.scheme == "https" else 80),
            )

        if any(self.is_private_or_local_ip(item) for item in resolved_ips):
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
            )
        return set(resolved_ips)

    def assert_connected_peer_allowed(
        self,
        *,
        response: httpx.Response,
        preflight_resolved_ips: set[IPAddress] | None,
    ) -> None:
        if self.allow_private_networks:
            return

        network_stream = response.extensions.get("network_stream")
        if network_stream is None:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
            )

        server_addr = network_stream.get_extra_info("server_addr")
        if not isinstance(server_addr, tuple) or not server_addr:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
            )

        peer_value = cast(str, server_addr[0])

        try:
            peer_ip = ipaddress.ip_address(peer_value)
        except ValueError as exc:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
            ) from exc

        if self.is_private_or_local_ip(peer_ip):
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
            )

        if preflight_resolved_ips and peer_ip not in preflight_resolved_ips:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
            )

    @staticmethod
    def resolve_ip_literal(host: str) -> list[IPAddress]:
        return [ipaddress.ip_address(host)]

    @staticmethod
    async def resolve_host_ips(*, host: str, port: int) -> list[IPAddress]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise TypedIOValidationException(
                f"Unable to resolve HTTP host '{host}'.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
            ) from exc
        resolved: list[IPAddress] = []
        for _, _, _, _, sockaddr in infos:
            try:
                resolved.append(ipaddress.ip_address(sockaddr[0]))
            except ValueError:
                continue
        if not resolved:
            raise TypedIOValidationException(
                f"Unable to resolve HTTP host '{host}'.",
                code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR.value,
            )
        return resolved

    @staticmethod
    def is_private_or_local_ip(value: IPAddress) -> bool:
        return (
            value.is_loopback
            or value.is_private
            or value.is_link_local
            or value.is_multicast
            or value.is_reserved
            or value.is_unspecified
        )
