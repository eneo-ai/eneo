from __future__ import annotations

from typing import Any


def is_authored_config(raw: dict[str, Any] | None) -> bool:
    """Check if config is in authored format (has ``auth`` key)."""
    return isinstance(raw, dict) and "auth" in raw
