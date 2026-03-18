from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore, InputSource, InputType, StepSpec

JsonObject = dict[str, Any]

_FILE_BASED_INPUT_TYPES = {
    InputType.AUDIO,
    InputType.DOCUMENT,
    InputType.FILE,
}

_DEFAULT_RUNTIME_INPUT_DESCRIPTIONS: dict[InputType, str] = {
    InputType.AUDIO: "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
    InputType.DOCUMENT: "Ladda upp dokument som detta steg ska analysera.",
    InputType.FILE: "Ladda upp filer som detta steg ska analysera.",
}


def normalize_builder_draft_runtime_inputs(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    """Normalize runtime-upload defaults for newly proposed builder draft steps.

    Only new steps are normalized here. Existing-step edits are left untouched at the
    draft layer because the stored flow may already have richer runtime-input config
    that should be preserved during apply.
    """

    updated_steps = [
        step if step.existing_step_ref is not None else step.model_copy(update={
            "input_config": resolve_runtime_input_config(step_spec=step)
        })
        for step in spec.steps
    ]
    return spec.model_copy(update={"steps": updated_steps})


def resolve_runtime_input_config(
    *,
    step_spec: StepSpec,
    existing_input_config: JsonObject | None = None,
) -> JsonObject | None:
    """Return the effective input_config for a compiled AI Builder step."""
    base_config = _clone_json_object(step_spec.input_config)
    if base_config is None:
        base_config = _clone_json_object(existing_input_config)

    if not _requires_runtime_upload(step_spec):
        return _remove_runtime_input_config(base_config)

    effective_config = dict(base_config or {})
    runtime_input = effective_config.get("runtime_input")
    runtime_input_config = (
        dict(runtime_input)
        if isinstance(runtime_input, dict)
        else {}
    )
    runtime_input_config["enabled"] = True
    runtime_input_config.setdefault("input_format", step_spec.input_type.value)
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


def _clone_json_object(value: JsonObject | None) -> JsonObject | None:
    if isinstance(value, dict):
        return dict(value)
    return None


def _remove_runtime_input_config(value: JsonObject | None) -> JsonObject | None:
    if not isinstance(value, dict):
        return None

    updated = dict(value)
    updated.pop("runtime_input", None)
    return updated or None
