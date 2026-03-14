from __future__ import annotations

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
                return parts[-(trusted_proxy_count + 1)]

        # x-real-ip is commonly set by reverse proxies to the original client IP.
        real_ip = _get_header(request, trusted_proxy_headers, "x-real-ip")
        if real_ip:
            return real_ip.strip()

    client = request.client
    return client.host if client else None


def _get_header(request: "Request", headers: list[str], preferred: str) -> str | None:
    preferred_value = request.headers.get(preferred)
    if preferred_value:
        return preferred_value

    for header_name in headers:
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value
    return None
