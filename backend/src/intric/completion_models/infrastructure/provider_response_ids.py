from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extract_provider_response_id(response: Any) -> str | None:
    candidates: list[Any] = []

    if isinstance(response, Mapping):
        candidates.append(response.get("id"))
    else:
        candidates.append(getattr(response, "id", None))
        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            try:
                payload = model_dump(mode="json")
            except TypeError:
                payload = model_dump()
            if isinstance(payload, Mapping):
                candidates.append(payload.get("id"))

    for candidate in candidates:
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return None
