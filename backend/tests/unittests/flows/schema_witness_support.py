"""Independent oracles for the template-bound contract tests.

`all_plain` restates what the compiler may edit, written from the rule and not
from the production code; `witness` builds one instance a plain schema accepts,
so a test can show that an edited contract is still satisfiable.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PLAIN_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "title",
        "description",
        "examples",
        "default",
        "$comment",
    }
)


def all_plain(schema: Any) -> bool:
    """Whether every schema node anywhere carries only structural and annotation keywords."""

    if not isinstance(schema, dict):
        return False
    if not set(schema) <= PLAIN_KEYWORDS:
        return False
    declared = schema.get("properties", {})
    if schema.get("additionalProperties") is False and any(
        key not in declared for key in schema.get("required", [])
    ):
        return False  # a closed object that requires a key it does not declare
    subschemas: list[Any] = (
        list(schema.get("properties", {}).values())
        if isinstance(schema.get("properties", {}), dict)
        else [None]
    )
    for keyword in ("items", "additionalProperties"):
        if keyword in schema and not isinstance(schema[keyword], bool):
            subschemas.append(schema[keyword])
    return all(all_plain(sub) for sub in subschemas)


def witness(schema: dict[str, Any]) -> Any:
    """One instance of a plain schema: "" for text, 0, False, [] for arrays.

    An object has every required key: from its properties, else from the
    additionalProperties schema, else "".
    """

    kind = schema.get("type")
    kind = kind[0] if isinstance(kind, list) and kind else kind
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        return {
            key: witness(
                properties[key]
                if key in properties
                else (extra if isinstance(extra, dict) else {})
            )
            for key in schema.get("required", [])
        }
    if kind == "array":
        return []
    if kind in ("number", "integer"):
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return ""


@contextmanager
def local_listener() -> Iterator[tuple[str, list[str]]]:
    """A real listener on 127.0.0.1: yields its base URL and the paths requested.

    A validator that resolves a remote `$ref` shows up here as a request.
    """

    requested: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
