"""Content-Security-Policy construction for served MCP App view HTML.

The host builds the CSP; the app can only widen it through the domain lists
declared in its resource's ``_meta.ui.csp`` block. Omitted lists stay at
their restrictive defaults, and entries that do not parse as bare
``http(s)://host[:port]`` origins are dropped (never widened) so a malformed
declaration cannot smuggle in extra sources.
"""

import re
from typing import Any, Optional, cast
from urllib.parse import urlsplit

from eneo.main.logging import get_logger

logger = get_logger(__name__)

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+(:\d{1,5})?$")


def _valid_origins(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    origins: list[str] = []
    for value in cast(list[Any], values):
        if not isinstance(value, str):
            continue
        try:
            parts = urlsplit(value)
        except ValueError:
            logger.warning("Dropping unparseable CSP domain entry: %r", value)
            continue
        if (
            parts.scheme in ("http", "https")
            and parts.netloc
            and _HOST_RE.match(parts.netloc)
            and not parts.path
            and not parts.query
            and not parts.fragment
        ):
            origins.append(f"{parts.scheme}://{parts.netloc}")
        else:
            logger.warning("Dropping invalid CSP domain entry: %r", value)
    return origins


def declared_domains(ui_csp: Optional[dict[str, Any]]) -> dict[str, list[str]]:
    """The hosts a view's declaration opens, as the served policy will have them.

    Keyed by the declaration's own list names; entries that are not bare
    origins are already dropped.
    """
    csp = ui_csp or {}
    domains = {
        name: _valid_origins(csp.get(name))
        for name in (
            "connectDomains",
            "resourceDomains",
            "frameDomains",
            "baseUriDomains",
        )
    }
    # Nested frames are not part of the effective policy.
    domains["frameDomains"] = []
    return domains


def build_app_csp(
    ui_csp: Optional[dict[str, Any]],
    *,
    frame_ancestors: Optional[str] = None,
) -> str:
    """Build the CSP header value for one served view."""
    domains = declared_domains(ui_csp)
    resource_domains = domains["resourceDomains"]
    connect_domains = domains["connectDomains"]
    base_uri_domains = domains["baseUriDomains"]

    script_src = " ".join(["'self'", "'unsafe-inline'"] + resource_domains)
    img_src = " ".join(["'self'", "data:"] + resource_domains)
    font_src = " ".join(["'self'"] + resource_domains)
    # A view reaches the network only where its server declared it will. Its
    # own origin serves views and nothing a view has reason to call.
    connect_src = " ".join(connect_domains) if connect_domains else "'none'"
    # The outer policy also governs navigation of its untrusted srcdoc child.
    # Never widen this from app metadata: doing so transfers the bridge to a
    # navigated page. Nested frames are deliberately unsupported.
    frame_src = "'none'"
    base_uri = " ".join(base_uri_domains) if base_uri_domains else "'self'"

    directives = [
        # This response is Eneo's trusted proxy, never server HTML. Its child
        # additionally has sandbox="allow-scripts" (opaque origin).
        "sandbox allow-scripts allow-same-origin",
        "default-src 'none'",
        "object-src 'none'",
        "worker-src 'none'",
        "script-src " + script_src,
        "style-src " + script_src,
        "img-src " + img_src,
        "font-src " + font_src,
        "connect-src " + connect_src,
        "frame-src " + frame_src,
        "base-uri " + base_uri,
        "form-action 'none'",
    ]
    # Only Eneo may frame a view; where its address is not known, nothing may.
    directives.append("frame-ancestors " + (frame_ancestors or "'none'"))
    return "; ".join(directives)
