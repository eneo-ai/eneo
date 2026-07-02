from __future__ import annotations

from collections.abc import Mapping


def is_authored_config(raw: Mapping[str, object] | None) -> bool:
    """Return whether the payload declares the authored HTTP config shape."""
    return isinstance(raw, Mapping) and "auth" in raw
