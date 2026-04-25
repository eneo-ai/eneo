from __future__ import annotations

from typing import Any, cast


def clean_raw_previous_field_refs(refs: Any) -> list[dict[str, Any]]:
    """Return parse-safe structured field refs from untrusted LLM payloads."""

    if not isinstance(refs, list):
        return []

    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for raw_ref in cast(list[Any], refs):
        if not isinstance(raw_ref, dict):
            continue
        raw_ref_dict = cast(dict[str, Any], raw_ref)
        from_step = raw_ref_dict.get("from_step")
        field_path_raw = raw_ref_dict.get("field_path")
        if not isinstance(from_step, int) or from_step < 1:
            continue
        if not isinstance(field_path_raw, str):
            continue
        field_path = field_path_raw.strip()
        if not _is_valid_field_path(field_path):
            continue
        key = (from_step, field_path)
        if key in seen:
            continue
        seen.add(key)
        cleaned_ref: dict[str, Any] = {
            "from_step": from_step,
            "field_path": field_path,
        }
        label = raw_ref_dict.get("label")
        if isinstance(label, str) and label.strip():
            cleaned_ref["label"] = label.strip()
        cleaned.append(cleaned_ref)
    return cleaned


def clean_raw_form_field_refs(refs: Any) -> list[str]:
    """Return parse-safe form field names from untrusted LLM payloads."""

    if not isinstance(refs, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_ref in cast(list[Any], refs):
        if not isinstance(raw_ref, str):
            continue
        field_name = raw_ref.strip()
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        cleaned.append(field_name)
    return cleaned


def _is_valid_field_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    field_path = value.strip()
    if not field_path:
        return False
    return all(segment.strip() for segment in field_path.split("."))


__all__ = [
    "clean_raw_form_field_refs",
    "clean_raw_previous_field_refs",
]
