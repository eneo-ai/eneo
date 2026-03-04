from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlsplit

import httpx

from intric.main.config import get_settings
from intric.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from intric.flows.variable_resolver import FlowVariableResolver

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_TEMPLATE_ONLY_PATTERN = re.compile(r"^\s*\{\{\s*([^{}]+)\s*\}\}\s*$")


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
                code="typed_io_http_invalid_config",
            )
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds must be greater than zero.",
                code="typed_io_http_invalid_config",
            )
        if timeout_seconds > self.max_timeout_seconds:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.timeout_seconds cannot exceed {self.max_timeout_seconds:g}.",
                code="typed_io_http_invalid_config",
            )
        return timeout_seconds

    def build_headers(
        self,
        headers_raw: Any,
        *,
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> dict[str, str]:
        if headers_raw is None:
            return {}
        if not isinstance(headers_raw, dict):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.headers must be an object.",
                code="typed_io_http_invalid_config",
            )
        headers: dict[str, str] = {}
        for key, value in headers_raw.items():
            if not isinstance(key, str):
                raise TypedIOValidationException(
                    f"Step {step_order}: {config_label}.headers keys must be strings.",
                    code="typed_io_http_invalid_config",
                )
            rendered = self.interpolate_value(value, context=context)
            headers[key] = str(rendered)
        return headers

    def resolve_request_body(
        self,
        *,
        method: str,
        config: dict[str, Any],
        context: dict[str, Any],
        step_order: int,
        config_label: str,
    ) -> tuple[bytes | None, dict[str, Any] | list[Any] | None]:
        if method != "POST":
            return None, None
        body_template = config.get("body_template")
        body_json = config.get("body_json")
        if body_template is not None and not isinstance(body_template, str):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.body_template must be a string.",
                code="typed_io_http_invalid_config",
            )
        if body_json is not None and not isinstance(body_json, (dict, list)):
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label}.body_json must be an object or array.",
                code="typed_io_http_invalid_config",
            )
        if body_template is not None and body_json is not None:
            raise TypedIOValidationException(
                f"Step {step_order}: {config_label} cannot define both body_template and body_json.",
                code="typed_io_http_invalid_config",
            )
        if body_json is not None:
            interpolated_json = self.interpolate_value(body_json, context=context)
            if not isinstance(interpolated_json, (dict, list)):
                raise TypedIOValidationException(
                    f"Step {step_order}: {config_label}.body_json interpolation must produce object or array.",
                    code="typed_io_http_invalid_config",
                )
            return None, interpolated_json
        if body_template is not None:
            rendered = self.variable_resolver.interpolate(body_template, context)
            return rendered.encode("utf-8"), None
        return None, None

    def interpolate_value(self, value: Any, *, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            if _TEMPLATE_ONLY_PATTERN.match(value):
                rendered = self.variable_resolver.interpolate(value, context)
                try:
                    return json.loads(rendered)
                except (ValueError, json.JSONDecodeError):
                    return rendered
            return self.variable_resolver.interpolate(value, context)
        if isinstance(value, list):
            return [self.interpolate_value(item, context=context) for item in value]
        if isinstance(value, dict):
            return {
                str(item_key): self.interpolate_value(item_value, context=context)
                for item_key, item_value in value.items()
            }
        return value

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
                        code="typed_io_http_response_too_large",
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
                code="typed_io_http_invalid_url",
            )
        host = parsed.hostname
        if not host:
            raise TypedIOValidationException(
                "HTTP URL must include a hostname.",
                code="typed_io_http_invalid_url",
            )
        host_lower = host.strip().lower()
        if host_lower in {"localhost", "localhost.localdomain"}:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
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
                code="typed_io_http_ssrf_blocked",
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
                code="typed_io_http_connection_error",
            )

        server_addr = network_stream.get_extra_info("server_addr")
        if not isinstance(server_addr, tuple) or not server_addr:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            )

        peer_value = server_addr[0]
        if not isinstance(peer_value, str):
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            )

        try:
            peer_ip = ipaddress.ip_address(peer_value)
        except ValueError as exc:
            raise TypedIOValidationException(
                "Unable to verify HTTP peer address.",
                code="typed_io_http_connection_error",
            ) from exc

        if self.is_private_or_local_ip(peer_ip):
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
            )

        if preflight_resolved_ips and peer_ip not in preflight_resolved_ips:
            raise TypedIOValidationException(
                "HTTP URL blocked by SSRF policy.",
                code="typed_io_http_ssrf_blocked",
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
                code="typed_io_http_connection_error",
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
                code="typed_io_http_connection_error",
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
