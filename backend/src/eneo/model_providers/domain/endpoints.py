"""Endpoint URLs as admins paste them, and the destinations keys are sent to."""

from urllib.parse import urlsplit

from eneo.main.exceptions import BadRequestException


def normalize_endpoint_base(base: str) -> str:
    """Strip a trailing slash and an optional ``/v1`` suffix so users can
    paste either ``https://api.example.com`` or ``https://api.example.com/v1``
    without us producing ``/v1/v1/...`` paths."""
    s = base.rstrip("/")
    if s.endswith("/v1"):
        s = s[:-3].rstrip("/")
    return s


def normalize_destination(endpoint: str | None) -> str | None:
    """Canonical ``scheme://host[:port]/path`` for comparing destinations.

    Scheme and host are case-insensitive, a default port is the same as no
    port, and trailing slashes do not change where a request goes. A
    different scheme, host, port, base path or query does.
    """
    if endpoint is None:
        return None
    value = endpoint.strip()
    if not value:
        return None
    parts = urlsplit(value if "://" in value else f"//{value}")
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port: int | None = parts.port
    except ValueError:
        port = None
        host = parts.netloc.lower()
    if (scheme, port) in (("http", 80), ("https", 443)):
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def is_masked_api_key(value: str) -> bool:
    """A value that is only the display form of a key, never a key."""
    stripped = value.strip()
    return stripped.startswith("...") or set(stripped) <= set("*•·")


def require_key_for_destination(
    *,
    stored_destination: str | None,
    proposed_destination: str | None,
    key_stored: bool,
    replacement_key: str | None,
) -> None:
    """A stored key is never sent to a destination it was not entered for.

    A masked display value is refused as a key. When the destination moves
    and a key is stored, the change must carry an explicitly typed
    replacement; an omitted or blank key is refused before anything is
    written. A key entered for an unchanged destination is checked only for
    shape.
    """
    if (
        replacement_key is not None
        and replacement_key.strip()
        and is_masked_api_key(replacement_key)
    ):
        raise BadRequestException(
            "The API key looks like the masked display value; enter the actual key."
        )
    if not key_stored or normalize_destination(
        stored_destination
    ) == normalize_destination(proposed_destination):
        return
    if replacement_key is None or not replacement_key.strip():
        raise BadRequestException(
            "Changing the endpoint requires entering a new API key; "
            "the stored key is not reused for a different destination."
        )
