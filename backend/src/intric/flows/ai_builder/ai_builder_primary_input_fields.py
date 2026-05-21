from __future__ import annotations

from intric.flows.flow_authoring_spec import (
    InputType,
)

_PRIMARY_INPUT_FIELD_ALIASES: dict[InputType, frozenset[str]] = {
    InputType.TEXT: frozenset({"text", "input", "indata_text"}),
    InputType.JSON: frozenset({"json", "input_json", "indata_json"}),
    InputType.DOCUMENT: frozenset(
        {"document", "documents", "input_document", "indata_document"}
    ),
    InputType.FILE: frozenset({"file", "files", "input_file", "indata_file"}),
    InputType.AUDIO: frozenset(
        {
            "audio",
            "input_audio",
            "indata_audio",
            "transcript",
            "transcription",
            "transcription_text",
            "transcribed_text",
            "transkribering",
            "transkription",
            "transkription_text",
        }
    ),
}


def primary_input_shadow_alias_input_types() -> frozenset[InputType]:
    return frozenset(_PRIMARY_INPUT_FIELD_ALIASES)


def is_primary_runtime_input_shadow_field(
    *,
    variable_name: str,
    field_type: str | None,
    runtime_input_type: InputType | None,
) -> bool:
    """Return true when a form field duplicates the flow's primary run input.

    AI Builder form fields represent secondary runtime parameters such as
    audience, tone, case id, or report level. The primary material the flow
    processes is already supplied through Flow input/runtime upload, so a form
    field named after that primary input would create duplicate UX and token
    usage.
    """

    if runtime_input_type is None:
        return False
    normalized_name = variable_name.strip().casefold()
    if normalized_name not in _PRIMARY_INPUT_FIELD_ALIASES.get(
        runtime_input_type, frozenset()
    ):
        return False

    normalized_type = (field_type or "text").strip().casefold()
    return normalized_type in {"", "text"}


def split_primary_runtime_input_shadow_names(
    *,
    field_names: list[str],
    runtime_input_type: InputType | None,
) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for field_name in field_names:
        if is_primary_runtime_input_shadow_field(
            variable_name=field_name,
            field_type="text",
            runtime_input_type=runtime_input_type,
        ):
            dropped.append(field_name)
            continue
        kept.append(field_name)
    return kept, dropped


def remove_primary_runtime_input_shadow_names(
    *,
    field_names: list[str],
    runtime_input_type: InputType | None,
) -> list[str]:
    """Filter step form-field references that point at the primary input."""

    kept, _ = split_primary_runtime_input_shadow_names(
        field_names=field_names,
        runtime_input_type=runtime_input_type,
    )
    return kept


__all__ = [
    "is_primary_runtime_input_shadow_field",
    "primary_input_shadow_alias_input_types",
    "remove_primary_runtime_input_shadow_names",
    "split_primary_runtime_input_shadow_names",
]
