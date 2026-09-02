from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import TypeGuard, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
    ArchitectureLogValue,
    ArchitectureRepairDisposition,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    MAX_COMPILED_STRUCTURED_FIELD_DEPTH,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    fold_result_field_name,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    NAMED_RESULT_FIELD_NAME_MAX_LENGTH,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject, clone_json_object
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
    is_reserved_runtime_variable,
    is_step_alias_variable,
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
MAX_TEMPLATE_PREPARATION_STAGES = 5
MAX_TEMPLATE_MATERIALIZED_PATHS = NAMED_RESULT_EVIDENCE_MAX_ITEMS
_TRANSCRIPTION_PLACEHOLDERS = frozenset(
    {
        FLOW_INPUT_TRANSCRIPTION_KEY,
        f"flow_input.{FLOW_INPUT_TRANSCRIPTION_KEY}",
        f"flow.input.{FLOW_INPUT_TRANSCRIPTION_KEY}",
    }
)


def template_preparation_stage_limit_exceeded(spec: FlowDraftSpecCore) -> bool:
    if (
        len(spec.steps) < 2
        or spec.steps[-1].output_mode is not OutputMode.TEMPLATE_FILL
    ):
        return False
    root_step = spec.steps[0]
    has_fixed_reader = (
        root_step.input_source is InputSource.FLOW_INPUT
        and root_step.input_type in {InputType.DOCUMENT, InputType.FILE}
        and root_step.output_type is OutputType.JSON
        and root_step.output_mode is OutputMode.PASS_THROUGH
    )
    preparation_steps = spec.steps[1:-1] if has_fixed_reader else spec.steps[:-1]
    return len(preparation_steps) > MAX_TEMPLATE_PREPARATION_STAGES


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
            repair_disposition="model_correctable",
            detail="A DOCX template-fill step must be the final Flow step.",
        )
    if not template_attachment_selection_is_valid(selected_template_count):
        raise _architecture_error(
            failure_code="template_attachment_selection_invalid",
            repair_disposition="user_action",
            detail=(
                "A template-fill Flow requires exactly one selected DOCX template. "
                "Select one template attachment and try again."
            ),
            selected_template_count=selected_template_count,
        )
    if not selected_template_is_readable(placeholders):
        raise _architecture_error(
            failure_code="template_attachment_unreadable",
            repair_disposition="user_action",
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
    spec = _materialize_nested_template_outputs(
        spec,
        placeholders=normalized_placeholders,
    )
    form_fields = list(spec.form_fields or ())
    terminal_step = spec.steps[-1]
    bindings: dict[str, str] = {}
    unresolved: list[str] = []
    for placeholder in normalized_placeholders:
        field_name = template_placeholder_form_field_name(placeholder)
        if field_name is not None and _declared_form_field_name(
            form_fields,
            requested_name=field_name,
        ):
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
        if explicit_binding is not None:
            bindings[placeholder] = explicit_binding
            continue

        prepared_binding = _folded_step_output_binding(
            placeholder=placeholder,
            spec=spec,
        )
        if prepared_binding is not None:
            bindings[placeholder] = prepared_binding
            continue

        if field_name is not None:
            canonical_name = _require_template_form_field(
                form_fields,
                requested_name=field_name,
            )
            bindings[placeholder] = form_field_reference_expression(canonical_name)
            continue

        unresolved.append(placeholder)

    if unresolved:
        raise _architecture_error(
            failure_code="template_placeholder_unresolved",
            repair_disposition="user_action",
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
    preparation_steps = _drop_unused_template_predecessor(
        steps=spec.steps[:-1],
        bindings=bindings,
    )
    dropped_predecessor = len(preparation_steps) != len(spec.steps) - 1
    terminal_update: dict[str, object] = {"output_config": portable_output_config}
    if dropped_predecessor:
        dropped_step = spec.steps[-2]
        terminal_update["input_bindings"] = _without_step_source_refs(
            terminal_step.input_bindings,
            step_refs={dropped_step.plan_step_ref, f"step_{len(spec.steps) - 1}"},
        )
    steps = [
        *preparation_steps,
        terminal_step.model_copy(update=terminal_update),
    ]
    return spec.model_copy(update={"steps": steps, "form_fields": form_fields})


def template_attachment_selection_is_valid(selected_template_count: int) -> bool:
    return selected_template_count == 1


def selected_template_is_readable(
    placeholders: Sequence[str] | None,
) -> TypeGuard[Sequence[str]]:
    return placeholders is not None


def _normalized_unique_placeholders(placeholders: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_placeholder in placeholders:
        placeholder = raw_placeholder.strip()
        if not placeholder or placeholder in seen:
            continue
        if "." in placeholder:
            segments = tuple(segment.strip() for segment in placeholder.split("."))
            if (
                any(not segment for segment in segments)
                or ".".join(segments) != placeholder
            ):
                raise _architecture_error(
                    failure_code="template_placeholder_path_invalid",
                    repair_disposition="user_action",
                    detail=(
                        "The selected DOCX contains a placeholder with an invalid "
                        "variable path. Remove whitespace around dots and empty path "
                        "segments."
                    ),
                )
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


def _declared_form_field_name(
    fields: list[FormFieldSpec],
    *,
    requested_name: str,
) -> bool:
    requested_key = requested_name.casefold()
    return any(field.name.casefold() == requested_key for field in fields)


def _folded_step_output_binding(
    *,
    placeholder: str,
    spec: FlowDraftSpecCore,
) -> str | None:
    """Bind a human-named placeholder to a prepared structured field.

    Template authors name placeholders in natural Swedish ("Ärendet",
    "förslag till beslut", "sections.ärendet.text") without knowing the
    Flow's step topology. When a preceding step declares a string output
    field whose folded name matches the folded placeholder, that prepared
    value is the content the author asked for; the latest such step wins
    because later preparation refines earlier output. Only fields declared
    in a step's output contract are eligible, so the binding stays provable.
    """

    folded_placeholder = fold_result_field_name(placeholder)
    if not folded_placeholder:
        return None

    for step in reversed(spec.steps[:-1]):
        contract = step.output_contract
        if not isinstance(contract, Mapping) or not step.plan_step_ref:
            continue
        string_paths = _declared_string_output_paths(contract)
        if placeholder in string_paths:
            matched_path = placeholder
        else:
            folded_matches = [
                path
                for path in string_paths
                if fold_result_field_name(path) == folded_placeholder
            ]
            if len(folded_matches) > 1:
                return None
            if not folded_matches:
                continue
            matched_path = folded_matches[0]
        return "{{ " + step.plan_step_ref + ".output.structured." + matched_path + " }}"
    return None


def _declared_string_output_paths(
    schema: Mapping[str, object],
    *,
    prefix: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return provable string leaf paths without implicit array traversal."""

    if schema.get("type") == "array":
        return ()
    if _schema_accepts_string(schema):
        return (".".join(prefix),) if prefix else ()

    properties = cast(object, schema.get("properties"))
    if not isinstance(properties, Mapping):
        return ()
    raw_required = schema.get("required")
    required: set[str] = (
        {item for item in cast(Sequence[object], raw_required) if isinstance(item, str)}
        if isinstance(raw_required, list)
        else set()
    )

    paths: list[str] = []
    for raw_name, raw_schema in cast(Mapping[object, object], properties).items():
        if (
            not isinstance(raw_name, str)
            or raw_name not in required
            or not isinstance(raw_schema, Mapping)
        ):
            continue
        paths.extend(
            _declared_string_output_paths(
                cast(Mapping[str, object], raw_schema),
                prefix=(*prefix, raw_name),
            )
        )
    return tuple(paths)


def _schema_accepts_string(schema: Mapping[str, object]) -> bool:
    raw_type = schema.get("type")
    if raw_type == "string":
        return True
    if not isinstance(raw_type, list):
        return False
    declared_types = {
        item for item in cast(list[object], raw_type) if isinstance(item, str)
    }
    return declared_types == {"string", "null"}


def _materialize_nested_template_outputs(
    spec: FlowDraftSpecCore,
    *,
    placeholders: tuple[str, ...],
) -> FlowDraftSpecCore:
    """Make server-known nested DOCX fields part of one JSON preparation step.

    Dotted template placeholders cannot be runtime form fields. When no prior
    step already declares one, the template itself is authoritative evidence
    that the Flow must prepare that string path. Adding it here keeps the
    provider from having to reproduce a contract Eneo has already inspected.
    Explicit Flow variable expressions remain validation-only and are never
    reinterpreted as output field names.
    """

    candidate_index = next(
        (
            index
            for index in range(len(spec.steps) - 2, -1, -1)
            if spec.steps[index].output_type is OutputType.JSON
            and isinstance(spec.steps[index].output_contract, Mapping)
        ),
        None,
    )
    if candidate_index is None:
        return spec

    candidate = spec.steps[candidate_index]
    contract = deepcopy(cast(dict[str, object], candidate.output_contract))
    added_paths: list[str] = []
    for placeholder in placeholders:
        if "." not in placeholder:
            continue
        namespace = placeholder.split(".", 1)[0].casefold()
        if (
            is_reserved_runtime_variable(namespace)
            or is_step_alias_variable(namespace)
            or namespace.startswith("step_")
        ):
            continue
        if _explicit_runtime_binding(placeholder=placeholder, spec=spec) is not None:
            continue
        if _folded_step_output_binding(placeholder=placeholder, spec=spec) is not None:
            continue
        path = tuple(placeholder.split("."))
        if len(path) > MAX_COMPILED_STRUCTURED_FIELD_DEPTH:
            raise _architecture_error(
                failure_code="template_placeholder_depth_exceeded",
                repair_disposition="user_action",
                detail=(
                    "The selected DOCX contains a nested placeholder deeper than "
                    "the compiled Flow schema supports."
                ),
                max_depth=MAX_COMPILED_STRUCTURED_FIELD_DEPTH,
            )
        if len(placeholder) > NAMED_RESULT_FIELD_NAME_MAX_LENGTH:
            raise _architecture_error(
                failure_code="template_placeholder_materialization_limit_exceeded",
                repair_disposition="user_action",
                detail=(
                    "The selected DOCX contains a placeholder path too large to "
                    "materialize safely."
                ),
                max_path_length=NAMED_RESULT_FIELD_NAME_MAX_LENGTH,
            )
        expanded_contract = deepcopy(contract)
        if _add_required_string_path(
            expanded_contract,
            path=path,
            placeholder=placeholder,
        ):
            if len(added_paths) >= MAX_TEMPLATE_MATERIALIZED_PATHS:
                raise _architecture_error(
                    failure_code=(
                        "template_placeholder_materialization_limit_exceeded"
                    ),
                    repair_disposition="user_action",
                    detail=(
                        "The selected DOCX requires more server-materialized "
                        "fields than one Flow step can safely prepare."
                    ),
                    max_paths=MAX_TEMPLATE_MATERIALIZED_PATHS,
                )
            contract = expanded_contract
            added_paths.append(placeholder)

    if not added_paths:
        return spec

    instructions = candidate.assistant_spec.instructions.rstrip()
    required_fields = "\n".join(
        f"- {path}: Value for DOCX template placeholder '{path}'."
        for path in added_paths
    )
    assistant_spec = candidate.assistant_spec.model_copy(
        update={
            "instructions": (
                f"{instructions}\n\nRequired DOCX template fields:\n{required_fields}"
            )
        }
    )
    updated_candidate = candidate.model_copy(
        update={
            "assistant_spec": assistant_spec,
            "output_contract": contract,
        }
    )
    steps = list(spec.steps)
    steps[candidate_index] = updated_candidate
    return spec.model_copy(update={"steps": steps})


def _add_required_string_path(
    schema: dict[str, object],
    *,
    path: tuple[str, ...],
    placeholder: str,
) -> bool:
    if not path or any(not part for part in path):
        return False

    node: dict[str, object] = schema
    for index, part in enumerate(path):
        raw_properties = node.get("properties")
        if not isinstance(raw_properties, dict):
            return False
        properties = cast(dict[str, object], raw_properties)
        raw_required = node.setdefault("required", [])
        if not isinstance(raw_required, list):
            return False
        required = cast(list[object], raw_required)
        if part not in required:
            required.append(part)

        existing = properties.get(part)
        is_leaf = index == len(path) - 1
        if is_leaf:
            if existing is None:
                properties[part] = {
                    "type": "string",
                    "description": (
                        f"Value for DOCX template placeholder '{placeholder}'."
                    ),
                }
                return True
            return isinstance(existing, Mapping) and _schema_accepts_string(
                cast(Mapping[str, object], existing)
            )

        if existing is None:
            created: dict[str, object] = {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
            properties[part] = created
            existing = created
        if not isinstance(existing, dict):
            return False
        child = cast(dict[str, object], existing)
        if child.get("type") != "object":
            return False
        node = child
    return False


def _drop_unused_template_predecessor(
    *,
    steps: Sequence[StepSpec],
    bindings: Mapping[str, str],
) -> Sequence[StepSpec]:
    """Remove a model-authored step that cannot affect template output."""

    if len(steps) < 2:
        return steps
    candidate = steps[-1]
    if (
        candidate.output_mode is not OutputMode.PASS_THROUGH
        or candidate.output_type not in {OutputType.JSON, OutputType.TEXT}
        or (
            candidate.output_type is OutputType.TEXT
            and candidate.review_policy is not None
        )
    ):
        return steps

    candidate_order = len(steps)
    candidate_reference_prefixes = (
        "{{ " + candidate.plan_step_ref + ".output.",
        "{{ step_" + str(candidate_order) + ".output.",
    )
    if any(
        expression.startswith(candidate_reference_prefixes)
        for expression in bindings.values()
    ):
        return steps
    if (
        candidate.output_type is OutputType.TEXT
        and "{{ " + PREVIOUS_STEP_TEXT_ALIAS + " }}" in bindings.values()
    ):
        return steps
    return steps[:-1]


def _without_step_source_refs(
    input_bindings: FlowPersistedJsonObject | None,
    *,
    step_refs: set[str],
) -> FlowPersistedJsonObject | None:
    if input_bindings is None:
        return None
    raw_source_refs = input_bindings.get("source_refs")
    if not isinstance(raw_source_refs, list):
        return input_bindings

    retained_source_refs: list[object] = []
    for source_ref in cast(list[object], raw_source_refs):
        if (
            isinstance(source_ref, Mapping)
            and cast(Mapping[object, object], source_ref).get("step_ref") in step_refs
        ):
            continue
        retained_source_refs.append(cast(object, source_ref))
    updated = dict(input_bindings)
    if retained_source_refs:
        updated["source_refs"] = retained_source_refs
    else:
        updated.pop("source_refs", None)
    return updated or None


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
    repair_disposition: ArchitectureRepairDisposition,
    detail: str,
    **context: ArchitectureLogValue,
) -> AIBuilderArchitectureError:
    return AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        repair_disposition=repair_disposition,
        detail=detail,
        log_context={
            "failure_code": failure_code,
            "reason": failure_code,
            **context,
        },
    )


__all__ = [
    "MAX_TEMPLATE_MATERIALIZED_PATHS",
    "MAX_TEMPLATE_PREPARATION_STAGES",
    "apply_template_attachment_contract",
    "selected_template_is_readable",
    "template_attachment_selection_is_valid",
    "template_preparation_stage_limit_exceeded",
]
