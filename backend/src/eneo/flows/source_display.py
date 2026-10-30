from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def format_source_display_name(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        return stripped
    if not stripped.startswith(("http://", "https://")):
        return stripped
    try:
        parsed = urlsplit(stripped)
    except ValueError:
        return stripped
    hostname = parsed.hostname or ""
    path = parsed.path.rstrip("/")
    if hostname and path:
        return f"{hostname}{path}"
    if hostname:
        return hostname
    return stripped


def format_source_container_display_name(reference: dict[str, Any]) -> str | None:
    raw_name = reference.get("source_container_name_raw") or reference.get(
        "source_container_name"
    )
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    raw_url = _resolve_reference_url(reference)
    if raw_url is not None:
        try:
            parsed = urlsplit(raw_url)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.hostname:
            return parsed.hostname
    raw_kind = reference.get("source_container_kind")
    if isinstance(raw_kind, str) and raw_kind.strip():
        return raw_kind.strip()
    return None


def format_source_container_label(reference: dict[str, Any]) -> str | None:
    label = format_source_container_display_name(reference)
    if label is None:
        return None
    container_kind = reference.get("source_container_kind")
    if container_kind == "collection" and not label.lower().startswith("collection: "):
        return f"Collection: {label}"
    return label


def resolve_reference_title(reference: dict[str, Any]) -> str | None:
    for key in ("source_title", "title", "source_url"):
        raw_value = reference.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _resolve_reference_url(reference: dict[str, Any]) -> str | None:
    for key in ("source_url", "source_title", "title"):
        raw_value = reference.get(key)
        if not isinstance(raw_value, str):
            continue
        stripped = raw_value.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped
    return None
