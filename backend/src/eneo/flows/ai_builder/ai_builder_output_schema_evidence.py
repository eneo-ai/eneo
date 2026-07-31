"""Deterministic, bounded output-schema evidence for Flow AI Builder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from eneo.flows.ai_builder.planning_state import (
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSchemaInferenceReason,
    OutputSchemaEvidence,
    OutputSchemaEvidenceSource,
    SignalConfidence,
)
from eneo.flows.domain.canonical_json_hash import (
    canonical_json_bytes,
    canonical_json_hash,
)
from eneo.flows.output_processing import (
    TypedIOValidationException,
    schema_yields_top_level_object,
    validate_schema_syntax,
)
from eneo.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage

OUTPUT_SCHEMA_MAX_JSON_BYTES = PLANNING_STATE_PAYLOAD_CAP_BYTES
OUTPUT_SCHEMA_MAX_DEPTH = 32
OUTPUT_SCHEMA_FIELD_PROJECTION_MAX_ITEMS = 8
OUTPUT_SCHEMA_FIELD_NAME_MAX_JSON_BYTES = 80
EXAMPLE_OUTPUT_MAX_JSON_BYTES = 16 * 1024
EXAMPLE_OUTPUT_MAX_FIELDS = 100
EXAMPLE_OUTPUT_MAX_DEPTH = 5

_JSON_OBJECT_ADAPTER = TypeAdapter(JsonObject)

OutputSchemaLimitReason = Literal["raw_bytes", "canonical_bytes", "depth"]

_JSON_SCHEMA_SHAPE_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "anyOf",
        "definitions",
        "items",
        "not",
        "oneOf",
        "properties",
        "required",
        "type",
    }
)


class OutputSchemaLimitExceeded(ValueError):
    """A schema candidate cannot safely fit the Builder evidence contract."""

    def __init__(
        self,
        *,
        reason: OutputSchemaLimitReason,
        max_value: int,
        actual_value: int | None,
        schema_shaped: bool,
    ) -> None:
        super().__init__(f"Output schema exceeds the {reason} limit.")
        self.reason: OutputSchemaLimitReason = reason
        self.max_value = max_value
        self.actual_value = actual_value
        self.schema_shaped = schema_shaped


@dataclass(frozen=True, slots=True)
class OutputSchemaCandidateRefusal:
    file_id: UUID
    reason: OutputSchemaLimitReason
    max_value: int
    actual_value: int | None
    blocks_provider_work: bool


@dataclass(frozen=True, slots=True)
class AIBuilderAttachmentOutputSchemaCandidate:
    fingerprint: str
    json_schema: JsonObject
    source_file_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class OutputSchemaFieldProjection:
    fields: tuple[str, ...]
    total_count: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class AttachmentOutputSchemaResolution:
    evidence: OutputSchemaEvidence | None
    conflict_pending: bool


@dataclass(frozen=True, slots=True)
class ExampleOutputJsonSource:
    file_id: UUID
    is_json: bool
    content: str | None
    content_complete: bool


@dataclass(frozen=True, slots=True)
class ExampleOutputSchemaInferenceResolution:
    evidence: OutputSchemaEvidence | None
    outcome: ExampleOutputSchemaInferenceOutcome | None


class _ExampleOutputInferenceDeclined(ValueError):
    def __init__(self, reason: ExampleOutputSchemaInferenceReason) -> None:
        super().__init__(reason)
        self.reason: ExampleOutputSchemaInferenceReason = reason


def parse_output_schema_candidate(raw_json: str) -> JsonObject | None:
    """Parse one bounded, top-level-object JSON Schema candidate.

    Limit failures are explicit so callers can distinguish an unsafe candidate
    from ordinary JSON that simply is not an output schema.
    """

    raw_bytes = len(raw_json.encode("utf-8"))
    if raw_bytes > OUTPUT_SCHEMA_MAX_JSON_BYTES:
        raise OutputSchemaLimitExceeded(
            reason="raw_bytes",
            max_value=OUTPUT_SCHEMA_MAX_JSON_BYTES,
            actual_value=raw_bytes,
            schema_shaped=False,
        )
    try:
        parsed: object = json.loads(
            raw_json,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    except RecursionError as error:
        raise OutputSchemaLimitExceeded(
            reason="depth",
            max_value=OUTPUT_SCHEMA_MAX_DEPTH,
            actual_value=None,
            schema_shaped=False,
        ) from error
    if not isinstance(parsed, dict):
        return None
    try:
        candidate = _JSON_OBJECT_ADAPTER.validate_python(parsed, strict=True)
    except ValidationError:
        return None
    if not _looks_like_json_schema(candidate):
        return None
    _validate_json_depth(candidate)
    try:
        canonical_output_schema_bytes(candidate)
    except OutputSchemaLimitExceeded:
        raise
    except ValueError:
        return None
    try:
        validate_schema_syntax(candidate, label="output_schema_evidence")
    except (RecursionError, TypedIOValidationException) as error:
        if isinstance(error, RecursionError):
            raise OutputSchemaLimitExceeded(
                reason="depth",
                max_value=OUTPUT_SCHEMA_MAX_DEPTH,
                actual_value=None,
                schema_shaped=True,
            ) from error
        return None
    if not schema_yields_top_level_object(candidate):
        return None
    return candidate


def canonical_output_schema_bytes(schema: JsonObject) -> bytes:
    """Return canonical bytes after enforcing the persisted schema ceiling."""

    try:
        encoded = canonical_json_bytes(schema)
    except RecursionError as error:
        raise OutputSchemaLimitExceeded(
            reason="depth",
            max_value=OUTPUT_SCHEMA_MAX_DEPTH,
            actual_value=None,
            schema_shaped=True,
        ) from error
    if len(encoded) > OUTPUT_SCHEMA_MAX_JSON_BYTES:
        raise OutputSchemaLimitExceeded(
            reason="canonical_bytes",
            max_value=OUTPUT_SCHEMA_MAX_JSON_BYTES,
            actual_value=len(encoded),
            schema_shaped=True,
        )
    return encoded


def output_schema_fingerprint(schema: JsonObject) -> str:
    canonical_output_schema_bytes(schema)
    return canonical_json_hash(schema)


def build_attachment_schema_candidate(
    schema: JsonObject,
    *,
    source_file_ids: tuple[UUID, ...],
) -> AIBuilderAttachmentOutputSchemaCandidate:
    return AIBuilderAttachmentOutputSchemaCandidate(
        fingerprint=output_schema_fingerprint(schema),
        json_schema=schema,
        source_file_ids=tuple(sorted(set(source_file_ids), key=str)),
    )


def build_output_schema_evidence(
    *,
    json_schema: JsonObject,
    source: OutputSchemaEvidenceSource,
    source_file_ids: tuple[UUID, ...] = (),
    confidence: SignalConfidence,
    evidence: tuple[str, ...],
    total_count: int | None = None,
    truncated: bool = False,
) -> OutputSchemaEvidence:
    """Build the only strict persisted full-schema representation."""

    return OutputSchemaEvidence(
        json_schema=json_schema,
        fingerprint=output_schema_fingerprint(json_schema),
        source=source,
        strength=(
            "explicit"
            if source in {"freeform_text", "attachment_json_schema"}
            else "inferred"
        ),
        source_file_ids=list(sorted(set(source_file_ids), key=str)),
        confidence=confidence,
        evidence=list(evidence),
        total_count=total_count,
        truncated=truncated,
    )


def attachment_candidate_evidence(
    candidate: AIBuilderAttachmentOutputSchemaCandidate,
) -> OutputSchemaEvidence:
    from eneo.flows.ai_builder.planning_state import (
        ATTACHMENT_JSON_SCHEMA_EVIDENCE_SUFFIX,
    )

    return build_output_schema_evidence(
        json_schema=candidate.json_schema,
        source="attachment_json_schema",
        source_file_ids=candidate.source_file_ids,
        confidence="high",
        evidence=tuple(
            f"file:{file_id}{ATTACHMENT_JSON_SCHEMA_EVIDENCE_SUFFIX}"
            for file_id in candidate.source_file_ids
        ),
    )


def resolve_attachment_output_schema(
    *,
    conversation: list[ConversationMessage],
    candidates: tuple[AIBuilderAttachmentOutputSchemaCandidate, ...],
    authoritative_evidence: OutputSchemaEvidence | None,
) -> AttachmentOutputSchemaResolution:
    """Resolve the current schema tier without reconstructing persisted candidates."""

    if (
        authoritative_evidence is not None
        and authoritative_evidence.source == "freeform_text"
    ):
        return AttachmentOutputSchemaResolution(
            evidence=authoritative_evidence,
            conflict_pending=False,
        )
    if not candidates:
        return AttachmentOutputSchemaResolution(
            evidence=authoritative_evidence,
            conflict_pending=False,
        )
    if len(candidates) == 1:
        return AttachmentOutputSchemaResolution(
            evidence=attachment_candidate_evidence(candidates[0]),
            conflict_pending=False,
        )

    current_fingerprints = frozenset(candidate.fingerprint for candidate in candidates)
    answered_selection = _latest_persisted_conflict_selection(conversation)
    if answered_selection is not None:
        option_fingerprints, selected_fingerprint = answered_selection
        candidate_by_fingerprint = {
            candidate.fingerprint: candidate for candidate in candidates
        }
        if (
            option_fingerprints == current_fingerprints
            and selected_fingerprint in option_fingerprints
            and selected_fingerprint in candidate_by_fingerprint
        ):
            return AttachmentOutputSchemaResolution(
                evidence=attachment_candidate_evidence(
                    candidate_by_fingerprint[selected_fingerprint]
                ),
                conflict_pending=False,
            )
    return AttachmentOutputSchemaResolution(evidence=None, conflict_pending=True)


def resolve_example_output_schema_inference(
    *,
    sources: tuple[ExampleOutputJsonSource, ...],
    authoritative_evidence: OutputSchemaEvidence | None,
) -> ExampleOutputSchemaInferenceResolution:
    """Resolve selected example-output JSON into one deliberately open schema."""

    if not sources:
        return ExampleOutputSchemaInferenceResolution(
            evidence=(
                None
                if authoritative_evidence is not None
                and authoritative_evidence.source == "inferred_example"
                else authoritative_evidence
            ),
            outcome=None,
        )

    ordered_sources = tuple(sorted(sources, key=lambda item: str(item.file_id)))
    all_source_file_ids = tuple(item.file_id for item in ordered_sources)
    if (
        authoritative_evidence is not None
        and authoritative_evidence.source != "inferred_example"
    ):
        return ExampleOutputSchemaInferenceResolution(
            evidence=authoritative_evidence,
            outcome=_example_output_inference_outcome(
                status="not_inferred",
                reason="higher_priority_schema",
                source_file_ids=all_source_file_ids,
            ),
        )

    json_sources = tuple(item for item in ordered_sources if item.is_json)
    if not json_sources:
        return ExampleOutputSchemaInferenceResolution(
            evidence=None,
            outcome=_example_output_inference_outcome(
                status="not_inferred",
                reason="no_json_object",
                source_file_ids=all_source_file_ids,
            ),
        )

    schemas_by_fingerprint: dict[str, tuple[JsonObject, list[UUID]]] = {}
    for source in json_sources:
        try:
            schema = _infer_example_output_json_schema(source)
        except _ExampleOutputInferenceDeclined as error:
            return ExampleOutputSchemaInferenceResolution(
                evidence=None,
                outcome=_example_output_inference_outcome(
                    status="not_inferred",
                    reason=error.reason,
                    source_file_ids=tuple(item.file_id for item in json_sources),
                ),
            )
        fingerprint = output_schema_fingerprint(schema)
        existing = schemas_by_fingerprint.get(fingerprint)
        if existing is None:
            schemas_by_fingerprint[fingerprint] = (schema, [source.file_id])
        else:
            existing[1].append(source.file_id)

    inferred_source_file_ids = tuple(item.file_id for item in json_sources)
    if len(schemas_by_fingerprint) != 1:
        return ExampleOutputSchemaInferenceResolution(
            evidence=None,
            outcome=_example_output_inference_outcome(
                status="not_inferred",
                reason="conflicting_shapes",
                source_file_ids=inferred_source_file_ids,
            ),
        )

    schema, source_file_ids = next(iter(schemas_by_fingerprint.values()))
    evidence = build_output_schema_evidence(
        json_schema=schema,
        source="inferred_example",
        source_file_ids=tuple(source_file_ids),
        confidence="medium",
        evidence=tuple(
            f"file:{file_id}:inferred_example_shape" for file_id in source_file_ids
        ),
    )
    return ExampleOutputSchemaInferenceResolution(
        evidence=evidence,
        outcome=_example_output_inference_outcome(
            status="inferred",
            reason=None,
            source_file_ids=tuple(source_file_ids),
        ),
    )


def _example_output_inference_outcome(
    *,
    status: Literal["inferred", "not_inferred"],
    reason: ExampleOutputSchemaInferenceReason | None,
    source_file_ids: tuple[UUID, ...],
) -> ExampleOutputSchemaInferenceOutcome:
    return ExampleOutputSchemaInferenceOutcome(
        status=status,
        reason=reason,
        source_file_ids=list(sorted(set(source_file_ids), key=str)),
    )


def _infer_example_output_json_schema(
    source: ExampleOutputJsonSource,
) -> JsonObject:
    if not source.content_complete or source.content is None:
        raise _ExampleOutputInferenceDeclined("incomplete_content")
    raw_bytes = len(source.content.encode("utf-8"))
    if raw_bytes > EXAMPLE_OUTPUT_MAX_JSON_BYTES:
        raise _ExampleOutputInferenceDeclined("raw_bytes")
    try:
        parsed: object = json.loads(
            source.content,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, ValueError):
        raise _ExampleOutputInferenceDeclined("invalid_json") from None
    except RecursionError:
        raise _ExampleOutputInferenceDeclined("depth") from None
    if not isinstance(parsed, dict):
        raise _ExampleOutputInferenceDeclined("top_level_not_object")
    try:
        example = _JSON_OBJECT_ADAPTER.validate_python(parsed, strict=True)
    except ValidationError:
        raise _ExampleOutputInferenceDeclined("invalid_json") from None
    schema = _infer_example_output_value_schema(example, depth=1)
    if _inferred_schema_field_count(schema) > EXAMPLE_OUTPUT_MAX_FIELDS:
        raise _ExampleOutputInferenceDeclined("field_count")
    return schema


def _reject_nonstandard_json_constant(value: str) -> object:
    raise ValueError(f"Non-standard JSON constant: {value}")


def _infer_example_output_value_schema(
    value: JsonValue,
    *,
    depth: int,
) -> JsonObject:
    if depth > EXAMPLE_OUTPUT_MAX_DEPTH:
        raise _ExampleOutputInferenceDeclined("depth")
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, dict):
        properties: JsonObject = {}
        for name, nested_value in value.items():
            properties[name] = _infer_example_output_value_schema(
                nested_value,
                depth=depth + 1,
            )
        return {"type": "object", "properties": properties}
    schema: JsonObject = {"type": "array"}
    if not value:
        return schema
    item_schemas = [
        _infer_example_output_value_schema(
            item,
            depth=depth + 1,
        )
        for item in value
    ]
    first = item_schemas[0]
    if first and all(item == first for item in item_schemas[1:]):
        schema["items"] = first
    return schema


def _inferred_schema_field_count(schema: JsonObject) -> int:
    count = 0
    stack: list[JsonValue] = [schema]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        properties = current.get("properties")
        if isinstance(properties, dict):
            count += len(properties)
            if count > EXAMPLE_OUTPUT_MAX_FIELDS:
                return count
            stack.extend(properties.values())
        items = current.get("items")
        if isinstance(items, dict):
            stack.append(items)
    return count


def _latest_persisted_conflict_selection(
    conversation: list[ConversationMessage],
) -> tuple[frozenset[str], str] | None:
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        question_answer_from_metadata,
        question_answer_question_id,
        question_answer_values,
        tool_calls_from_message,
    )
    from eneo.flows.ai_builder.ai_builder_tool_names import (
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
    )

    pending_options: frozenset[str] | None = None
    answered: tuple[frozenset[str], str] | None = None
    for message in conversation:
        for tool_call in tool_calls_from_message(message):
            if tool_call.name != ASK_STRUCTURED_QUESTION_TOOL_NAME:
                continue
            try:
                arguments = _JSON_OBJECT_ADAPTER.validate_python(
                    tool_call.arguments,
                    strict=True,
                )
            except ValidationError:
                continue
            if arguments.get("question_id") != "output_schema_conflict":
                continue
            option_fingerprints = _option_fingerprints(arguments.get("options"))
            if option_fingerprints is None:
                pending_options = None
                answered = None
                continue
            pending_options = option_fingerprints
            answered = None
        answer = question_answer_from_metadata(message.metadata)
        if (
            answer is None
            or question_answer_question_id(answer) != "output_schema_conflict"
            or pending_options is None
        ):
            continue
        selected = question_answer_values(answer)
        selected_value = next(iter(selected)) if len(selected) == 1 else None
        if isinstance(selected_value, str) and selected_value in pending_options:
            answered = (pending_options, selected_value)
        else:
            answered = None
    return answered


def _option_fingerprints(raw_options: JsonValue | None) -> frozenset[str] | None:
    if not isinstance(raw_options, list):
        return None
    fingerprints: set[str] = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            return None
        raw_id = raw_option.get("id")
        raw_value = raw_option.get("value")
        if (
            not isinstance(raw_id, str)
            or not isinstance(raw_value, str)
            or raw_id != raw_value
            or re.fullmatch(r"[0-9a-f]{64}", raw_id) is None
            or raw_id in fingerprints
        ):
            return None
        fingerprints.add(raw_id)
    return frozenset(fingerprints) if fingerprints else None


def project_output_schema_fields(schema: JsonObject) -> OutputSchemaFieldProjection:
    """Project UTF-8-byte-bounded field names for every human-facing consumer."""

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return OutputSchemaFieldProjection(fields=(), total_count=0, truncated=False)
    fields: list[str] = []
    total_count = 0
    for raw_name in properties:
        name = " ".join(raw_name.split())
        if not name:
            continue
        total_count += 1
        if len(fields) >= OUTPUT_SCHEMA_FIELD_PROJECTION_MAX_ITEMS:
            continue
        fields.append(
            _truncate_json_display(
                name,
                max_serialized_bytes=OUTPUT_SCHEMA_FIELD_NAME_MAX_JSON_BYTES,
            )
        )
    return OutputSchemaFieldProjection(
        fields=tuple(fields),
        total_count=total_count,
        truncated=total_count > len(fields),
    )


def _truncate_json_display(value: str, *, max_serialized_bytes: int) -> str:
    serialized = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(serialized) <= max_serialized_bytes:
        return value

    ellipsis = "…"
    content_budget = max_serialized_bytes - len(b'""') - len(ellipsis.encode("utf-8"))
    retained: list[str] = []
    retained_bytes = 0
    for character in value:
        escaped_character = json.dumps(character, ensure_ascii=False)[1:-1].encode(
            "utf-8"
        )
        if retained_bytes + len(escaped_character) > content_budget:
            break
        retained.append(character)
        retained_bytes += len(escaped_character)
    return f"{''.join(retained)}{ellipsis}"


def _validate_json_depth(value: JsonValue) -> None:
    stack: list[tuple[JsonValue, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > OUTPUT_SCHEMA_MAX_DEPTH:
            raise OutputSchemaLimitExceeded(
                reason="depth",
                max_value=OUTPUT_SCHEMA_MAX_DEPTH,
                actual_value=depth,
                schema_shaped=True,
            )
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _looks_like_json_schema(candidate: JsonObject) -> bool:
    return any(key in candidate for key in _JSON_SCHEMA_SHAPE_KEYS)


__all__ = [
    "EXAMPLE_OUTPUT_MAX_DEPTH",
    "EXAMPLE_OUTPUT_MAX_FIELDS",
    "EXAMPLE_OUTPUT_MAX_JSON_BYTES",
    "AIBuilderAttachmentOutputSchemaCandidate",
    "AttachmentOutputSchemaResolution",
    "OUTPUT_SCHEMA_FIELD_NAME_MAX_JSON_BYTES",
    "OUTPUT_SCHEMA_FIELD_PROJECTION_MAX_ITEMS",
    "OUTPUT_SCHEMA_MAX_DEPTH",
    "OUTPUT_SCHEMA_MAX_JSON_BYTES",
    "OutputSchemaCandidateRefusal",
    "OutputSchemaFieldProjection",
    "OutputSchemaLimitExceeded",
    "ExampleOutputJsonSource",
    "ExampleOutputSchemaInferenceResolution",
    "attachment_candidate_evidence",
    "build_attachment_schema_candidate",
    "build_output_schema_evidence",
    "canonical_output_schema_bytes",
    "output_schema_fingerprint",
    "parse_output_schema_candidate",
    "project_output_schema_fields",
    "resolve_attachment_output_schema",
    "resolve_example_output_schema_inference",
]
