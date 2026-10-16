"""Trusted web-host sandbox proxy for the MCP Apps double-iframe protocol.

Only this first-party shell is served as HTML. Approved server HTML travels
through the authenticated JSON response and SDK sandbox-resource-ready message.
"""

import json
from collections.abc import Sequence
from pathlib import Path

_SCRIPT = Path(__file__).with_name("sandbox.js").read_text()


def sandbox_document(host_origins: Sequence[str]) -> str:
    """The proxy page for the addresses Eneo is opened on.

    Several frontends may run side by side; the proxy answers whichever of
    them framed it and talks to that one alone from then on.
    """
    origins = json.dumps(list(host_origins)).replace("<", "\\u003c")
    script = _SCRIPT.replace("__HOST_ORIGINS__", origins)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>html,body,iframe{margin:0;width:100%;height:100%;border:0;"
        "overflow:hidden;display:block}</style></head><body>"
        f"<script>{script}</script></body></html>"
    )
