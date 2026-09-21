"""Canonical HTTP source identities; display metadata remains unchanged."""

from urllib.parse import urljoin, urlsplit, urlunsplit


def normalize_url(url: str, *, base_url: str | None = None) -> str | None:
    """Return a stable HTTP URL identity, or None for unsupported links."""

    try:
        absolute = urljoin(base_url, url) if base_url else url
        parsed = urlsplit(absolute)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname:
        return None

    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, host, path, parsed.query, ""))
