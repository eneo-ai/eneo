"""Host-scoping for credentialed crawler fetches.

Eneo holds each website's HTTP Basic Auth credentials and, in the post-Kravla
paths that fetch directly (linked-file downloads, sitemap probes), reaches out
to URLs that originate from the crawled site or the crawler service. Those URLs
must never cause credentials to leave the registered host: ``HttpAuthCredentials``
is domain-locked precisely so that ``credentials must only ever be sent to the
exact domain they were registered for``. These helpers re-assert that invariant
at the direct-fetch boundary, where the crawl seed host is the only host allowed
to receive the request (and the credentials).
"""

from urllib.parse import urlparse


def host_of(url: str) -> str | None:
    """The lowercased ``host[:port]`` of an http(s) URL.

    Returns ``None`` for any non-http(s) scheme or a URL with no host, so a
    caller can treat ``None`` as "not in scope" without a separate scheme check.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname:
        return None
    return parsed.netloc.lower()


def same_host(url: str, allowed_host: str | None) -> bool:
    """True when ``url`` is an http(s) URL whose ``host[:port]`` equals
    ``allowed_host`` (case-insensitive). False for any other scheme, a hostless
    URL, an off-host URL, or when ``allowed_host`` itself is missing."""
    if not allowed_host:
        return False
    candidate = host_of(url)
    return candidate is not None and candidate == allowed_host.lower()
