import ipaddress
import re
from urllib.parse import ParseResult, urlparse, urlsplit

from eneo.main.config import serialize_origin

# A DNS label sequence with an optional leading `*.` wildcard, ASCII only
# (IDNs must be given in their punycode form, which is what browsers send).
# A wildcard needs at least two labels after it: `*.kommun.se` names one
# organisation's hosts, `*.se` would let every site in a country frame the
# chat. The lenient form reads patterns saved before that rule.
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOST_RE = re.compile(
    rf"^(?:\*\.{_LABEL}\.{_LABEL}(?:\.{_LABEL})*|{_LABEL}(?:\.{_LABEL})*)$",
    re.IGNORECASE,
)
_LENIENT_HOST_RE = re.compile(rf"^(\*\.)?{_LABEL}(?:\.{_LABEL})*$", re.IGNORECASE)
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


def _canonical_host(host: str) -> str | None:
    """A pattern host in the form ``serialize_origin`` gives the Origin's.

    An IPv6 literal is compressed, so any written form of an address matches
    the one a browser sends; any other host is returned as is. None when the
    host has a colon but is no IPv6 address, which matches nothing.
    """
    if ":" not in host:
        return host
    try:
        return ipaddress.IPv6Address(host).compressed
    except ValueError:
        return None


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
        pattern_host = _canonical_host(pattern.lower())
        if pattern_host is None:
            return False
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
    pattern_host = _canonical_host(pattern_parsed.hostname.lower())
    if pattern_host is None:
        return False

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


def is_too_broad_wildcard(pattern: str) -> bool:
    """Whether a pattern's ``*.`` wildcard covers a whole top-level domain.

    A pattern saved before the two-label rule may still carry one. The
    visitor surface never honours it and the admin overview reports it.
    """
    host = pattern.split("://", 1)[-1].rsplit("@", 1)[-1]
    if host.startswith("["):
        return False
    host = host.split(":", 1)[0]
    return host.startswith("*.") and "." not in host[2:]


def normalize_origin_pattern(pattern: str, *, allow_too_broad: bool = False) -> str:
    """Validate and canonicalise one allowed-origin entry.

    Accepts ``<scheme>://<host>[:port]`` with an http(s) scheme, where the host
    may carry a leading ``*.`` wildcard and the port may be ``*``; anything
    beyond the authority (path, query, fragment, userinfo) is rejected so a
    pasted page URL cannot silently become a pattern that never matches.

    ``allow_too_broad`` reads a stored pattern whose wildcard covers a whole
    top-level domain; saving one is refused.
    """
    value = pattern.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(
            f"Invalid origin '{pattern}': must include scheme (http:// or https://) and host."
        )
    # urlparse reports an empty query, fragment or userinfo ("https://h?",
    # "https://@h") as absent, so the delimiters are checked in the raw text.
    if (
        parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or "@" in parsed.netloc
        or "?" in value
        or "#" in value
    ):
        raise ValueError(
            f"Invalid origin '{pattern}': only scheme, host and optional port are allowed."
        )
    if not _has_port_wildcard(parsed):
        _safe_port(parsed)
        # The colons inside a bracketed IPv6 literal are not a port separator.
        host_and_port = parsed.netloc.rsplit("@", 1)[-1]
        after_host = host_and_port.rsplit("]", 1)[-1]
        if parsed.port is None and ":" in after_host:
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
    elif not (_LENIENT_HOST_RE if allow_too_broad else _HOST_RE).match(host):
        if _LENIENT_HOST_RE.match(host):
            raise ValueError(
                f"Invalid origin '{pattern}': a wildcard needs at least two"
                " labels after '*.', for example https://*.kommun.se."
            )
        raise ValueError(
            f"Invalid origin '{pattern}': host may only contain letters, digits,"
            " '.', '-' and a leading '*.' wildcard."
        )
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
