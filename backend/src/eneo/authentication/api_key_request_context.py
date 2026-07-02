from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


def resolve_client_ip(
    request: "Request",
    *,
    trusted_proxy_count: int,
    trusted_proxy_headers: list[str],
) -> str | None:
    if trusted_proxy_count > 0:
        forwarded_for = _get_header(request, trusted_proxy_headers, "x-forwarded-for")
        if forwarded_for:
            parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            if len(parts) > trusted_proxy_count:
                return _validate_ip(parts[-(trusted_proxy_count + 1)])

        # x-real-ip is commonly set by reverse proxies to the original client IP.
        real_ip = _get_header(request, trusted_proxy_headers, "x-real-ip")
        if real_ip:
            return _validate_ip(real_ip.strip())

    client = request.client
    return _validate_ip(client.host) if client else None


def _validate_ip(value: str) -> str | None:
    # request.client.host can be a hostname (e.g. "testclient" from Starlette's
    # TestClient) and proxies may inject non-IP values. Audit logs use Postgres
    # INET and API-key allow-list checks call ipaddress.ip_network/ip_address —
    # both fail on a non-IP. Returning None lets callers treat it as "unknown"
    # rather than crash the worker or evaluate against a garbage value.
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def _get_header(request: "Request", headers: list[str], preferred: str) -> str | None:
    preferred_value = request.headers.get(preferred)
    if preferred_value:
        return preferred_value

    for header_name in headers:
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value
    return None
