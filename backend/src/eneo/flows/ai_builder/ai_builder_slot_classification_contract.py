"""Typed request, response, schema, and parsing contract for slot classification."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast, get_args
from uuid import UUID

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_VALUES,
    ResultObligation,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_EVIDENCE_MAX_CITATIONS,
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    AttachmentCoverage,
    CheckpointProducerKind,
    ExampleOutputConstraintEvidence,
    ExampleOutputStyleCategory,
    FileRole,
    SlotEvidenceLevel,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode

SlotClassificationConfidence = Literal["high", "medium", "low"]
SlotClassificationEvidenceLevel = SlotEvidenceLevel
CheckpointUpdateOperation = Literal["update", "clear"]
SlotClassificationAttemptOutcome = Literal[
    "resolved",
    "no_content",
    "parse_failed",
    "skipped_context_budget",
    "skipped_no_resolvable_slots",
]
SlotClassificationSourceKind = Literal[
    "user_message",
    "structured_answer",
    "uploaded_file",
]
_USER_OWNED_CLASSIFICATION_SOURCE_KINDS: frozenset[SlotClassificationSourceKind] = (
    frozenset({"user_message", "structured_answer"})
)
_FIELD_STRUCTURAL_BOUNDARIES = frozenset(
    {"$", "@", "#", "/", "\\", ":", "[", "]", "{", "}", "."}
)
UNKNOWN_SLOT_VALUE = "unknown"
SLOT_CLASSIFICATION_SCHEMA_VERSION = 20
CLASSIFICATION_EVIDENCE_MAX_ITEMS = 3
CLASSIFICATION_EVIDENCE_MAX_LENGTH = 240
CLASSIFICATION_REASON_MAX_LENGTH = 500
NAMED_RESULT_DELTA_CITATION_MAX_ITEMS = NAMED_RESULT_EVIDENCE_MAX_CITATIONS
CLASSIFICATION_NOTE_MAX_LENGTH = 500
CLASSIFICATION_NOTES_MAX_ITEMS = 10
EXAMPLE_OUTPUT_HEADINGS_MAX_ITEMS = 20
EXAMPLE_OUTPUT_STYLE_CONSTRAINTS_MAX_ITEMS = 20
EXAMPLE_OUTPUT_CITATIONS_MAX_ITEMS = 12


@dataclass(frozen=True, slots=True)
class SlotClassificationSource:
    source_id: str
    kind: SlotClassificationSourceKind
    text: str
    message_id: str | None = None
    question_id: str | None = None
    selected_value: str | None = None
    file_id: UUID | None = None
    coverage: AttachmentCoverage | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SlotClassificationInput:
    sources: tuple[SlotClassificationSource, ...]
    current_user_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClassifiedEvidence:
    source_id: str
    quote: str

    def planning_reference(self) -> str:
        return f"quote:{self.source_id}:{self.quote}"


def planning_reference_cites_source(reference: str, *, source_id: str) -> bool:
    """Match a persisted quote to its complete source identity."""

    return reference.startswith(f"quote:{source_id}:")


def quoted_texts_from_planning_references(references: Sequence[str]) -> list[str]:
    """Return every user quote carried by persisted evidence references."""

    return [
        text
        for reference in references
        for text in [quoted_text_from_planning_reference(reference)]
        if text is not None
    ]


def quoted_text_from_planning_reference(reference: str) -> str | None:
    """Return the user's words from a persisted evidence reference.

    The decoder lives beside `ClassifiedEvidence.planning_reference` so the
    encoding has one owner: source ids carry their own colons, so a naive
    prefix strip leaks internal ids into user-facing remediation text
    (observed live 2026-08-06).
    """

    if not reference.startswith("quote:"):
        return None
    body = reference.removeprefix("quote:")
    source_id, separator, quote = body.partition(":")
    if source_id in _COMPOUND_EVIDENCE_SOURCE_KINDS:
        _, _, remainder = quote.partition(":")
        quote = remainder or quote
    text = quote.strip() if separator else ""
    return text or None


# Source kinds whose ids embed a second colon (`user_message:<message_id>`).
_COMPOUND_EVIDENCE_SOURCE_KINDS = frozenset(
    {"user_message", "assistant_message", "answer", "attachment", "file"}
)


@dataclass(frozen=True, slots=True)
class ClassifiedSchemaDirection:
    candidate_fingerprints: tuple[str, ...]
    input_fingerprint: str | None
    output_fingerprint: str | None
    reference_only: bool
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassifiedSlot:
    slot_name: str
    value: str
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...] = ()
    evidence_level: SlotClassificationEvidenceLevel = "inferred"


@dataclass(frozen=True, slots=True)
class ClassifiedFileRole:
    file_id: UUID
    role: FileRole
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...] = ()
    evidence_level: SlotClassificationEvidenceLevel = "inferred"


@dataclass(frozen=True, slots=True)
class ClassifiedFormIntake:
    needs_form_fields: bool
    sectioned_form_intake: bool
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...] = ()
    evidence_level: SlotClassificationEvidenceLevel = "inferred"


@dataclass(frozen=True, slots=True)
class ClassifiedCheckpointUpdate:
    operation: CheckpointUpdateOperation
    producer_kind: CheckpointProducerKind
    mode: FlowStepReviewMode | None
    confidence: SlotClassificationConfidence
    reason: str
    evidence: tuple[ClassifiedEvidence, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedNamedResultEvidence:
    name: str
    evidence: tuple[ClassifiedEvidence, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedNamedResultDelta:
    operation: Literal["update", "clear"]
    names: tuple[str, ...]
    confidence: SlotClassificationConfidence
    reason: str
    removed_names: tuple[str, ...] = ()
    evidence: tuple[ClassifiedEvidence, ...] = ()
    evidence_by_name: tuple[ClassifiedNamedResultEvidence, ...] = ()

    def __post_init__(self) -> None:
        changed_names = tuple(
            fold_result_field_name(name) for name in (*self.names, *self.removed_names)
        )
        mapped_names = tuple(
            fold_result_field_name(item.name) for item in self.evidence_by_name
        )
        if (
            any(not name for name in (*changed_names, *mapped_names))
            or len(changed_names) != len(set(changed_names))
            or len(mapped_names) != len(set(mapped_names))
            or set(mapped_names) != set(changed_names)
        ):
            raise ValueError("evidence_by_name must exactly cover named-result changes")
        allowed_evidence = set(self.evidence)
        if any(
            not item.evidence
            or any(citation not in allowed_evidence for citation in item.evidence)
            for item in self.evidence_by_name
        ):
            raise ValueError("evidence_by_name citations must belong to delta evidence")


@dataclass(frozen=True, slots=True)
class SlotClassificationResult:
    slots: tuple[ClassifiedSlot, ...] = ()
    file_roles: tuple[ClassifiedFileRole, ...] = ()
    checkpoint_updates: tuple[ClassifiedCheckpointUpdate, ...] = ()
    form_intake: ClassifiedFormIntake | None = None
    named_result_evidence: ClassifiedNamedResultDelta | None = None
    example_output_constraints: ExampleOutputConstraintEvidence | None = None
    schema_direction: ClassifiedSchemaDirection | None = None
    secondary_obligations: tuple[ResultObligation, ...] = ()
    assumptions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    cached: bool = False


@dataclass(frozen=True, slots=True)
class SlotClassificationAttempt:
    outcome: SlotClassificationAttemptOutcome
    result: SlotClassificationResult | None = None

    def __post_init__(self) -> None:
        if (self.outcome == "resolved") != (self.result is not None):
            raise ValueError(
                "Resolved slot classification attempts require a result; "
                "other outcomes must not carry one"
            )


@dataclass(frozen=True, slots=True)
class SlotClassificationBias:
    """Sharpens classification toward the slot the user was just asked about.

    When the user has answered a specific clarification question, the classifier
    should prioritize resolving that slot from the (possibly indirect) latest
    reply instead of weighting the whole conversation evenly.
    """

    target_slot_name: str
    asked_question_id: str
    answer_source_id: str


def classification_evidence_has_user_owned_source(
    evidence_source_ids: Iterable[str],
    *,
    source_kinds_by_id: Mapping[str, SlotClassificationSourceKind],
) -> bool:
    return any(
        source_kinds_by_id.get(source_id) in _USER_OWNED_CLASSIFICATION_SOURCE_KINDS
        for source_id in evidence_source_ids
    )


def slot_classification_input_is_valid(
    classification_input: SlotClassificationInput,
) -> bool:
    current_user_message_id = classification_input.current_user_message_id
    if current_user_message_id is not None and not current_user_message_id.strip():
        return False
    source_ids = [source.source_id for source in classification_input.sources]
    if not source_ids or len(source_ids) != len(set(source_ids)):
        return False
    return all(
        _classification_source_is_valid(source)
        for source in classification_input.sources
    )


def _classification_source_is_valid(source: SlotClassificationSource) -> bool:
    if not source.source_id.strip() or not source.text.strip():
        return False
    if source.kind == "user_message":
        return source.message_id is not None and bool(source.message_id.strip())
    if source.kind == "structured_answer":
        return (
            source.message_id is not None
            and bool(source.message_id.strip())
            and source.question_id is not None
            and bool(source.question_id.strip())
            and source.selected_value is not None
            and bool(source.selected_value.strip())
        )
    return source.file_id is not None and source.coverage is not None


def parse_slot_classification_response(
    content: str,
    *,
    allowed_slot_values: Mapping[str, Collection[str]],
    classification_input: SlotClassificationInput,
    schema_candidate_fingerprints: Collection[str] = (),
) -> SlotClassificationResult | None:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, dict):
        return None
    raw_dict = cast(dict[str, Any], raw)
    if not _slot_classification_top_level_contract_is_valid(
        raw_dict,
        allowed_slot_values=allowed_slot_values,
        schema_candidate_fingerprints=schema_candidate_fingerprints,
    ):
        return None
    raw_slots = cast(list[object], raw_dict["slots"])

    slot_values = normalize_slot_classification_values(allowed_slot_values)
    source_kinds_by_id: dict[str, SlotClassificationSourceKind] = {
        source.source_id: source.kind for source in classification_input.sources
    }
    slots: list[ClassifiedSlot] = []
    seen_slot_names: set[str] = set()
    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        slot_name = item_dict.get("slot_name")
        value = item_dict.get("value")
        confidence = item_dict.get("confidence")
        reason = item_dict.get("reason")
        evidence = _parse_classification_evidence(
            item_dict.get("evidence", []),
            classification_input=classification_input,
        )
        if not isinstance(slot_name, str) or slot_name not in slot_values:
            continue
        if slot_name in seen_slot_names:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        normalized_value = value.strip()
        if (
            normalized_value != UNKNOWN_SLOT_VALUE
            and normalized_value not in slot_values[slot_name]
        ):
            continue
        if confidence not in {"high", "medium", "low"}:
            continue
        evidence_level = _validated_evidence_level(
            item_dict.get("evidence_level", "inferred"),
            evidence,
            classification_input=classification_input,
            structured_question_id=slot_name,
        )
        if slot_name == "terminal_output" and not (
            classification_evidence_has_user_owned_source(
                (item.source_id for item in evidence),
                source_kinds_by_id=source_kinds_by_id,
            )
        ):
            continue
        confidence_value = cast(SlotClassificationConfidence, confidence)
        slots.append(
            ClassifiedSlot(
                slot_name=slot_name,
                value=normalized_value,
                confidence=_downgrade_unsupported_confidence(
                    confidence_value,
                    evidence,
                ),
                reason=reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "slot classification",
                evidence=evidence,
                evidence_level=evidence_level,
            )
        )
        seen_slot_names.add(slot_name)

    assumptions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("assumptions", []))
        if isinstance(item, str) and item.strip()
    )
    contradictions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("contradictions", []))
        if isinstance(item, str) and item.strip()
    )
    file_roles = _parse_file_roles(
        raw_dict.get("file_roles", []),
        classification_input=classification_input,
    )
    checkpoint_updates = _parse_checkpoint_updates(
        raw_dict["checkpoint_updates"],
        classification_input=classification_input,
    )
    if checkpoint_updates is None:
        return None
    form_intake = _parse_form_intake(
        raw_dict.get("form_intake"),
        classification_input=classification_input,
    )
    try:
        named_result_evidence = _parse_named_result_evidence(
            raw_dict.get("named_result_evidence"),
            classification_input=classification_input,
        )
    except _MalformedNamedResultDelta:
        # A structurally malformed present delta fails the attempt visibly
        # (parse_failed retries); resolving without the fields was the
        # silent schema loss the raw capture attributed. Citation-level
        # refusals keep the established refuse-fields semantics.
        return None
    example_output_constraints = _parse_example_output_constraints(
        raw_dict.get("example_output_constraints"),
        classification_input=classification_input,
        file_roles=file_roles,
    )
    secondary_obligations = _parse_secondary_obligations(
        raw_dict.get("secondary_obligations", [])
    )
    schema_direction = _parse_schema_direction(
        raw_dict.get("schema_direction"),
        classification_input=classification_input,
        candidate_fingerprints=tuple(sorted(set(schema_candidate_fingerprints))),
    )
    return SlotClassificationResult(
        slots=tuple(slots),
        file_roles=file_roles,
        checkpoint_updates=checkpoint_updates,
        form_intake=form_intake,
        named_result_evidence=named_result_evidence,
        example_output_constraints=example_output_constraints,
        schema_direction=schema_direction,
        secondary_obligations=secondary_obligations,
        assumptions=assumptions,
        contradictions=contradictions,
    )


def _slot_classification_top_level_contract_is_valid(
    payload: Mapping[str, object],
    *,
    allowed_slot_values: Mapping[str, Collection[str]],
    schema_candidate_fingerprints: Collection[str],
) -> bool:
    properties = _slot_classification_top_level_properties(
        allowed_slot_values,
        schema_candidate_fingerprints=schema_candidate_fingerprints,
    )
    if frozenset(payload) != frozenset(properties):
        return False
    for field, schema in properties.items():
        value = payload[field]
        if schema.get("type") == "array":
            if not isinstance(value, list):
                return False
            continue
        if value is not None and not isinstance(value, dict):
            return False
    return True


class _MalformedNamedResultDelta(Exception):
    """A present named-result delta violated its structure."""


def _parse_named_result_evidence(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
) -> ClassifiedNamedResultDelta | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise _MalformedNamedResultDelta
    item = cast(dict[str, Any], raw_value)
    operation = item.get("operation")
    if operation not in {"update", "clear"}:
        raise _MalformedNamedResultDelta
    raw_names = item.get("names")
    raw_removed_names = item.get("removed_names")
    if not isinstance(raw_names, list) or not isinstance(raw_removed_names, list):
        raise _MalformedNamedResultDelta
    raw_name_items = cast(list[object], raw_names)
    raw_removed_name_items = cast(list[object], raw_removed_names)
    if operation == "update" and not (raw_name_items or raw_removed_name_items):
        raise _MalformedNamedResultDelta
    if operation == "clear" and (raw_name_items or raw_removed_name_items):
        raise _MalformedNamedResultDelta
    confidence = item.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        raise _MalformedNamedResultDelta
    evidence = _parse_classification_evidence(
        item.get("evidence", []),
        classification_input=classification_input,
        max_items=NAMED_RESULT_DELTA_CITATION_MAX_ITEMS,
    )
    source_kinds = {
        source.source_id: source.kind for source in classification_input.sources
    }
    current_user_message_id = classification_input.current_user_message_id
    if current_user_message_id is None:
        return None
    source_texts = {
        source.source_id: source.text for source in classification_input.sources
    }
    source_message_ids = {
        source.source_id: source.message_id for source in classification_input.sources
    }
    user_owned_evidence = tuple(
        cited
        for cited in evidence
        if source_kinds[cited.source_id] in _USER_OWNED_CLASSIFICATION_SOURCE_KINDS
        and source_message_ids[cited.source_id] == current_user_message_id
    )
    if not user_owned_evidence:
        return None
    evidence_by_name = _parse_cited_named_result_evidence(
        raw_name_items,
        evidence=user_owned_evidence,
        source_texts=source_texts,
    )
    removed_evidence_by_name = _parse_cited_named_result_evidence(
        raw_removed_name_items,
        evidence=user_owned_evidence,
        source_texts=source_texts,
    )
    if evidence_by_name is None or removed_evidence_by_name is None:
        return None
    names = tuple(item.name for item in evidence_by_name)
    removed_names = tuple(item.name for item in removed_evidence_by_name)
    folded_names = [fold_result_field_name(name) for name in (*names, *removed_names)]
    if (
        any(not name for name in folded_names)
        or len(folded_names) != len(set(folded_names))
        or len(folded_names) > NAMED_RESULT_EVIDENCE_MAX_ITEMS
    ):
        return None
    reason = item.get("reason")
    return ClassifiedNamedResultDelta(
        operation=cast(Literal["update", "clear"], operation),
        names=names,
        confidence=cast(SlotClassificationConfidence, confidence),
        reason=(
            reason.strip()
            if isinstance(reason, str) and reason.strip()
            else "named-result classification"
        ),
        removed_names=removed_names,
        evidence=user_owned_evidence,
        evidence_by_name=(*evidence_by_name, *removed_evidence_by_name),
    )


def _parse_checkpoint_updates(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
) -> tuple[ClassifiedCheckpointUpdate, ...] | None:
    if not isinstance(raw_value, list):
        return None
    producer_kinds = set(get_args(CheckpointProducerKind))
    review_modes = {mode.value: mode for mode in FlowStepReviewMode}
    source_kinds = {
        source.source_id: source.kind for source in classification_input.sources
    }
    source_message_ids = {
        source.source_id: source.message_id for source in classification_input.sources
    }
    current_user_message_id = classification_input.current_user_message_id
    updates: list[ClassifiedCheckpointUpdate] = []
    seen_producers: set[str] = set()
    for item in cast(list[object], raw_value):
        if not isinstance(item, dict):
            return None
        payload = cast(dict[str, object], item)
        operation = payload.get("operation")
        if operation not in {"update", "clear"}:
            return None
        producer_kind = payload.get("producer_kind")
        if not isinstance(producer_kind, str) or producer_kind not in producer_kinds:
            return None
        if producer_kind in seen_producers:
            return None
        seen_producers.add(producer_kind)
        confidence = payload.get("confidence")
        if confidence not in {"high", "medium"}:
            return None
        raw_mode = payload.get("mode")
        if operation == "update":
            if raw_mode not in review_modes:
                return None
            mode = review_modes[cast(str, raw_mode)]
        else:
            if raw_mode is not None:
                return None
            mode = None
        evidence = _parse_classification_evidence(
            payload.get("evidence", []),
            classification_input=classification_input,
        )
        if not evidence or current_user_message_id is None:
            return None
        if not any(
            source_kinds[cited.source_id] in _USER_OWNED_CLASSIFICATION_SOURCE_KINDS
            and source_message_ids[cited.source_id] == current_user_message_id
            for cited in evidence
        ):
            return None
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return None
        updates.append(
            ClassifiedCheckpointUpdate(
                operation=cast(CheckpointUpdateOperation, operation),
                producer_kind=cast(CheckpointProducerKind, producer_kind),
                mode=mode,
                confidence=cast(SlotClassificationConfidence, confidence),
                reason=reason.strip(),
                evidence=evidence,
            )
        )
    return tuple(updates)


def _parse_cited_named_result_evidence(
    raw_names: list[object],
    *,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> tuple[ClassifiedNamedResultEvidence, ...] | None:
    evidence_by_name: list[ClassifiedNamedResultEvidence] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str) or not raw_name:
            return None
        named_evidence = _cited_named_result_evidence(
            raw_name,
            evidence=evidence,
            source_texts=source_texts,
        )
        if named_evidence is None or any(
            item.name == named_evidence.name for item in evidence_by_name
        ):
            return None
        evidence_by_name.append(named_evidence)
    return tuple(evidence_by_name)


def _cited_named_result_evidence(
    raw_name: str,
    *,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> ClassifiedNamedResultEvidence | None:
    cited_occurrences: list[
        tuple[ClassifiedEvidence, frozenset[Literal["quoted", "unquoted"]]]
    ] = []
    for cited in evidence:
        occurrence_kinds = _cited_field_occurrence_kinds(
            source_text=source_texts[cited.source_id],
            quote=cited.quote,
            field_name=raw_name,
        )
        if occurrence_kinds:
            cited_occurrences.append((cited, occurrence_kinds))
    occurrence_kinds = {kind for _, kinds in cited_occurrences for kind in kinds}
    if occurrence_kinds == {"quoted"}:
        name = raw_name
    elif occurrence_kinds == {"unquoted"}:
        phrase = raw_name
        while phrase.endswith(("[]", "{}")):
            phrase = phrase[:-2]
        name = _normalize_unquoted_named_result_name(phrase)
    else:
        return None
    if name is None:
        return None
    return ClassifiedNamedResultEvidence(
        name=name,
        evidence=tuple(cited for cited, _ in cited_occurrences),
    )


def _normalize_unquoted_named_result_name(phrase: str) -> str | None:
    normalized = unicodedata.normalize("NFKD", phrase).casefold()
    field_name_parts: list[str] = []
    separating = False
    for character in normalized:
        category = unicodedata.category(character)
        if category.startswith("M"):
            continue
        if category.startswith(("L", "N")):
            if separating and field_name_parts:
                field_name_parts.append("_")
            field_name_parts.append(character)
            separating = False
        else:
            separating = True
    field_name = "".join(field_name_parts).strip("_")
    return field_name or None


def _cited_field_occurrence_kinds(
    *,
    source_text: str,
    quote: str,
    field_name: str,
) -> frozenset[Literal["quoted", "unquoted"]]:
    """Validate quoted field occurrences against their complete source context."""
    kinds: set[Literal["quoted", "unquoted"]] = set()
    quote_start = 0
    while (quote_index := source_text.find(quote, quote_start)) >= 0:
        field_start = 0
        while (field_index := quote.find(field_name, field_start)) >= 0:
            absolute_start = quote_index + field_index
            kind = _valid_field_occurrence_kind(
                source_text,
                start_index=absolute_start,
                end_index=absolute_start + len(field_name),
            )
            if kind is not None:
                kinds.add(kind)
            field_start = field_index + 1
        quote_start = quote_index + 1
    return frozenset(kinds)


def _valid_field_occurrence_kind(
    text: str,
    *,
    start_index: int,
    end_index: int,
) -> Literal["quoted", "unquoted"] | None:
    before = text[start_index - 1] if start_index > 0 else None
    # A cited name may carry JSON shape notation in the source
    # ("applicant_channels[]"): the notation belongs to the mention, not
    # its boundary. The model names the bare field; judge the boundary
    # after the notation.
    if text[end_index : end_index + 2] in ("[]", "{}"):
        end_index += 2
    after = text[end_index] if end_index < len(text) else None
    before_is_quote = before is not None and _is_quotation_mark(before)
    after_is_quote = after is not None and _is_quotation_mark(after)
    if before_is_quote != after_is_quote:
        return None
    if before_is_quote and after_is_quote:
        assert before is not None and after is not None
        if not _quotation_marks_form_pair(before, after):
            return None
        outside_before_index = _field_outer_boundary_index(
            text,
            start_index=start_index - 2,
            direction=-1,
        )
        outside_after_index = _field_outer_boundary_index(
            text,
            start_index=end_index + 1,
            direction=1,
        )
        outside_before = (
            text[outside_before_index] if outside_before_index is not None else None
        )
        outside_after = (
            text[outside_after_index] if outside_after_index is not None else None
        )
        if _field_boundary_is_ambiguous(
            outside_before,
            side="before",
            allow_declaration_colon=(
                outside_before == ":"
                and outside_before_index is not None
                and outside_before_index < start_index - 2
            ),
        ) or (
            _field_boundary_is_ambiguous(
                outside_after,
                side="after",
                text=text,
                index=(outside_after_index if outside_after_index is not None else 0),
                adjacent_to_name=outside_after_index == end_index + 1,
            )
        ):
            return None
        return "quoted"
    outside_before_index = _field_outer_boundary_index(
        text,
        start_index=start_index - 1,
        direction=-1,
    )
    outside_after_index = _field_outer_boundary_index(
        text,
        start_index=end_index,
        direction=1,
    )
    outside_before = (
        text[outside_before_index] if outside_before_index is not None else before
    )
    outside_after = (
        text[outside_after_index] if outside_after_index is not None else after
    )
    if _field_boundary_is_ambiguous(
        outside_before,
        side="before",
        allow_declaration_colon=(
            outside_before == ":"
            and outside_before_index is not None
            and outside_before_index < start_index - 1
        ),
    ) or (
        _field_boundary_is_ambiguous(
            outside_after,
            side="after",
            text=text,
            index=(
                outside_after_index if outside_after_index is not None else end_index
            ),
            adjacent_to_name=outside_after_index == end_index,
        )
    ):
        return None
    return "unquoted"


def _nearest_non_whitespace_index(
    text: str,
    *,
    start_index: int,
    direction: Literal[-1, 1],
) -> int | None:
    index = start_index
    while 0 <= index < len(text):
        if not text[index].isspace():
            return index
        index += direction
    return None


def _field_outer_boundary_index(
    text: str,
    *,
    start_index: int,
    direction: Literal[-1, 1],
) -> int | None:
    if not 0 <= start_index < len(text):
        return None
    if not text[start_index].isspace():
        return start_index
    nearest = _nearest_non_whitespace_index(
        text,
        start_index=start_index,
        direction=direction,
    )
    if nearest is None or text[nearest] not in _FIELD_STRUCTURAL_BOUNDARIES:
        return None
    return nearest


def _field_boundary_is_ambiguous(
    value: str | None,
    *,
    side: Literal["before", "after"],
    text: str = "",
    index: int = 0,
    allow_declaration_colon: bool = False,
    adjacent_to_name: bool = False,
) -> bool:
    if value is None:
        return False
    if _is_identifier_continuation(value):
        return True
    if value in _FIELD_STRUCTURAL_BOUNDARIES - {".", ":"}:
        return True
    if value == ":":
        return side == "after" or not allow_declaration_colon
    if value != ".":
        return False
    if side == "before":
        return True
    if adjacent_to_name:
        # A period hugging the name is a dotted path only when the child
        # segment hugs it too ("user.id"). "routing_issues[]. Bevara" ends a
        # sentence, whatever character starts the next one.
        return index + 1 < len(text) and _is_identifier_continuation(text[index + 1])
    # A period separated from the name by whitespace ('"id" . child') is a
    # spaced path when an identifier follows it.
    next_index = _nearest_non_whitespace_index(
        text,
        start_index=index + 1,
        direction=1,
    )
    return next_index is not None and _is_identifier_continuation(text[next_index])


def _is_identifier_continuation(value: str) -> bool:
    category = unicodedata.category(value)
    return category[0] in {"L", "M", "N", "S"} or category in {"Pc", "Pd", "Cf"}


def _is_quotation_mark(value: str) -> bool:
    return value in {'"', "'", "`"} or unicodedata.category(value) in {"Pi", "Pf"}


def _quotation_marks_form_pair(before: str, after: str) -> bool:
    if before == after:
        return True
    if before in {'"', "'", "`"} or after in {'"', "'", "`"}:
        return False
    return unicodedata.category(before) == "Pi" and unicodedata.category(after) == "Pf"


def _parse_schema_direction(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
    candidate_fingerprints: tuple[str, ...],
) -> ClassifiedSchemaDirection | None:
    if not isinstance(raw_value, dict) or not candidate_fingerprints:
        return None
    raw = cast(dict[str, Any], raw_value)
    input_fingerprint = raw.get("input_fingerprint")
    output_fingerprint = raw.get("output_fingerprint")
    reference_only = raw.get("reference_only")
    confidence = raw.get("confidence")
    reason = raw.get("reason")
    evidence = _parse_classification_evidence(
        raw.get("evidence", []),
        classification_input=classification_input,
    )
    if input_fingerprint is not None and not isinstance(input_fingerprint, str):
        return None
    if output_fingerprint is not None and not isinstance(output_fingerprint, str):
        return None
    if not isinstance(reference_only, bool):
        return None
    if reference_only:
        if input_fingerprint is not None or output_fingerprint is not None:
            return None
    elif input_fingerprint is None and output_fingerprint is None:
        return None
    current_fingerprints = frozenset(candidate_fingerprints)
    if any(
        fingerprint not in current_fingerprints
        for fingerprint in (input_fingerprint, output_fingerprint)
        if fingerprint is not None
    ):
        return None
    if confidence not in {"high", "medium", "low"}:
        return None
    confidence_value = cast(SlotClassificationConfidence, confidence)
    source_kinds_by_id: dict[str, SlotClassificationSourceKind] = {
        source.source_id: source.kind for source in classification_input.sources
    }
    if confidence_value != "low" and not (
        evidence
        and classification_evidence_has_user_owned_source(
            (item.source_id for item in evidence),
            source_kinds_by_id=source_kinds_by_id,
        )
    ):
        confidence_value = "low"
    return ClassifiedSchemaDirection(
        candidate_fingerprints=candidate_fingerprints,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        reference_only=reference_only,
        confidence=confidence_value,
        reason=(
            reason.strip()
            if isinstance(reason, str) and reason.strip()
            else "schema direction classification"
        ),
        evidence=evidence,
    )


def _parse_file_roles(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
) -> tuple[ClassifiedFileRole, ...]:
    if not isinstance(raw_value, list):
        return ()
    allowed_roles = set(get_args(FileRole))
    roles: list[ClassifiedFileRole] = []
    seen_file_ids: set[UUID] = set()
    for item in cast(list[object], raw_value):
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        file_id_raw = item_dict.get("file_id")
        role = item_dict.get("role")
        confidence = item_dict.get("confidence")
        reason = item_dict.get("reason")
        evidence = _parse_classification_evidence(
            item_dict.get("evidence", []),
            classification_input=classification_input,
        )
        raw_evidence_level = item_dict.get("evidence_level", "inferred")
        if not isinstance(file_id_raw, str):
            continue
        try:
            file_id = UUID(file_id_raw)
        except ValueError:
            continue
        if file_id in seen_file_ids:
            continue
        if file_id not in _classification_file_ids(classification_input):
            continue
        if role not in allowed_roles:
            continue
        if confidence not in {"high", "medium", "low"}:
            continue
        evidence = _file_role_evidence(
            evidence,
            file_id=file_id,
            classification_input=classification_input,
        )
        evidence_level = _validated_evidence_level(
            raw_evidence_level,
            evidence,
            classification_input=classification_input,
            structured_question_id=None,
        )
        role_value = cast(FileRole, role)
        confidence_value = cast(SlotClassificationConfidence, confidence)
        roles.append(
            ClassifiedFileRole(
                file_id=file_id,
                role=role_value,
                confidence=_downgrade_unsupported_confidence(
                    confidence_value,
                    evidence,
                ),
                reason=reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "file role classification",
                evidence=evidence,
                evidence_level=evidence_level,
            )
        )
        seen_file_ids.add(file_id)
    return tuple(roles)


def _file_role_evidence(
    evidence: tuple[ClassifiedEvidence, ...],
    *,
    file_id: UUID,
    classification_input: SlotClassificationInput,
) -> tuple[ClassifiedEvidence, ...]:
    sources_by_id = {
        source.source_id: source for source in classification_input.sources
    }
    return tuple(
        item
        for item in evidence
        if (
            sources_by_id[item.source_id].kind != "uploaded_file"
            or (
                sources_by_id[item.source_id].file_id == file_id
                and sources_by_id[item.source_id].coverage != "inventory_only"
            )
        )
    )


def _parse_form_intake(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
) -> ClassifiedFormIntake | None:
    if not isinstance(raw_value, dict):
        return None
    item_dict = cast(dict[str, Any], raw_value)
    needs_form_fields = item_dict.get("needs_form_fields")
    sectioned_form_intake = item_dict.get("sectioned_form_intake")
    confidence = item_dict.get("confidence")
    reason = item_dict.get("reason")
    evidence = _parse_classification_evidence(
        item_dict.get("evidence", []),
        classification_input=classification_input,
    )
    evidence_level = _validated_evidence_level(
        item_dict.get("evidence_level", "inferred"),
        evidence,
        classification_input=classification_input,
        structured_question_id="form_intake_pattern",
    )
    if not isinstance(needs_form_fields, bool) or not isinstance(
        sectioned_form_intake,
        bool,
    ):
        return None
    if not needs_form_fields and not sectioned_form_intake:
        return None
    if confidence not in {"high", "medium", "low"}:
        return None
    confidence_value = cast(SlotClassificationConfidence, confidence)
    return ClassifiedFormIntake(
        needs_form_fields=needs_form_fields or sectioned_form_intake,
        sectioned_form_intake=sectioned_form_intake,
        confidence=_downgrade_unsupported_confidence(confidence_value, evidence),
        reason=reason.strip()
        if isinstance(reason, str) and reason.strip()
        else "form intake classification",
        evidence=evidence,
        evidence_level=evidence_level,
    )


def _parse_classification_evidence(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
    max_items: int = CLASSIFICATION_EVIDENCE_MAX_ITEMS,
) -> tuple[ClassifiedEvidence, ...]:
    if not isinstance(raw_value, list):
        return ()

    sources_by_id = {
        source.source_id: source for source in classification_input.sources
    }
    evidence: list[ClassifiedEvidence] = []
    seen: set[tuple[str, str]] = set()
    for item in cast(list[object], raw_value):
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, object], item)
        source_id = item_dict.get("source_id")
        quote = item_dict.get("quote")
        if not isinstance(source_id, str) or not isinstance(quote, str):
            continue
        source_id = source_id.strip()
        quote = quote.strip()
        source = sources_by_id.get(source_id)
        if (
            source is None
            or not quote
            or len(quote) > CLASSIFICATION_EVIDENCE_MAX_LENGTH
            or quote not in source.text
            or (source_id, quote) in seen
        ):
            continue
        evidence.append(ClassifiedEvidence(source_id=source_id, quote=quote))
        seen.add((source_id, quote))
        if len(evidence) >= max_items:
            break
    return tuple(evidence)


def _parse_example_output_constraints(
    raw_value: object,
    *,
    classification_input: SlotClassificationInput,
    file_roles: tuple[ClassifiedFileRole, ...],
) -> ExampleOutputConstraintEvidence | None:
    if not isinstance(raw_value, dict):
        return None
    raw = cast(dict[str, object], raw_value)
    source_file_ids = _parse_example_output_source_file_ids(raw.get("source_file_ids"))
    if source_file_ids is None:
        return None
    roles_by_file_id = {item.file_id: item for item in file_roles}
    if any(
        (role := roles_by_file_id.get(file_id)) is None
        or role.role != "example_output"
        or role.confidence == "low"
        for file_id in source_file_ids
    ):
        return None

    evidence = _parse_classification_evidence(
        raw.get("evidence", []),
        classification_input=classification_input,
        max_items=EXAMPLE_OUTPUT_CITATIONS_MAX_ITEMS,
    )
    sources_by_id = {
        source.source_id: source for source in classification_input.sources
    }
    uploaded_sources_by_file_id = {
        source.file_id: source
        for source in classification_input.sources
        if source.kind == "uploaded_file" and source.file_id is not None
    }
    if any(
        (source := uploaded_sources_by_file_id.get(file_id)) is None
        or source.coverage == "inventory_only"
        or not any(item.source_id == source.source_id for item in evidence)
        for file_id in source_file_ids
    ):
        return None
    if any(
        (source := sources_by_id[item.source_id]).kind == "uploaded_file"
        and source.file_id not in source_file_ids
        for item in evidence
    ):
        return None

    confidence = raw.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        return None
    if confidence == "high" and not any(
        sources_by_id[item.source_id].kind != "uploaded_file" for item in evidence
    ):
        confidence = "medium"
    try:
        return ExampleOutputConstraintEvidence.model_validate(
            {
                "source_file_ids": sorted(source_file_ids, key=str),
                "source_coverage": [
                    {
                        "file_id": str(file_id),
                        "coverage": uploaded_sources_by_file_id[file_id].coverage,
                    }
                    for file_id in sorted(source_file_ids, key=str)
                ],
                "headings": raw.get("headings", []),
                "style_constraints": raw.get("style_constraints", []),
                "confidence": confidence,
                "citations": [
                    {
                        "source_id": item.source_id,
                        "file_id": sources_by_id[item.source_id].file_id,
                        "quote": item.quote,
                    }
                    for item in evidence
                ],
            }
        )
    except ValidationError:
        return None


def _parse_example_output_source_file_ids(
    raw_value: object,
) -> tuple[UUID, ...] | None:
    if not isinstance(raw_value, list) or not raw_value:
        return None
    parsed: list[UUID] = []
    for raw_file_id in cast(list[object], raw_value):
        if not isinstance(raw_file_id, str):
            return None
        try:
            file_id = UUID(raw_file_id)
        except ValueError:
            return None
        if file_id in parsed:
            return None
        parsed.append(file_id)
        if len(parsed) > 100:
            return None
    return tuple(parsed)


def _validated_evidence_level(
    raw_value: object,
    evidence: tuple[ClassifiedEvidence, ...],
    *,
    classification_input: SlotClassificationInput,
    structured_question_id: str | None,
) -> SlotClassificationEvidenceLevel:
    if raw_value != "explicit":
        return "inferred"
    sources_by_id = {
        source.source_id: source for source in classification_input.sources
    }
    for item in evidence:
        source = sources_by_id[item.source_id]
        if source.kind == "user_message" and source.question_id is None:
            return "explicit"
        if (
            source.kind in {"user_message", "structured_answer"}
            and structured_question_id is not None
            and source.question_id is not None
            and canonical_question_id(source.question_id)
            == canonical_question_id(structured_question_id)
        ):
            return "explicit"
    return "inferred"


def _classification_file_ids(
    classification_input: SlotClassificationInput,
) -> frozenset[UUID]:
    return frozenset(
        source.file_id
        for source in classification_input.sources
        if source.kind == "uploaded_file" and source.file_id is not None
    )


def slot_classification_json_schema(
    allowed_slot_values: Mapping[str, Collection[str]],
    *,
    schema_candidate_fingerprints: Collection[str] = (),
) -> dict[str, object]:
    properties = _slot_classification_top_level_properties(
        allowed_slot_values,
        schema_candidate_fingerprints=schema_candidate_fingerprints,
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _slot_classification_top_level_properties(
    allowed_slot_values: Mapping[str, Collection[str]],
    *,
    schema_candidate_fingerprints: Collection[str] = (),
) -> dict[str, dict[str, object]]:
    normalized_values = normalize_slot_classification_values(allowed_slot_values)
    normalized_fingerprints = tuple(sorted(set(schema_candidate_fingerprints)))
    return {
        "slots": {
            "type": "array",
            "maxItems": len(normalized_values),
            "items": _slot_classification_slot_schema(normalized_values),
        },
        "file_roles": {
            "type": "array",
            "items": _classified_file_role_schema(),
        },
        "checkpoint_updates": {
            "type": "array",
            "maxItems": len(get_args(CheckpointProducerKind)),
            "items": _classified_checkpoint_update_schema(),
        },
        "form_intake": {
            "anyOf": [
                _classified_form_intake_schema(),
                {"type": "null"},
            ],
        },
        "named_result_evidence": {
            "anyOf": [
                _classified_named_result_evidence_schema(),
                {"type": "null"},
            ],
        },
        "example_output_constraints": {
            "anyOf": [
                _classified_example_output_constraints_schema(),
                {"type": "null"},
            ],
        },
        "schema_direction": {
            "anyOf": [
                *(
                    [_classified_schema_direction_schema(normalized_fingerprints)]
                    if normalized_fingerprints
                    else []
                ),
                {"type": "null"},
            ],
        },
        "secondary_obligations": {
            "type": "array",
            "maxItems": len(RESULT_OBLIGATION_VALUES),
            "items": {"type": "string", "enum": list(RESULT_OBLIGATION_VALUES)},
        },
        "assumptions": _classification_note_array_schema(),
        "contradictions": _classification_note_array_schema(),
    }


def _classified_named_result_evidence_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "operation",
            "names",
            "removed_names",
            "confidence",
            "reason",
            "evidence",
        ],
        "properties": {
            "operation": {"type": "string", "enum": ["update", "clear"]},
            "names": {
                "type": "array",
                "maxItems": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": CLASSIFICATION_EVIDENCE_MAX_LENGTH,
                },
            },
            "removed_names": {
                "type": "array",
                "maxItems": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": CLASSIFICATION_EVIDENCE_MAX_LENGTH,
                },
            },
            "confidence": _classification_confidence_schema(),
            "reason": _classification_reason_schema(),
            "evidence": _classification_evidence_array_schema(
                max_items=NAMED_RESULT_DELTA_CITATION_MAX_ITEMS
            ),
        },
    }


def _classified_schema_direction_schema(
    candidate_fingerprints: tuple[str, ...],
) -> dict[str, object]:
    nullable_fingerprint = {
        "anyOf": [
            {"type": "string", "enum": list(candidate_fingerprints)},
            {"type": "null"},
        ]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "input_fingerprint",
            "output_fingerprint",
            "reference_only",
            "confidence",
            "reason",
            "evidence",
        ],
        "properties": {
            "input_fingerprint": nullable_fingerprint,
            "output_fingerprint": nullable_fingerprint,
            "reference_only": {"type": "boolean"},
            "confidence": _classification_confidence_schema(),
            "reason": _classification_reason_schema(),
            "evidence": _classification_evidence_array_schema(),
        },
    }


def _slot_classification_slot_schema(
    allowed_slot_values: Mapping[str, Collection[str]],
) -> dict[str, object]:
    slot_variants = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "slot_name",
                "value",
                "confidence",
                "reason",
                "evidence",
                "evidence_level",
            ],
            "properties": {
                "slot_name": {"type": "string", "enum": [slot_name]},
                "value": {
                    "type": "string",
                    "enum": sorted({*values, UNKNOWN_SLOT_VALUE}),
                },
                "confidence": _classification_confidence_schema(),
                "reason": _classification_reason_schema(),
                "evidence": _classification_evidence_array_schema(),
                "evidence_level": _classification_evidence_level_schema(),
            },
        }
        for slot_name, values in sorted(allowed_slot_values.items())
    ]
    if not slot_variants:
        return {"type": "object", "additionalProperties": False}
    return {"anyOf": slot_variants}


def _classified_file_role_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "file_id",
            "role",
            "confidence",
            "reason",
            "evidence",
            "evidence_level",
        ],
        "properties": {
            "file_id": {"type": "string"},
            "role": {"type": "string", "enum": list(get_args(FileRole))},
            "confidence": _classification_confidence_schema(),
            "reason": _classification_reason_schema(),
            "evidence": _classification_evidence_array_schema(),
            "evidence_level": _classification_evidence_level_schema(),
        },
    }


def _classified_checkpoint_update_schema() -> dict[str, object]:
    producer_kind = {
        "type": "string",
        "enum": list(get_args(CheckpointProducerKind)),
    }
    common_properties: dict[str, object] = {
        "producer_kind": producer_kind,
        "confidence": {
            "type": "string",
            "enum": ["high", "medium"],
        },
        "reason": _classification_reason_schema(),
        "evidence": _classification_evidence_array_schema(),
    }
    return {
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "operation",
                    "producer_kind",
                    "mode",
                    "confidence",
                    "reason",
                    "evidence",
                ],
                "properties": {
                    "operation": {"type": "string", "enum": ["update"]},
                    **common_properties,
                    "mode": {
                        "type": "string",
                        "enum": [mode.value for mode in FlowStepReviewMode],
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "operation",
                    "producer_kind",
                    "confidence",
                    "reason",
                    "evidence",
                ],
                "properties": {
                    "operation": {"type": "string", "enum": ["clear"]},
                    **common_properties,
                    "mode": {"type": "null"},
                },
            },
        ]
    }


def _classified_form_intake_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "needs_form_fields",
            "sectioned_form_intake",
            "confidence",
            "reason",
            "evidence",
            "evidence_level",
        ],
        "properties": {
            "needs_form_fields": {"type": "boolean"},
            "sectioned_form_intake": {"type": "boolean"},
            "confidence": _classification_confidence_schema(),
            "reason": _classification_reason_schema(),
            "evidence": _classification_evidence_array_schema(),
            "evidence_level": _classification_evidence_level_schema(),
        },
    }


def _classified_example_output_constraints_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_file_ids",
            "headings",
            "style_constraints",
            "confidence",
            "evidence",
        ],
        "properties": {
            "source_file_ids": {
                "type": "array",
                "maxItems": 100,
                "items": {"type": "string"},
            },
            "headings": {
                "type": "array",
                "maxItems": EXAMPLE_OUTPUT_HEADINGS_MAX_ITEMS,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                },
            },
            "style_constraints": {
                "type": "array",
                "maxItems": EXAMPLE_OUTPUT_STYLE_CONSTRAINTS_MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category", "description"],
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": list(get_args(ExampleOutputStyleCategory)),
                        },
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 240,
                        },
                    },
                },
            },
            "confidence": _classification_confidence_schema(),
            "evidence": _classification_evidence_array_schema(
                max_items=EXAMPLE_OUTPUT_CITATIONS_MAX_ITEMS
            ),
        },
    }


def _classification_confidence_schema() -> dict[str, object]:
    return {"type": "string", "enum": ["high", "medium", "low"]}


def _classification_evidence_level_schema() -> dict[str, object]:
    return {"type": "string", "enum": ["explicit", "inferred"]}


def _classification_reason_schema() -> dict[str, object]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": CLASSIFICATION_REASON_MAX_LENGTH,
    }


def _classification_note_array_schema() -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": CLASSIFICATION_NOTES_MAX_ITEMS,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": CLASSIFICATION_NOTE_MAX_LENGTH,
        },
    }


def _classification_evidence_array_schema(
    *,
    max_items: int = CLASSIFICATION_EVIDENCE_MAX_ITEMS,
) -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": max_items,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_id", "quote"],
            "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "quote": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": CLASSIFICATION_EVIDENCE_MAX_LENGTH,
                },
            },
        },
    }


def _downgrade_unsupported_confidence(
    confidence: SlotClassificationConfidence,
    evidence: tuple[ClassifiedEvidence, ...],
) -> SlotClassificationConfidence:
    if evidence:
        return confidence
    return "low"


def _parse_secondary_obligations(raw_value: object) -> tuple[ResultObligation, ...]:
    if not isinstance(raw_value, list):
        return ()
    legal_values = set(RESULT_OBLIGATION_VALUES)
    values: list[ResultObligation] = []
    seen: set[str] = set()
    for item in cast(list[object], raw_value):
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value not in legal_values or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return tuple(values)


def normalize_slot_classification_values(
    allowed_slot_values: Mapping[str, Collection[str]],
) -> dict[str, frozenset[str]]:
    return {
        slot_name: frozenset(value for value in values if value)
        for slot_name, values in sorted(allowed_slot_values.items())
        if slot_name and values
    }
