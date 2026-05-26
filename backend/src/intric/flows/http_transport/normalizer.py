from __future__ import annotations

from collections.abc import Mapping


def is_authored_config(raw: Mapping[str, object] | None) -> bool:
    """Check if config is in authored format (has ``auth`` key)."""
    return isinstance(raw, Mapping) and "auth" in raw
