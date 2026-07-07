from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)
from eneo.json_types import JsonObject

logger = logging.getLogger(__name__)

_SOURCE_CAPTURE_INPUT_TYPES = frozenset(
    {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
)
_SOURCE_CONTRACT_INPUT_TYPES = frozenset(
    {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
)
_SOURCE_CONTRACT_FORM_FIELD_PREFIX_TOKENS = frozenset(
    {
        "manual",
        "manuell",
        "manuella",
        "provided",
        "runtime",
        "user",
    }
)
_SOURCE_CONTRACT_TOKEN_ALIASES = {
    "år": "date",
    "ar": "date",
    "year": "date",
}


def complete_source_reader_contracts(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
    required_fields: tuple[SourceCaptureField, ...],
) -> list[NewStepDraft]:
    source_reader_indexes = tuple(
        index for index, step in enumerate(steps) if _is_source_json_contract_step(step)
    )
    if not source_reader_indexes:
        return steps

    fields_by_index: dict[int, list[SourceCaptureField]] = {}
    terminal_fields = (
        _capture_fields_from_terminal_schema(terminal_output_schema)
        if terminal_output_schema is not None
        else ()
    )
    global_fields = _dedupe_capture_fields([*required_fields, *terminal_fields])
    missing_global_fields = [
        field
        for field in global_fields
        if not any(
            _structured_fields_have_leaf(steps[index].output_fields or [], field.name)
            for index in source_reader_indexes
        )
    ]
    if missing_global_fields:
        if len(source_reader_indexes) != 1:
            raise AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                detail=(
                    "Source-reader contract completion found required fields "
                    "but could not attribute them to exactly one reader."
                ),
                log_context={
                    "source_reader_count": len(source_reader_indexes),
                    "required_fields": ",".join(
                        field.name for field in missing_global_fields
                    ),
                },
            )
        fields_by_index.setdefault(source_reader_indexes[0], []).extend(
            missing_global_fields
        )

    for step in steps:
        for ref in step.uses_previous_fields:
            source_index = ref.from_step - 1
            if source_index < 0 or source_index >= len(steps):
                continue
            source_step = steps[source_index]
            if not _is_source_json_contract_step(source_step):
                continue
            field_name = _leaf_field_name(ref.field_path)
            if not field_name or _structured_fields_have_leaf(
                source_step.output_fields or [], field_name
            ):
                continue
            fields_by_index.setdefault(source_index, []).append(
                SourceCaptureField(name=field_name, description=ref.label)
            )

    if not fields_by_index:
        return steps

    updated_steps = list(steps)
    for index, fields in fields_by_index.items():
        step = steps[index]
        output_fields = step.output_fields or []
        completed_fields = _add_missing_source_reader_fields(
            output_fields,
            required_fields=_dedupe_capture_fields(fields),
        )
        if completed_fields == output_fields:
            continue
        updated_steps[index] = step.model_copy(
            update={"output_fields": completed_fields}
        )
        logger.info(
            "ai_builder_source_reader_contract_completed",
            extra={
                "step_index": index + 1,
                "field_names": [field.name for field in fields],
            },
        )

    return updated_steps


def drop_source_contract_shadow_form_fields(
    *,
    steps: list[NewStepDraft],
    form_fields: list[FormFieldSpec],
) -> tuple[list[NewStepDraft], list[FormFieldSpec], list[str]]:
    dropped_names = set(
        source_contract_shadow_form_field_names(
            output_fields_by_step=tuple(
                tuple(step.output_fields or ())
                for step in steps
                if _is_source_json_contract_step(step)
            ),
            form_fields=tuple(form_fields),
        )
    )
    if not dropped_names:
        return steps, form_fields, []
    return (
        [_without_form_field_refs(step, dropped_names=dropped_names) for step in steps],
        [field for field in form_fields if field.name not in dropped_names],
        sorted(dropped_names),
    )


def log_dropped_source_contract_shadow_fields(
    *,
    field_names: list[str],
) -> None:
    if not field_names:
        return
    logger.info(
        "ai_builder_source_contract_shadow_input_fields_dropped",
        extra={"field_names": field_names},
    )


def source_capture_fields_by_step_index(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
) -> dict[int, tuple[SourceCaptureField, ...]]:
    fields_by_index: dict[int, tuple[SourceCaptureField, ...]] = {}
    for index, step in enumerate(steps):
        if not _is_source_capture_step(step):
            continue
        fields = _nearest_downstream_capture_fields(
            steps=steps,
            source_index=index,
            terminal_output_schema=terminal_output_schema,
        )
        if fields:
            fields_by_index[index] = fields
    return fields_by_index


def clear_terminal_schema_output_fields(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
) -> list[NewStepDraft]:
    if (
        terminal_output_schema is None
        or not steps
        or steps[-1].output_type != OutputType.JSON
        or steps[-1].output_fields is None
    ):
        return steps
    return [*steps[:-1], steps[-1].model_copy(update={"output_fields": None})]


def apply_terminal_output_schema(
    compiled_steps: list[StepSpec],
    *,
    terminal_output_schema: JsonObject | None,
) -> list[StepSpec]:
    if (
        terminal_output_schema is None
        or not compiled_steps
        or compiled_steps[-1].output_type != OutputType.JSON
    ):
        return compiled_steps
    terminal_step = compiled_steps[-1].model_copy(
        update={
            "output_contract": cast(
                FlowPersistedJsonObject,
                deepcopy(terminal_output_schema),
            )
        }
    )
    return [*compiled_steps[:-1], terminal_step]


def complete_structured_source_reader_fields(
    fields: tuple[StructuredFieldDraft, ...],
    *,
    required_fields: tuple[SourceCaptureField, ...],
) -> tuple[StructuredFieldDraft, ...]:
    return tuple(
        _add_missing_source_reader_fields(
            list(fields),
            required_fields=_dedupe_capture_fields(list(required_fields)),
        )
    )


def source_contract_shadow_form_field_names(
    *,
    output_fields_by_step: tuple[tuple[StructuredFieldDraft, ...], ...],
    form_fields: tuple[FormFieldSpec, ...],
) -> tuple[str, ...]:
    if not form_fields:
        return ()
    source_contract_token_sets: set[frozenset[str]] = set()
    for output_fields in output_fields_by_step:
        source_contract_token_sets.update(
            _structured_field_token_sets(list(output_fields))
        )
    if not source_contract_token_sets:
        return ()
    frozen_source_contract_token_sets = frozenset(source_contract_token_sets)
    return tuple(
        sorted(
            field.name
            for field in form_fields
            if _form_field_shadows_source_contract(
                field,
                source_contract_token_sets=frozen_source_contract_token_sets,
            )
        )
    )


def source_capture_fields_from_terminal_schema(
    terminal_output_schema: JsonObject,
) -> tuple[SourceCaptureField, ...]:
    return _capture_fields_from_terminal_schema(terminal_output_schema)


def structured_fields_have_source_leaf(
    fields: tuple[StructuredFieldDraft, ...],
    required_name: str,
) -> bool:
    return _structured_fields_have_leaf(list(fields), required_name)


def source_reader_leaf_field_name(field_path: str) -> str:
    return _leaf_field_name(field_path)


def _add_missing_source_reader_fields(
    fields: list[StructuredFieldDraft],
    *,
    required_fields: tuple[SourceCaptureField, ...],
) -> list[StructuredFieldDraft]:
    missing_fields = [
        field
        for field in required_fields
        if not _structured_fields_have_leaf(fields, field.name)
    ]
    if not missing_fields:
        return fields

    if len(fields) == 1:
        field = fields[0]
        if field.field_type == "array" and field.item_fields:
            return [
                field.model_copy(
                    update={
                        "item_fields": _append_structured_leaf_fields(
                            field.item_fields,
                            missing_fields=missing_fields,
                        )
                    }
                )
            ]
        if field.field_type == "object" and field.fields:
            return [
                field.model_copy(
                    update={
                        "fields": _append_structured_leaf_fields(
                            field.fields,
                            missing_fields=missing_fields,
                        )
                    }
                )
            ]

    return _append_structured_leaf_fields(fields, missing_fields=missing_fields)


def _append_structured_leaf_fields(
    fields: list[StructuredFieldDraft],
    *,
    missing_fields: list[SourceCaptureField],
) -> list[StructuredFieldDraft]:
    return [
        *fields,
        *(
            StructuredFieldDraft(
                name=field.name,
                field_type="string",
                description=field.description
                or f"Source-derived value for {field.name}.",
            )
            for field in missing_fields
        ),
    ]


def _structured_fields_have_leaf(
    fields: list[StructuredFieldDraft],
    required_name: str,
) -> bool:
    return any(
        _field_name_matches_required_leaf(field.name, required_name)
        for field in _iter_output_capture_fields(fields)
    )


def _field_name_matches_required_leaf(field_name: str, required_name: str) -> bool:
    field_key = _field_name_match_key(field_name)
    required_key = _field_name_match_key(required_name)
    if field_key == required_key:
        return True
    if not field_key.endswith(f"_{required_key}"):
        return False
    logger.info(
        "ai_builder_source_reader_contract_fuzzy_leaf_match",
        extra={"field_name": field_name, "required_name": required_name},
    )
    return True


def _field_name_match_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _leaf_field_name(field_path: str) -> str:
    return next(
        (
            segment.strip()
            for segment in reversed(field_path.split("."))
            if segment.strip() and not segment.strip().isdigit()
        ),
        "",
    )


def _is_source_json_contract_step(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _SOURCE_CONTRACT_INPUT_TYPES
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
    )


def _structured_field_token_sets(
    fields: list[StructuredFieldDraft] | None,
) -> set[frozenset[str]]:
    token_sets: set[frozenset[str]] = set()
    for field in fields or []:
        tokens = _source_contract_name_tokens(field.name)
        if tokens:
            token_sets.add(frozenset(tokens))
        token_sets.update(_structured_field_token_sets(field.fields))
        token_sets.update(_structured_field_token_sets(field.item_fields))
    return token_sets


def _form_field_shadows_source_contract(
    field: FormFieldSpec,
    *,
    source_contract_token_sets: frozenset[frozenset[str]],
) -> bool:
    candidates = (
        _source_contract_name_tokens(field.name),
        _source_contract_name_tokens(field.label),
    )
    return any(
        candidate
        and any(
            candidate.issubset(source_tokens)
            for source_tokens in source_contract_token_sets
        )
        for candidate in candidates
    )


def _source_contract_name_tokens(value: str) -> frozenset[str]:
    normalized = normalize_discovery_text(value.replace("_", " ").replace("-", " "))
    tokens = tuple(
        _SOURCE_CONTRACT_TOKEN_ALIASES.get(token, token) for token in normalized.split()
    )
    while tokens and tokens[0] in _SOURCE_CONTRACT_FORM_FIELD_PREFIX_TOKENS:
        tokens = tokens[1:]
    return frozenset(tokens)


def _without_form_field_refs(
    step: NewStepDraft,
    *,
    dropped_names: set[str],
) -> NewStepDraft:
    if not step.uses_form_fields:
        return step
    uses_form_fields = [
        field_name
        for field_name in step.uses_form_fields
        if field_name not in dropped_names
    ]
    if uses_form_fields == step.uses_form_fields:
        return step
    return step.model_copy(update={"uses_form_fields": uses_form_fields})


def _is_source_capture_step(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _SOURCE_CAPTURE_INPUT_TYPES
        and step.output_type == OutputType.TEXT
    )


def _nearest_downstream_capture_fields(
    *,
    steps: list[NewStepDraft],
    source_index: int,
    terminal_output_schema: JsonObject | None,
) -> tuple[SourceCaptureField, ...]:
    for downstream_index in range(source_index + 1, len(steps)):
        step = steps[downstream_index]
        if step.output_type != OutputType.JSON:
            continue
        fields = _capture_fields_from_output_fields(step.output_fields)
        if (
            not fields
            and terminal_output_schema is not None
            and downstream_index == len(steps) - 1
        ):
            fields = _capture_fields_from_terminal_schema(terminal_output_schema)
        if fields:
            return fields
    return ()


def _capture_fields_from_output_fields(
    output_fields: list[StructuredFieldDraft] | None,
) -> tuple[SourceCaptureField, ...]:
    if not output_fields:
        return ()
    return _dedupe_capture_fields(_iter_output_capture_fields(output_fields))


def _iter_output_capture_fields(
    output_fields: list[StructuredFieldDraft],
) -> list[SourceCaptureField]:
    fields: list[SourceCaptureField] = []
    for field in output_fields:
        object_fields = field.fields if field.field_type == "object" else None
        item_fields = field.item_fields if field.field_type == "array" else None
        if object_fields:
            fields.extend(_iter_output_capture_fields(object_fields))
        elif item_fields:
            fields.extend(_iter_output_capture_fields(item_fields))
        elif field.name:
            fields.append(
                SourceCaptureField(name=field.name, description=field.description)
            )
    return fields


def _capture_fields_from_terminal_schema(
    terminal_output_schema: JsonObject,
) -> tuple[SourceCaptureField, ...]:
    names = schema_leaf_property_names(cast(dict[str, Any], terminal_output_schema))
    return _dedupe_capture_fields(
        [SourceCaptureField(name=name, description=None) for name in names]
    )


def _dedupe_capture_fields(
    fields: list[SourceCaptureField],
) -> tuple[SourceCaptureField, ...]:
    deduped: list[SourceCaptureField] = []
    seen: set[str] = set()
    for field in fields:
        name = field.name.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(SourceCaptureField(name=name, description=field.description))
    return tuple(deduped)
