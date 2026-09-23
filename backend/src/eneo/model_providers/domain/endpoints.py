"""Provider endpoint URLs as admins paste them."""


def normalize_endpoint_base(base: str) -> str:
    """Strip a trailing slash and an optional ``/v1`` suffix so users can
    paste either ``https://api.example.com`` or ``https://api.example.com/v1``
    without us producing ``/v1/v1/...`` paths."""
    s = base.rstrip("/")
    if s.endswith("/v1"):
        s = s[:-3].rstrip("/")
    return s
