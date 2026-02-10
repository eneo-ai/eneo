from urllib.parse import urlparse


def origin_matches_pattern(origin: str, pattern: str) -> bool:
    origin_parsed = urlparse(origin)
    if not origin_parsed.scheme or not origin_parsed.hostname:
        return False

    origin_scheme = origin_parsed.scheme.lower()
    origin_host = origin_parsed.hostname.lower()
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

    pattern_parsed = urlparse(pattern)
    if not pattern_parsed.scheme or not pattern_parsed.hostname:
        return False

    pattern_scheme = pattern_parsed.scheme.lower()
    pattern_host = pattern_parsed.hostname.lower()
    pattern_port = pattern_parsed.port or (443 if pattern_scheme == "https" else 80)

    if pattern_scheme != origin_scheme or pattern_port != origin_port:
        return False

    if pattern_host.startswith("*."):
        base = pattern_host[2:]
        if not origin_host.endswith(f".{base}"):
            return False
        origin_labels = origin_host.split(".")
        base_labels = base.split(".")
        return len(origin_labels) == len(base_labels) + 1

    return origin_host == pattern_host
