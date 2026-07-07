from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
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
_SOURCE_CONTRACT_FORM_FIELD_CONTEXT_TOKENS = frozenset(
    {
        "document",
        "dokument",
        "hint",
        "report",
        "rapport",
    }
)
_SOURCE_CONTRACT_TOKEN_ALIASES = {
    "år": "date",
    "ar": "date",
    "year": "date",
}
_SOURCE_CAPTURE_FIELD_TOKEN_ALIASES = {
    "ar": "date",
    "author": "author",
    "avsandare": "sender",
    "category": "category",
    "checklista": "checklist",
    "confidential": "confidentiality",
    "confidentiality": "confidentiality",
    "date": "date",
    "datum": "date",
    "documenttype": "document_type",
    "dokumenttyp": "document_type",
    "forfattare": "author",
    "fraga": "question",
    "fragor": "question",
    "kategori": "category",
    "krav": "requirement",
    "regel": "rule",
    "regler": "rule",
    "requirement": "requirement",
    "requirements": "requirement",
    "rule": "rule",
    "rules": "rule",
    "sammanfattning": "summary",
    "secret": "confidentiality",
    "secrecy": "confidentiality",
    "sekretess": "confidentiality",
    "sekretesskansliga": "confidentiality",
    "sekretesskänsliga": "confidentiality",
    "sender": "sender",
    "sensitive": "confidentiality",
    "slutsats": "conclusion",
    "slutsatser": "conclusion",
    "titel": "title",
    "year": "date",
    "år": "date",
}
_DATE_TOKENS = frozenset({"date"})
_AUTHOR_OR_SENDER_TOKENS = frozenset({"author", "sender"})
_SUMMARY_TOKENS = frozenset({"summary"})
_SUMMARY_MODIFIER_TOKENS = frozenset(
    {"brief", "concise", "kort", "short", "source", "topic"}
)
_REQUIREMENT_TOKENS = frozenset({"requirement"})
_REQUIREMENT_MODIFIER_TOKENS = frozenset({"key", "main", "rule"})
_CONFIDENTIALITY_TOKENS = frozenset({"confidentiality"})
_CONFIDENTIALITY_MODIFIER_TOKENS = frozenset(
    {"note", "part", "parts", "section", "sections"}
)
_TITLE_TOKEN_SETS = frozenset(
    {
        frozenset({"title"}),
        frozenset({"document", "title"}),
    }
)
_DOCUMENT_TYPE_TOKEN_SETS = frozenset(
    {
        frozenset({"document_type"}),
        frozenset({"document", "type"}),
    }
)
_CATEGORY_TOKENS = frozenset({"category"})
_CONCLUSION_TOKENS = frozenset({"conclusion"})
_CONCLUSION_MODIFIER_TOKENS = frozenset(
    {"central", "implication", "key", "main", "summary"}
)
_SOURCE_IDENTITY_TOKENS = frozenset(
    {
        frozenset({"file", "name"}),
        frozenset({"filename"}),
        frozenset({"source"}),
        frozenset({"source", "file", "name"}),
        frozenset({"source", "label"}),
    }
)
_SOURCE_DOCUMENT_CONTAINER_KEYS = frozenset(
    {
        "document",
        "documents",
        "dokument",
        "dokumenten",
        "dokumentet",
        "kalldokument",
        "källdokument",
        "source_document",
        "source_documents",
    }
)


@dataclass(frozen=True, slots=True)
class SourceCaptureField:
    name: str
    description: str | None = None


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


def structured_fields_have_document_items(
    fields: tuple[StructuredFieldDraft, ...],
) -> bool:
    return any(_structured_field_is_documents_array(field) for field in fields)


def source_reader_leaf_field_name(field_path: str) -> str:
    return _leaf_field_name(field_path)


def _add_missing_source_reader_fields(
    fields: list[StructuredFieldDraft],
    *,
    required_fields: tuple[SourceCaptureField, ...],
) -> list[StructuredFieldDraft]:
    fields = _normalize_source_reader_fields(fields)
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
            return _normalize_source_reader_fields(
                [
                    field.model_copy(
                        update={
                            "item_fields": _append_structured_leaf_fields(
                                field.item_fields,
                                missing_fields=missing_fields,
                            )
                        }
                    )
                ]
            )
        if field.field_type == "object" and field.fields:
            return _normalize_source_reader_fields(
                [
                    field.model_copy(
                        update={
                            "fields": _append_structured_leaf_fields(
                                field.fields,
                                missing_fields=missing_fields,
                            )
                        }
                    )
                ]
            )

    return _normalize_source_reader_fields(
        _append_structured_leaf_fields(fields, missing_fields=missing_fields)
    )


def _normalize_source_reader_fields(
    fields: list[StructuredFieldDraft],
    *,
    parent_name: str | None = None,
) -> list[StructuredFieldDraft]:
    normalized_fields: list[StructuredFieldDraft] = []
    seen: set[str] = set()
    for field in fields:
        if parent_name is not None and _is_self_nested_container_field(
            field.name,
            parent_name=parent_name,
        ):
            continue
        normalized_field = _normalize_source_reader_field(field)
        key = _source_capture_field_key(normalized_field.name)
        if key in seen:
            continue
        seen.add(key)
        normalized_fields.append(normalized_field)
    return normalized_fields


def _normalize_source_reader_field(
    field: StructuredFieldDraft,
) -> StructuredFieldDraft:
    field_name = _canonical_source_reader_field_name(field.name)
    is_source_document_array = (
        field.field_type == "array"
        and _field_name_is_source_document_container(field.name)
    )
    if is_source_document_array:
        field_name = "documents"
    updates: dict[str, object] = {"name": field_name}
    if field.field_type == "object" and field.fields:
        updates["fields"] = _normalize_source_reader_fields(
            field.fields,
            parent_name=field_name,
        )
    if field.field_type == "array":
        item_fields = (
            _normalize_source_reader_fields(
                field.item_fields,
                parent_name=field_name,
            )
            if field.item_fields
            else []
        )
        if is_source_document_array:
            item_fields = _ensure_source_label_field(item_fields)
        if item_fields:
            updates["item_fields"] = item_fields
    return field.model_copy(update=updates)


def _canonical_source_reader_field_name(field_name: str) -> str:
    tokens = _source_reader_field_tokens(field_name)
    if tokens == _DATE_TOKENS:
        return "date_or_year"
    if tokens and tokens <= _AUTHOR_OR_SENDER_TOKENS:
        return "author_or_sender"
    if tokens in _TITLE_TOKEN_SETS:
        return "title"
    if tokens in _DOCUMENT_TYPE_TOKEN_SETS:
        return "document_type"
    if tokens == _CATEGORY_TOKENS:
        return "category"
    if "conclusion" in tokens and tokens <= (
        _CONCLUSION_TOKENS | _CONCLUSION_MODIFIER_TOKENS
    ):
        return "conclusions"
    if tokens == _SUMMARY_TOKENS or (
        "summary" in tokens and tokens <= (_SUMMARY_MODIFIER_TOKENS | _SUMMARY_TOKENS)
    ):
        return "summary"
    if "requirement" in tokens and tokens <= (
        _REQUIREMENT_TOKENS | _REQUIREMENT_MODIFIER_TOKENS
    ):
        return "requirements"
    if "confidentiality" in tokens and tokens <= (
        _CONFIDENTIALITY_TOKENS | _CONFIDENTIALITY_MODIFIER_TOKENS
    ):
        return "confidentiality"
    if tokens in _SOURCE_IDENTITY_TOKENS:
        return "source_label"
    return field_name


def _source_reader_field_tokens(field_name: str) -> frozenset[str]:
    normalized = normalize_discovery_text(
        field_name.replace("_", " ").replace("-", " ")
    )
    return frozenset(
        _SOURCE_CAPTURE_FIELD_TOKEN_ALIASES.get(token, token)
        for token in normalized.split()
        if token and token != "or"
    )


def _is_self_nested_container_field(field_name: str, *, parent_name: str) -> bool:
    if _field_name_is_source_document_container(
        field_name
    ) and _field_name_is_source_document_container(parent_name):
        return True
    return _field_name_match_key(field_name).rstrip("s") == _field_name_match_key(
        parent_name
    ).rstrip("s")


def _ensure_source_label_field(
    fields: list[StructuredFieldDraft],
) -> list[StructuredFieldDraft]:
    if any(field.name == "source_label" for field in fields):
        return fields
    return [
        StructuredFieldDraft(
            name="source_label",
            field_type="string",
            description=(
                "Source file name if available, otherwise a stable source label."
            ),
        ),
        *fields,
    ]


def _structured_field_is_documents_array(field: StructuredFieldDraft) -> bool:
    return field.field_type == "array" and _field_name_is_source_document_container(
        field.name
    )


def _field_name_is_source_document_container(field_name: str) -> bool:
    return _field_name_match_key(field_name) in _SOURCE_DOCUMENT_CONTAINER_KEYS


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
    return any(_structured_field_has_name(field, required_name) for field in fields)


def _structured_field_has_name(
    field: StructuredFieldDraft,
    required_name: str,
) -> bool:
    if _field_name_matches_required_leaf(field.name, required_name):
        return True
    nested_fields = field.fields if field.field_type == "object" else field.item_fields
    return any(
        _structured_field_has_name(nested_field, required_name)
        for nested_field in nested_fields or []
    )


def _field_name_matches_required_leaf(field_name: str, required_name: str) -> bool:
    field_key = _source_capture_field_key(field_name)
    required_key = _source_capture_field_key(required_name)
    if field_key == required_key:
        return True
    field_key = _field_name_match_key(field_name)
    required_key = _field_name_match_key(required_name)
    if not field_key.endswith(f"_{required_key}"):
        return False
    logger.info(
        "ai_builder_source_reader_contract_fuzzy_leaf_match",
        extra={"field_name": field_name, "required_name": required_name},
    )
    return True


def _field_name_match_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _source_capture_field_key(value: str) -> str:
    normalized = normalize_discovery_text(value.replace("_", " ").replace("-", " "))
    tokens = tuple(
        _SOURCE_CAPTURE_FIELD_TOKEN_ALIASES.get(token, token)
        for token in normalized.split()
    )
    token_set = frozenset(tokens)
    if token_set in _TITLE_TOKEN_SETS:
        return "title"
    if token_set in _DOCUMENT_TYPE_TOKEN_SETS:
        return "document_type"
    if token_set == _CATEGORY_TOKENS:
        return "category"
    if "conclusion" in token_set and token_set <= (
        _CONCLUSION_TOKENS | _CONCLUSION_MODIFIER_TOKENS
    ):
        return "conclusion"
    if "requirement" in token_set and token_set <= (
        _REQUIREMENT_TOKENS | _REQUIREMENT_MODIFIER_TOKENS
    ):
        return "requirement"
    if "confidentiality" in token_set and token_set <= (
        _CONFIDENTIALITY_TOKENS | _CONFIDENTIALITY_MODIFIER_TOKENS
    ):
        return "confidentiality"
    if "summary" in tokens:
        tokens = tuple(
            token for token in tokens if token not in _SUMMARY_MODIFIER_TOKENS
        )
    if not tokens:
        return _field_name_match_key(value)
    return " ".join(sorted(tokens))


def _leaf_field_name(field_path: str) -> str:
    return next(
        (
            segment.strip()
            for segment in reversed(field_path.split("."))
            if segment.strip() and not segment.strip().isdigit()
        ),
        "",
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
        _form_field_source_contract_tokens(field.name),
        _form_field_source_contract_tokens(field.label),
    )
    return any(
        candidate
        and any(
            candidate.issubset(source_tokens) or source_tokens.issubset(candidate)
            for source_tokens in source_contract_token_sets
        )
        for candidate in candidates
    )


def _form_field_source_contract_tokens(value: str) -> frozenset[str]:
    return _source_contract_name_token_set(
        value,
        ignored_tokens=_SOURCE_CONTRACT_FORM_FIELD_CONTEXT_TOKENS,
    )


def _source_contract_name_tokens(value: str) -> frozenset[str]:
    return _source_contract_name_token_set(value, ignored_tokens=frozenset())


def _source_contract_name_token_set(
    value: str,
    *,
    ignored_tokens: frozenset[str],
) -> frozenset[str]:
    normalized = normalize_discovery_text(value.replace("_", " ").replace("-", " "))
    tokens = tuple(
        _SOURCE_CONTRACT_TOKEN_ALIASES.get(token, token) for token in normalized.split()
    )
    while tokens and tokens[0] in _SOURCE_CONTRACT_FORM_FIELD_PREFIX_TOKENS:
        tokens = tokens[1:]
    return frozenset(token for token in tokens if token not in ignored_tokens)


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
        key = _source_capture_field_key(name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(SourceCaptureField(name=name, description=field.description))
    return tuple(deduped)
