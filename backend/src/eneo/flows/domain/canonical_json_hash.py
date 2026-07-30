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


def canonical_json_hash(value: object) -> str:
    """Hash JSON-compatible data using the canonical Flows serialization."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = ["canonical_json_bytes", "canonical_json_hash"]
