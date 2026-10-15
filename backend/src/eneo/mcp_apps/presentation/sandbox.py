"""Trusted web-host sandbox proxy for the MCP Apps double-iframe protocol.

Only this first-party shell is served as HTML. Approved server HTML travels
through the authenticated JSON response and SDK sandbox-resource-ready message.
"""

import json
from pathlib import Path

_SCRIPT = Path(__file__).with_name("sandbox.js").read_text()


def sandbox_document(host_origin: str) -> str:
    origin = json.dumps(host_origin).replace("<", "\\u003c")
    script = _SCRIPT.replace("__HOST_ORIGIN__", origin)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>html,body,iframe{margin:0;width:100%;height:100%;border:0;"
        "overflow:hidden;display:block}</style></head><body>"
        f"<script>{script}</script></body></html>"
    )
