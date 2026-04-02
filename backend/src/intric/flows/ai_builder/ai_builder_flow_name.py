from __future__ import annotations

import re

MAX_FLOW_NAME_LENGTH = 120

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_flow_name(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", value).strip()
    if not normalized:
        raise ValueError("Flow names must not be empty.")
    if len(normalized) > MAX_FLOW_NAME_LENGTH:
        raise ValueError(
            f"Flow names must be at most {MAX_FLOW_NAME_LENGTH} characters long."
        )
    return normalized


def normalize_optional_flow_name(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_flow_name(value)
