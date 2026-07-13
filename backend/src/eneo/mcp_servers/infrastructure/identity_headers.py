"""Build the X-Eneo-* identity headers forwarded to opted-in remote MCP servers.

Forwarding the acting user/tenant identity is PII egress to a third party, so it
is opted into per server (``MCPServer.forward_identity``) and the header set is
built once per completion request and handed to every client; each client then
decides whether to send it based on its own server's flag.

Header values originate from user-controlled fields (email, display name), so
every value is sanitized for HTTP safety: CR/LF stripped (header-injection
guard) and encoded latin-1-safe (httpx encodes request headers as latin-1;
Swedish å/ä/ö are latin-1 but other Unicode is not, so non-encodable characters
are replaced rather than raising).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from eneo.tenants.tenant import TenantInDB
    from eneo.users.user import UserInDB


def _sanitize(value: Optional[str]) -> Optional[str]:
    """Return an HTTP-header-safe form of ``value``, or None when empty.

    Strips CR/LF and any other control characters, then forces the result into
    the latin-1 range httpx requires (non-encodable characters become "?").
    """
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch == " " or ch.isprintable())
    cleaned = cleaned.replace("\r", "").replace("\n", "").strip()
    if not cleaned:
        return None
    return cleaned.encode("latin-1", errors="replace").decode("latin-1")


def build_identity_headers(
    user: "UserInDB | None",
    tenant: "TenantInDB | None",
) -> dict[str, str]:
    """Return the X-Eneo-* identity headers for the acting user/tenant.

    Returns an empty dict when there is no user (e.g. service-key or worker
    contexts). Empty/None values are omitted so a server never receives a blank
    header. Callers forward the result only to servers with
    ``forward_identity=True``.
    """
    if user is None:
        return {}

    display_name = user.username or (user.email.split("@")[0] if user.email else None)
    role_names = ", ".join(
        role.name for role in user.roles if getattr(role, "name", None)
    )
    tenant_obj = tenant or getattr(user, "tenant", None)

    candidates: dict[str, Optional[str]] = {
        "X-Eneo-User-Id": str(user.id) if getattr(user, "id", None) else None,
        "X-Eneo-User-Email": user.email,
        "X-Eneo-User-Name": display_name,
        "X-Eneo-Tenant-Id": str(user.tenant_id) if user.tenant_id else None,
        "X-Eneo-Tenant-Name": getattr(tenant_obj, "name", None),
        "X-Eneo-Role": role_names or None,
    }

    headers: dict[str, str] = {}
    for header, raw in candidates.items():
        sanitized = _sanitize(raw)
        if sanitized is not None:
            headers[header] = sanitized
    return headers
