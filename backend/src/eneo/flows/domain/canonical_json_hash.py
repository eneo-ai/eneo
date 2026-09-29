from __future__ import annotations

import hashlib
import json


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON-compatible data using the canonical Flows encoding."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def is_json_container(value: object) -> bool:
    return isinstance(value, (dict, list))


def json_values_differ(stored: object, incoming: object) -> bool:
    """Whether two values differ, JSON being compared as JSON: `True` is not
    `1`, `1.0` is not `1`, and the order of keys is no difference. Anything
    else is compared as Python compares it."""

    if is_json_container(stored) or is_json_container(incoming):
        return canonical_json_bytes(stored) != canonical_json_bytes(incoming)
    return stored != incoming


def canonical_json_hash(value: object) -> str:
    """Hash JSON-compatible data using the canonical Flows serialization."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "canonical_json_bytes",
    "canonical_json_hash",
    "is_json_container",
    "json_values_differ",
]
