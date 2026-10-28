from collections.abc import Mapping

_SAFE_METHODS = frozenset({"GET", "HEAD"})


def browser_request_allowed(method: str, headers: Mapping[str, str]) -> bool:
    """Whether a request may authenticate with the browser session cookie.

    ``headers`` must look names up case-insensitively, as Starlette's
    ``Headers`` does. ``Sec-Fetch-Site`` decides alone when present. Supported
    browsers always send it, so a request without it is a same-origin read or a
    non-browser client; it may only read, and only without ``Origin``, which
    every cross-origin CORS request carries.
    """
    safe = method.upper() in _SAFE_METHODS
    site = headers.get("sec-fetch-site")
    if site is None:
        return safe and "origin" not in headers
    site = site.strip().lower()
    if site == "same-origin":
        return True
    if site == "none":
        return safe
    return False
