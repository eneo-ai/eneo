import re
from urllib.parse import ParseResult, urlparse

# A DNS label sequence with an optional leading `*.` wildcard, ASCII only
# (IDNs must be given in their punycode form, which is what browsers send).
_HOST_RE = re.compile(
    r"^(\*\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$",
    re.IGNORECASE,
)
_IPV6_HOST_RE = re.compile(r"^[0-9a-f:.]+$", re.IGNORECASE)


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
    origin_parsed = urlparse(origin)
    if not origin_parsed.scheme or not origin_parsed.hostname:
        return False

    origin_scheme = origin_parsed.scheme.lower()
    origin_host = origin_parsed.hostname.lower()
    origin_port_raw = _safe_port(origin_parsed)
    if origin_port_raw is None and ":" in origin_parsed.netloc.rsplit("@", 1)[-1]:
        # Inbound Origin had a malformed port — fail closed.
        return False
    origin_port = origin_port_raw or (443 if origin_scheme == "https" else 80)

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

    pattern_parsed = urlparse(pattern)
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


def normalize_origin_pattern(pattern: str) -> str:
    """Validate and canonicalise one allowed-origin entry.

    Accepts ``<scheme>://<host>[:port]`` with an http(s) scheme, where the host
    may carry a leading ``*.`` wildcard and the port may be ``*``; anything
    beyond the authority (path, query, fragment, userinfo) is rejected so a
    pasted page URL cannot silently become a pattern that never matches.
    """
    value = pattern.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            f"Invalid origin '{pattern}': must include scheme (http:// or https://) and host."
        )
    if parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError(
            f"Invalid origin '{pattern}': only scheme, host and optional port are allowed."
        )
    if not _has_port_wildcard(parsed):
        _safe_port(parsed)
        if parsed.port is None and ":" in parsed.netloc.rsplit("@", 1)[-1]:
            raise ValueError(f"Invalid origin '{pattern}': malformed port.")
    # The pattern ends up verbatim in a CSP frame-ancestors header, so the
    # host must be a plain DNS name (IDNA-encoded), an IP literal or a `*.`
    # wildcard of one: no spaces, semicolons or other directive syntax.
    # urlparse also drops tabs and newlines silently, so check the raw text.
    if value != "".join(value.split()):
        raise ValueError(f"Invalid origin '{pattern}': whitespace is not allowed.")
    host = parsed.hostname
    if "[" in parsed.netloc:
        if not _IPV6_HOST_RE.match(host):
            raise ValueError(f"Invalid origin '{pattern}': malformed host.")
    elif not _HOST_RE.match(host):
        raise ValueError(
            f"Invalid origin '{pattern}': host may only contain letters, digits,"
            " '.', '-' and a leading '*.' wildcard."
        )
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
