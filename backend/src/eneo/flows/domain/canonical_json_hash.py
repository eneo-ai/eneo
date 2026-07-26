from __future__ import annotations

import hashlib
import json


def canonical_json_hash(value: object) -> str:
    """Hash JSON-compatible data using the canonical Flows serialization."""

    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["canonical_json_hash"]
