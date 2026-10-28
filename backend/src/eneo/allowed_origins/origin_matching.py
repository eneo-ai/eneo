from urllib.parse import ParseResult, urlparse, urlsplit

from eneo.main.config import serialize_origin


def _safe_port(parsed: ParseResult) -> int | None:
    """Return ``parsed.port`` without raising on malformed values.

    ``urlparse('http://h:*').port`` raises ValueError because the wildcard is
    not an integer; treat that as "no fixed port" so the caller can interpret
    it however it wants.
    """
    try:
        return parsed.port
    except ValueError:
        return None


def _has_port_wildcard(parsed: ParseResult) -> bool:
    """A pattern like ``http://localhost:*`` indicates "any port matches".

    We strip optional ``user:pass@`` userinfo before checking so credentials
    embedded in a URL can't trigger a false positive.
    """
    host_and_port = parsed.netloc.rsplit("@", 1)[-1]
    return host_and_port.endswith(":*")


def origin_matches_pattern(origin: str, pattern: str) -> bool:
    """Whether a request's Origin matches one allowlist pattern.

    The Origin is client input and a pattern may be a stored typo, so a value
    that does not parse matches nothing rather than raising, which would turn a
    refused origin into a 500. ``serialize_origin`` is the one parser of the
    Origin: anything but an http(s) origin is refused.
    """
    origin_url = serialize_origin(origin)
    if origin_url is None:
        return False

    # Lowercase, IPv6 compressed and a valid port: this parse cannot fail.
    origin_parsed = urlsplit(origin_url)
    origin_scheme = origin_parsed.scheme
    origin_host = origin_parsed.hostname or ""
    origin_port = origin_parsed.port or (443 if origin_scheme == "https" else 80)

    if "://" not in pattern:
        pattern_host = pattern.lower()
        if pattern_host.startswith("*."):
            base = pattern_host[2:]
            if not origin_host.endswith(f".{base}"):
                return False
            origin_labels = origin_host.split(".")
            base_labels = base.split(".")
            return len(origin_labels) == len(base_labels) + 1
        return origin_host == pattern_host

    try:
        pattern_parsed = urlparse(pattern)
    except ValueError:
        return False
    if not pattern_parsed.scheme or not pattern_parsed.hostname:
        return False

    pattern_scheme = pattern_parsed.scheme.lower()
    pattern_host = pattern_parsed.hostname.lower()

    if pattern_scheme != origin_scheme:
        return False

    # Port handling. ``:*`` means "any port"; otherwise pin to the parsed
    # value (or the scheme default if absent).
    if not _has_port_wildcard(pattern_parsed):
        pattern_port = _safe_port(pattern_parsed) or (
            443 if pattern_scheme == "https" else 80
        )
        if pattern_port != origin_port:
            return False

    if pattern_host.startswith("*."):
        base = pattern_host[2:]
        if not origin_host.endswith(f".{base}"):
            return False
        origin_labels = origin_host.split(".")
        base_labels = base.split(".")
        return len(origin_labels) == len(base_labels) + 1

    return origin_host == pattern_host
