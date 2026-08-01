"""Deterministic, bounded schema evidence for Flow AI Builder."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from eneo.flows.ai_builder.planning_state import (
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSchemaInferenceReason,
    SchemaEvidence,
    SchemaEvidenceSource,
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
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        StructuredQuestionAnswerMetadata,
    )
    from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage

SCHEMA_MAX_JSON_BYTES = 128 * 1024
SCHEMA_MAX_DEPTH = 32
SCHEMA_FIELD_PROJECTION_MAX_ITEMS = 8
SCHEMA_FIELD_NAME_MAX_JSON_BYTES = 80
SCHEMA_PROVENANCE_MAX_ITEMS = 200
SCHEMA_CANDIDATE_MAX_ITEMS = 100
EXAMPLE_OUTPUT_MAX_JSON_BYTES = 16 * 1024
EXAMPLE_OUTPUT_MAX_FIELDS = 100
EXAMPLE_OUTPUT_MAX_DEPTH = 5

_JSON_OBJECT_ADAPTER = TypeAdapter(JsonObject)
_FENCED_JSON_BLOCK_RE = re.compile(
    r"```(?P<label>jsonschema|schema|json)?\s*(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)

logger = logging.getLogger(__name__)

SchemaLimitReason = Literal[
    "raw_bytes",
    "canonical_bytes",
    "depth",
    "candidate_count",
]

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


class SchemaLimitExceeded(ValueError):
    """A schema candidate cannot safely fit the Builder evidence contract."""

    def __init__(
        self,
        *,
        reason: SchemaLimitReason,
        max_value: int,
        actual_value: int | None,
        schema_shaped: bool,
    ) -> None:
        super().__init__(f"Schema exceeds the {reason} limit.")
        self.reason: SchemaLimitReason = reason
        self.max_value = max_value
        self.actual_value = actual_value
        self.schema_shaped = schema_shaped


@dataclass(frozen=True, slots=True)
class SchemaCandidateRefusal:
    file_id: UUID
    reason: SchemaLimitReason
    max_value: int
    actual_value: int | None
    blocks_provider_work: bool


@dataclass(frozen=True, slots=True)
class DeclaredSchemaCandidate:
    fingerprint: str
    json_schema: JsonObject
    source_file_ids: tuple[UUID, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemaFieldProjection:
    fields: tuple[str, ...]
    total_count: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class SchemaDirectionSelection:
    candidate_fingerprints: tuple[str, ...]
    input_fingerprint: str | None
    output_fingerprint: str | None
    reference_only: bool
    confidence: SignalConfidence
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExampleOutputJsonSource:
    file_id: UUID
    is_json: bool
    content: str | None
    content_complete: bool


@dataclass(frozen=True, slots=True)
class ExampleOutputSchemaInferenceResolution:
    evidence: SchemaEvidence | None
    outcome: ExampleOutputSchemaInferenceOutcome | None


class _ExampleOutputInferenceDeclined(ValueError):
    def __init__(self, reason: ExampleOutputSchemaInferenceReason) -> None:
        super().__init__(reason)
        self.reason: ExampleOutputSchemaInferenceReason = reason


def parse_schema_candidate(raw_json: str) -> JsonObject | None:
    """Parse one bounded, top-level-object JSON Schema candidate.

    Limit failures are explicit so callers can distinguish an unsafe candidate
    from ordinary JSON that simply is not a schema.
    """

    raw_bytes = len(raw_json.encode("utf-8"))
    if raw_bytes > SCHEMA_MAX_JSON_BYTES:
        raise SchemaLimitExceeded(
            reason="raw_bytes",
            max_value=SCHEMA_MAX_JSON_BYTES,
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
        raise SchemaLimitExceeded(
            reason="depth",
            max_value=SCHEMA_MAX_DEPTH,
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
        canonical_schema_bytes(candidate)
    except SchemaLimitExceeded:
        raise
    except ValueError:
        return None
    try:
        validate_schema_syntax(candidate, label="schema_evidence")
    except (RecursionError, TypedIOValidationException) as error:
        if isinstance(error, RecursionError):
            raise SchemaLimitExceeded(
                reason="depth",
                max_value=SCHEMA_MAX_DEPTH,
                actual_value=None,
                schema_shaped=True,
            ) from error
        return None
    if not schema_yields_top_level_object(candidate):
        return None
    return candidate


def canonical_schema_bytes(schema: JsonObject) -> bytes:
    """Return canonical bytes after enforcing the persisted schema ceiling."""

    try:
        encoded = canonical_json_bytes(schema)
    except RecursionError as error:
        raise SchemaLimitExceeded(
            reason="depth",
            max_value=SCHEMA_MAX_DEPTH,
            actual_value=None,
            schema_shaped=True,
        ) from error
    if len(encoded) > SCHEMA_MAX_JSON_BYTES:
        raise SchemaLimitExceeded(
            reason="canonical_bytes",
            max_value=SCHEMA_MAX_JSON_BYTES,
            actual_value=len(encoded),
            schema_shaped=True,
        )
    return encoded


def schema_fingerprint(schema: JsonObject) -> str:
    canonical_schema_bytes(schema)
    return canonical_json_hash(schema)


def build_declared_schema_candidate(
    schema: JsonObject,
    *,
    source_file_ids: tuple[UUID, ...] = (),
    provenance: tuple[str, ...],
) -> DeclaredSchemaCandidate:
    unique_provenance = tuple(dict.fromkeys(provenance))
    if not unique_provenance or any(not item.strip() for item in unique_provenance):
        raise ValueError("declared schema candidate requires bounded provenance")
    if len(unique_provenance) > SCHEMA_PROVENANCE_MAX_ITEMS:
        raise ValueError("declared schema candidate exceeds the provenance item limit")
    return DeclaredSchemaCandidate(
        fingerprint=schema_fingerprint(schema),
        json_schema=schema,
        source_file_ids=tuple(sorted(set(source_file_ids), key=str)),
        provenance=unique_provenance,
    )


def build_schema_evidence(
    *,
    json_schema: JsonObject,
    source: SchemaEvidenceSource,
    source_file_ids: tuple[UUID, ...] = (),
    confidence: SignalConfidence,
    evidence: tuple[str, ...],
    total_count: int | None = None,
    truncated: bool = False,
) -> SchemaEvidence:
    """Build the only strict persisted full-schema representation."""

    return SchemaEvidence(
        json_schema=json_schema,
        fingerprint=schema_fingerprint(json_schema),
        source=source,
        strength="explicit" if source == "declared_schema" else "inferred",
        source_file_ids=list(sorted(set(source_file_ids), key=str)),
        confidence=confidence,
        evidence=list(evidence),
        total_count=total_count,
        truncated=truncated,
    )


def declared_candidate_evidence(
    candidate: DeclaredSchemaCandidate,
    *,
    confidence: SignalConfidence,
    assignment_evidence: tuple[str, ...],
) -> SchemaEvidence:
    bounded_assignment = tuple(dict.fromkeys(assignment_evidence))
    if not bounded_assignment:
        raise ValueError("declared schema assignment requires direction evidence")
    combined_evidence = tuple(
        dict.fromkeys((*candidate.provenance, *bounded_assignment))
    )
    if len(combined_evidence) > SCHEMA_PROVENANCE_MAX_ITEMS:
        raise ValueError("schema direction evidence exceeds the provenance item limit")
    return build_schema_evidence(
        json_schema=candidate.json_schema,
        source="declared_schema",
        source_file_ids=candidate.source_file_ids,
        confidence=confidence,
        evidence=combined_evidence,
    )


def merge_declared_schema_candidates(
    *candidate_groups: tuple[DeclaredSchemaCandidate, ...],
) -> tuple[DeclaredSchemaCandidate, ...]:
    candidates_by_fingerprint: dict[str, DeclaredSchemaCandidate] = {}
    for candidate in (item for group in candidate_groups for item in group):
        existing = candidates_by_fingerprint.get(candidate.fingerprint)
        if existing is None:
            candidates_by_fingerprint[candidate.fingerprint] = candidate
            continue
        candidates_by_fingerprint[candidate.fingerprint] = (
            build_declared_schema_candidate(
                existing.json_schema,
                source_file_ids=(*existing.source_file_ids, *candidate.source_file_ids),
                provenance=(*existing.provenance, *candidate.provenance),
            )
        )
    merged = tuple(
        candidates_by_fingerprint[fingerprint]
        for fingerprint in sorted(candidates_by_fingerprint)
    )
    if len(merged) > SCHEMA_CANDIDATE_MAX_ITEMS:
        raise SchemaLimitExceeded(
            reason="candidate_count",
            max_value=SCHEMA_CANDIDATE_MAX_ITEMS,
            actual_value=len(merged),
            schema_shaped=True,
        )
    return merged


def derive_freeform_schema_candidates(
    conversation: list[ConversationMessage],
) -> tuple[DeclaredSchemaCandidate, ...]:
    """Return every bounded schema pasted by a user, without assigning direction."""

    candidates: tuple[DeclaredSchemaCandidate, ...] = ()
    for message in conversation:
        if message.role != "user" or not message.content:
            continue
        for match in _FENCED_JSON_BLOCK_RE.finditer(message.content):
            label = (match.group("label") or "").casefold()
            try:
                schema = parse_schema_candidate(match.group("body"))
            except SchemaLimitExceeded as error:
                if label in {"schema", "jsonschema"} or error.schema_shaped:
                    raise
                continue
            if schema is None:
                continue
            candidates = merge_declared_schema_candidates(
                candidates,
                (
                    build_declared_schema_candidate(
                        schema,
                        provenance=(
                            f"message:{message.message_id}",
                            "fenced_json_schema",
                        ),
                    ),
                ),
            )
    return candidates


def schema_direction_option_values(
    candidates: tuple[DeclaredSchemaCandidate, ...],
) -> tuple[str, ...]:
    fingerprints = tuple(sorted(candidate.fingerprint for candidate in candidates))
    return (
        *(
            f"{boundary}:{fingerprint}"
            for fingerprint in fingerprints
            for boundary in ("input", "output")
        ),
        "reference_only",
    )


def is_valid_structured_schema_direction_answer(
    *,
    conversation: list[ConversationMessage],
    answer: StructuredQuestionAnswerMetadata,
) -> bool:
    """Validate one explicit answer against the latest offered schema question."""

    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        tool_calls_from_message,
    )
    from eneo.flows.ai_builder.ai_builder_tool_names import (
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
    )

    offered_options: frozenset[str] | None = None
    for message in conversation:
        for tool_call in tool_calls_from_message(message):
            if (
                tool_call.name == ASK_STRUCTURED_QUESTION_TOOL_NAME
                and tool_call.arguments.get("question_id") == "schema_direction"
            ):
                offered_options = _schema_direction_offered_options(tool_call.arguments)
    if offered_options is None:
        return False

    tokens = _schema_direction_answer_tokens(answer)
    if not set(tokens) <= offered_options:
        return False
    candidate_fingerprints = tuple(
        sorted(
            {
                token.split(":", 1)[1]
                for token in offered_options
                if token != "reference_only"
            }
        )
    )
    return (
        _schema_direction_selection(
            tokens,
            candidate_fingerprints=candidate_fingerprints,
            evidence=(),
        )
        is not None
    )


def latest_schema_direction_answer_matches_candidates(
    *,
    conversation: list[ConversationMessage],
    candidates: tuple[DeclaredSchemaCandidate, ...],
) -> bool:
    """Check the current turn's explicit assignment against current candidates."""

    if not conversation:
        return True
    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        question_answer_from_metadata,
        question_answer_question_id,
    )

    answer = question_answer_from_metadata(conversation[-1].metadata)
    if answer is None or question_answer_question_id(answer) != "schema_direction":
        return True
    return (
        resolve_structured_schema_direction(
            conversation=conversation,
            candidates=candidates,
        )
        is not None
    )


def resolve_structured_schema_direction(
    *,
    conversation: list[ConversationMessage],
    candidates: tuple[DeclaredSchemaCandidate, ...],
) -> SchemaDirectionSelection | None:
    """Resolve only an answer to the exact currently offered candidate set."""

    from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
        question_answer_from_metadata,
        question_answer_question_id,
        tool_calls_from_message,
    )
    from eneo.flows.ai_builder.ai_builder_tool_names import (
        ASK_STRUCTURED_QUESTION_TOOL_NAME,
    )

    expected_options = frozenset(schema_direction_option_values(candidates))
    offered_options: frozenset[str] | None = None
    unavailable_reason = "missing_question"
    resolved: SchemaDirectionSelection | None = None
    for message in conversation:
        for tool_call in tool_calls_from_message(message):
            if (
                tool_call.name != ASK_STRUCTURED_QUESTION_TOOL_NAME
                or tool_call.arguments.get("question_id") != "schema_direction"
            ):
                continue
            parsed_options = _schema_direction_offered_options(tool_call.arguments)
            if not candidates:
                unavailable_reason = "no_current_candidates"
                offered_options = None
            elif parsed_options is None:
                unavailable_reason = "invalid_question_contract"
                offered_options = None
            elif parsed_options != expected_options:
                unavailable_reason = "candidate_set_changed"
                offered_options = None
            else:
                offered_options = parsed_options
                unavailable_reason = "missing_question"
            resolved = None
        answer = question_answer_from_metadata(message.metadata)
        if answer is None or question_answer_question_id(answer) != "schema_direction":
            continue
        if offered_options is None:
            _log_discarded_schema_direction_answer(
                message_id=message.message_id,
                reason=unavailable_reason,
            )
            continue
        tokens = _schema_direction_answer_tokens(answer)
        resolved = _schema_direction_selection(
            tokens,
            candidate_fingerprints=tuple(
                sorted(candidate.fingerprint for candidate in candidates)
            ),
            evidence=tuple(
                f"quote:structured_answer:{message.message_id}:{index}:{token}"
                for index, token in enumerate(tokens)
            ),
        )
        if resolved is None:
            _log_discarded_schema_direction_answer(
                message_id=message.message_id,
                reason="invalid_answer",
            )
    return resolved


def _log_discarded_schema_direction_answer(*, message_id: str, reason: str) -> None:
    logger.info(
        "AI Builder discarded schema-direction answer",
        extra={"message_id": message_id, "discard_reason": reason},
    )


def _schema_direction_offered_options(
    arguments: JsonObject,
) -> frozenset[str] | None:
    if (
        arguments.get("selection_mode") != "multi"
        or arguments.get("allow_custom") is not False
        or arguments.get("requires_confirm") is not True
    ):
        return None
    raw_options = arguments.get("options")
    if not isinstance(raw_options, list):
        return None
    values: set[str] = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            return None
        raw_id = raw_option.get("id")
        raw_value = raw_option.get("value")
        if (
            not isinstance(raw_id, str)
            or raw_id != raw_value
            or raw_id in values
            or (
                raw_id != "reference_only"
                and re.fullmatch(r"(?:input|output):[0-9a-f]{64}", raw_id) is None
            )
        ):
            return None
        values.add(raw_id)
    return frozenset(values) if values else None


def _schema_direction_answer_tokens(
    answer: StructuredQuestionAnswerMetadata,
) -> tuple[str, ...]:
    selected_values = answer.selected_values
    selected_option_ids = answer.selected_option_ids
    raw_values: Sequence[object]
    if isinstance(selected_values, list):
        raw_values = selected_values
    elif isinstance(selected_option_ids, list):
        raw_values = selected_option_ids
    else:
        singular_values = (
            answer.selected_value,
            answer.selected_option_id,
            answer.answer,
        )
        raw_values = [value for value in singular_values if value is not None]
    if answer.custom_value is not None:
        return ()
    return tuple(value for value in raw_values if isinstance(value, str))


def _schema_direction_selection(
    tokens: tuple[str, ...],
    *,
    candidate_fingerprints: tuple[str, ...],
    evidence: tuple[str, ...],
) -> SchemaDirectionSelection | None:
    if not tokens or len(tokens) > 2 or len(tokens) != len(set(tokens)):
        return None
    if "reference_only" in tokens:
        if tokens != ("reference_only",):
            return None
        return SchemaDirectionSelection(
            candidate_fingerprints=candidate_fingerprints,
            input_fingerprint=None,
            output_fingerprint=None,
            reference_only=True,
            confidence="high",
            evidence=evidence,
        )
    if any(
        not token.startswith("input:") and not token.startswith("output:")
        for token in tokens
    ):
        return None
    current = frozenset(candidate_fingerprints)
    input_fingerprints = [
        token.removeprefix("input:") for token in tokens if token.startswith("input:")
    ]
    output_fingerprints = [
        token.removeprefix("output:") for token in tokens if token.startswith("output:")
    ]
    if (
        len(input_fingerprints) > 1
        or len(output_fingerprints) > 1
        or not input_fingerprints
        and not output_fingerprints
        or any(
            fingerprint not in current
            for fingerprint in (*input_fingerprints, *output_fingerprints)
        )
    ):
        return None
    return SchemaDirectionSelection(
        candidate_fingerprints=candidate_fingerprints,
        input_fingerprint=input_fingerprints[0] if input_fingerprints else None,
        output_fingerprint=output_fingerprints[0] if output_fingerprints else None,
        reference_only=False,
        confidence="high",
        evidence=evidence,
    )


def resolve_example_output_schema_inference(
    *,
    sources: tuple[ExampleOutputJsonSource, ...],
    authoritative_evidence: SchemaEvidence | None,
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
        fingerprint = schema_fingerprint(schema)
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
    evidence = build_schema_evidence(
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


def project_schema_fields(schema: JsonObject) -> SchemaFieldProjection:
    """Project UTF-8-byte-bounded field names for every human-facing consumer."""

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return SchemaFieldProjection(fields=(), total_count=0, truncated=False)
    fields: list[str] = []
    total_count = 0
    for raw_name in properties:
        name = " ".join(raw_name.split())
        if not name:
            continue
        total_count += 1
        if len(fields) >= SCHEMA_FIELD_PROJECTION_MAX_ITEMS:
            continue
        fields.append(
            _truncate_json_display(
                name,
                max_serialized_bytes=SCHEMA_FIELD_NAME_MAX_JSON_BYTES,
            )
        )
    return SchemaFieldProjection(
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
        if depth > SCHEMA_MAX_DEPTH:
            raise SchemaLimitExceeded(
                reason="depth",
                max_value=SCHEMA_MAX_DEPTH,
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
    "DeclaredSchemaCandidate",
    "SCHEMA_CANDIDATE_MAX_ITEMS",
    "SCHEMA_FIELD_NAME_MAX_JSON_BYTES",
    "SCHEMA_FIELD_PROJECTION_MAX_ITEMS",
    "SCHEMA_MAX_DEPTH",
    "SCHEMA_MAX_JSON_BYTES",
    "SCHEMA_PROVENANCE_MAX_ITEMS",
    "SchemaCandidateRefusal",
    "SchemaDirectionSelection",
    "SchemaFieldProjection",
    "SchemaLimitExceeded",
    "ExampleOutputJsonSource",
    "ExampleOutputSchemaInferenceResolution",
    "build_declared_schema_candidate",
    "build_schema_evidence",
    "canonical_schema_bytes",
    "declared_candidate_evidence",
    "derive_freeform_schema_candidates",
    "is_valid_structured_schema_direction_answer",
    "latest_schema_direction_answer_matches_candidates",
    "merge_declared_schema_candidates",
    "parse_schema_candidate",
    "project_schema_fields",
    "resolve_example_output_schema_inference",
    "resolve_structured_schema_direction",
    "schema_direction_option_values",
    "schema_fingerprint",
]
