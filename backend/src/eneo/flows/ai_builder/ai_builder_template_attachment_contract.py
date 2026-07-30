from __future__ import annotations

from collections.abc import Mapping

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    ArchitectureLogValue,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
)
from eneo.flows.domain.flow import clone_json_object
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_variable_definitions import (
    PREVIOUS_STEP_TEXT_ALIAS,
    form_field_reference_expression,
    template_placeholder_form_field_name,
)

_LOCAL_TEMPLATE_CONFIG_KEYS = frozenset(
    {
        "template_asset_id",
        "template_checksum",
        "template_file_id",
        "template_name",
        "placeholders",
    }
)
_MAX_DIAGNOSTIC_PLACEHOLDER_LENGTH = 80
_TRANSCRIPTION_PLACEHOLDERS = frozenset(
    {
        FLOW_INPUT_TRANSCRIPTION_KEY,
        f"flow_input.{FLOW_INPUT_TRANSCRIPTION_KEY}",
        f"flow.input.{FLOW_INPUT_TRANSCRIPTION_KEY}",
    }
)


def apply_template_attachment_contract(
    spec: FlowDraftSpecCore,
    *,
    selected_template_count: int,
    placeholders: tuple[str, ...] | None,
) -> FlowDraftSpecCore:
    """Compile one selected DOCX's exact runtime contract before approval."""

    template_step_indexes = [
        index
        for index, step in enumerate(spec.steps)
        if step.output_mode is OutputMode.TEMPLATE_FILL
    ]
    if not template_step_indexes:
        return spec
    if template_step_indexes != [len(spec.steps) - 1]:
        raise _architecture_error(
            failure_code="template_fill_position_invalid",
            detail="A DOCX template-fill step must be the final Flow step.",
        )
    if selected_template_count != 1:
        raise _architecture_error(
            failure_code="template_attachment_selection_invalid",
            detail=(
                "A template-fill Flow requires exactly one selected DOCX template. "
                "Select one template attachment and try again."
            ),
            selected_template_count=selected_template_count,
        )
    if placeholders is None:
        raise _architecture_error(
            failure_code="template_attachment_unreadable",
            detail=(
                "The selected DOCX template could not be inspected safely. "
                "Attach a valid DOCX file and try again."
            ),
        )

    normalized_placeholders = _normalized_unique_placeholders(placeholders)
    spec = _require_transcription_input_when_referenced(
        spec,
        placeholders=normalized_placeholders,
    )
    form_fields = list(spec.form_fields or ())
    terminal_step = spec.steps[-1]
    bindings: dict[str, str] = {}
    unresolved: list[str] = []
    for placeholder in normalized_placeholders:
        field_name = template_placeholder_form_field_name(placeholder)
        if field_name is not None:
            canonical_name = _require_template_form_field(
                form_fields,
                requested_name=field_name,
            )
            bindings[placeholder] = form_field_reference_expression(canonical_name)
            continue

        explicit_binding = _explicit_runtime_binding(
            placeholder=placeholder,
            spec=spec,
        )
        if explicit_binding is None:
            unresolved.append(placeholder)
            continue
        bindings[placeholder] = explicit_binding

    if unresolved:
        raise _architecture_error(
            failure_code="template_placeholder_unresolved",
            detail=(
                "The selected DOCX contains placeholders that cannot be resolved "
                "safely by this Flow. Use Flow input fields, {{ datum }}, or a "
                "declared output from an earlier step."
            ),
            unresolved_count=len(unresolved),
            unresolved_placeholders=", ".join(
                name[:_MAX_DIAGNOSTIC_PLACEHOLDER_LENGTH] for name in unresolved[:8]
            ),
        )

    existing_output_config = terminal_step.output_config or {}
    portable_output_config = {
        key: value
        for key, value in existing_output_config.items()
        if key not in _LOCAL_TEMPLATE_CONFIG_KEYS and key != "bindings"
    }
    portable_output_config["bindings"] = bindings
    steps = [
        *spec.steps[:-1],
        terminal_step.model_copy(update={"output_config": portable_output_config}),
    ]
    return spec.model_copy(update={"steps": steps, "form_fields": form_fields})


def _normalized_unique_placeholders(placeholders: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_placeholder in placeholders:
        placeholder = raw_placeholder.strip()
        if not placeholder or placeholder in seen:
            continue
        normalized.append(placeholder)
        seen.add(placeholder)
    return tuple(normalized)


def _require_transcription_input_when_referenced(
    spec: FlowDraftSpecCore,
    *,
    placeholders: tuple[str, ...],
) -> FlowDraftSpecCore:
    if not _TRANSCRIPTION_PLACEHOLDERS.intersection(placeholders):
        return spec

    root_step = spec.steps[0]
    if not (
        root_step.input_source is InputSource.FLOW_INPUT
        and root_step.input_type is InputType.AUDIO
    ):
        return spec

    input_config = resolve_runtime_input_config(step_spec=root_step)
    if input_config is None:
        return spec
    runtime_input = clone_json_object(input_config.get("runtime_input"))
    if runtime_input is None:
        return spec

    runtime_input["required"] = True
    updated_input_config = dict(input_config)
    updated_input_config["runtime_input"] = runtime_input
    updated_root_step = root_step.model_copy(
        update={"input_config": updated_input_config}
    )
    return spec.model_copy(update={"steps": [updated_root_step, *spec.steps[1:]]})


def _require_template_form_field(
    fields: list[FormFieldSpec],
    *,
    requested_name: str,
) -> str:
    requested_key = requested_name.casefold()
    for index, field in enumerate(fields):
        if field.name.casefold() != requested_key:
            continue
        if not field.required:
            fields[index] = field.model_copy(update={"required": True})
        return field.name

    fields.append(
        FormFieldSpec(
            name=requested_name,
            type="text",
            label=requested_name,
            required=True,
        )
    )
    return requested_name


def _explicit_runtime_binding(
    *,
    placeholder: str,
    spec: FlowDraftSpecCore,
) -> str | None:
    if placeholder == "datum":
        return "{{ datum }}"

    runtime_alias_binding = _provable_runtime_alias_binding(
        placeholder=placeholder,
        spec=spec,
    )
    if runtime_alias_binding is not None:
        return runtime_alias_binding

    if "." not in placeholder:
        return None
    raw_head, tail = placeholder.split(".", maxsplit=1)
    referenced_step = _referenced_step(spec, raw_head.strip())
    if referenced_step is None:
        return None
    referenced_index, referenced = referenced_step
    terminal_index = len(spec.steps) - 1
    if referenced_index >= terminal_index:
        return None

    if tail == "output.text":
        if referenced.output_type is not OutputType.TEXT:
            return None
    elif tail == "output.structured":
        if referenced.output_contract is None:
            return None
    elif tail.startswith("output.structured."):
        contract = referenced.output_contract
        if not isinstance(contract, Mapping):
            return None
        path = tail.removeprefix("output.structured.")
        if not path or missing_structured_output_path(dict(contract), path) is not None:
            return None
    else:
        return None

    return "{{ " + referenced.plan_step_ref + "." + tail + " }}"


def _provable_runtime_alias_binding(
    *,
    placeholder: str,
    spec: FlowDraftSpecCore,
) -> str | None:
    root_step = spec.steps[0]
    root_runtime_input = build_runtime_input_config(root_step.input_config)
    if (
        root_step.input_source is InputSource.FLOW_INPUT
        and root_step.input_type is InputType.AUDIO
        and root_runtime_input.enabled
        and root_runtime_input.required
        and root_runtime_input.input_format == InputType.AUDIO.value
        and placeholder in _TRANSCRIPTION_PLACEHOLDERS
    ):
        return "{{ " + placeholder + " }}"

    if (
        placeholder == PREVIOUS_STEP_TEXT_ALIAS
        and len(spec.steps) > 1
        and spec.steps[-2].output_type is OutputType.TEXT
    ):
        return "{{ " + placeholder + " }}"
    return None


def _referenced_step(
    spec: FlowDraftSpecCore,
    head: str,
) -> tuple[int, StepSpec] | None:
    for index, step in enumerate(spec.steps):
        if step.plan_step_ref == head:
            return index, step
    if head.startswith("step_"):
        raw_order = head.removeprefix("step_")
        if raw_order.isdigit():
            index = int(raw_order) - 1
            if 0 <= index < len(spec.steps):
                return index, spec.steps[index]
    return None


def _architecture_error(
    *,
    failure_code: str,
    detail: str,
    **context: ArchitectureLogValue,
) -> AIBuilderArchitectureError:
    return AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=detail,
        log_context={
            "failure_code": failure_code,
            "reason": failure_code,
            **context,
        },
    )


__all__ = ["apply_template_attachment_contract"]
