from __future__ import annotations

from intric.flows.domain.flow import FlowPersistedJsonObject, clone_json_object
from intric.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    StepSpec,
)

_FILE_BASED_INPUT_TYPES = {
    InputType.AUDIO,
    InputType.DOCUMENT,
    InputType.FILE,
}

_FORMAT_TO_INPUT_TYPE: dict[str, InputType] = {
    t.value: t for t in _FILE_BASED_INPUT_TYPES
}

_DEFAULT_RUNTIME_INPUT_DESCRIPTIONS: dict[InputType, str] = {
    InputType.AUDIO: "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
    InputType.DOCUMENT: "Ladda upp dokument som detta steg ska analysera.",
    InputType.FILE: "Ladda upp filer som detta steg ska analysera.",
}


def resolve_runtime_input_config(
    *,
    step_spec: StepSpec,
    existing_input_config: FlowPersistedJsonObject | None = None,
) -> FlowPersistedJsonObject | None:
    """Return the effective input_config for a compiled AI Builder step."""
    base_config = clone_json_object(step_spec.input_config)
    if base_config is None:
        base_config = clone_json_object(existing_input_config)

    if not _requires_runtime_upload(step_spec):
        return _remove_runtime_input_config(base_config)

    effective_config = base_config if base_config is not None else {}
    runtime_input_config = (
        clone_json_object(effective_config.get("runtime_input")) or {}
    )
    runtime_input_config["enabled"] = True
    runtime_input_config.setdefault("required", False)

    previous_format = runtime_input_config.get("input_format")
    runtime_input_config["input_format"] = step_spec.input_type.value

    if previous_format is not None and previous_format != step_spec.input_type.value:
        _sync_description_after_type_change(
            runtime_input_config, previous_format, step_spec.input_type
        )
        # Stale mimetype constraints from the old format are invalid for the new type
        runtime_input_config.pop("accepted_mimetypes_override", None)
    else:
        runtime_input_config.setdefault(
            "description",
            _DEFAULT_RUNTIME_INPUT_DESCRIPTIONS[step_spec.input_type],
        )
    effective_config["runtime_input"] = runtime_input_config
    return effective_config


def _requires_runtime_upload(step_spec: StepSpec) -> bool:
    return (
        step_spec.input_source == InputSource.FLOW_INPUT
        and step_spec.input_type in _FILE_BASED_INPUT_TYPES
    )


def _sync_description_after_type_change(
    runtime_input_config: FlowPersistedJsonObject,
    previous_format: object,
    new_input_type: InputType,
) -> None:
    current_description = runtime_input_config.get("description")

    old_input_type = (
        _FORMAT_TO_INPUT_TYPE.get(previous_format)
        if isinstance(previous_format, str)
        else None
    )
    old_default = (
        _DEFAULT_RUNTIME_INPUT_DESCRIPTIONS.get(old_input_type)
        if old_input_type is not None
        else None
    )

    if current_description is None or current_description == old_default:
        runtime_input_config["description"] = _DEFAULT_RUNTIME_INPUT_DESCRIPTIONS[
            new_input_type
        ]


def _remove_runtime_input_config(
    value: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    if not isinstance(value, dict):
        return None

    updated = dict(value)
    updated.pop("runtime_input", None)
    return updated or None
