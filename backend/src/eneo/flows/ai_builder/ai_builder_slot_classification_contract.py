"""Typed request, response, schema, and parsing contract for slot classification."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal, assert_never, cast, get_args
from uuid import UUID

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_new_step_models import MAX_STRUCTURED_FIELD_DEPTH
from eneo.flows.ai_builder.ai_builder_proposal_intent import fold_named_result_location
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_VALUES,
    ResultObligation,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    AttachmentCoverage,
    CheckpointProducerKind,
    ExactNamedResultPlacement,
    ExampleOutputConstraintEvidence,
    ExampleOutputStyleCategory,
    FileRole,
    NamedResultDeclaredShape,
    NamedResultPlacement,
    SlotEvidenceLevel,
    UnplacedNamedResultPlacement,
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
_CLASSIFICATION_SOURCE_KINDS: frozenset[str] = frozenset(
    get_args(SlotClassificationSourceKind)
)
_FIELD_STRUCTURAL_BOUNDARIES = frozenset(
    {"$", "@", "#", "/", "\\", ":", "[", "]", "{", "}", "."}
)
UNKNOWN_SLOT_VALUE = "unknown"
SLOT_CLASSIFICATION_SCHEMA_VERSION = 24
_DECLARED_SHAPE_BY_NOTATION: Mapping[str, NamedResultDeclaredShape] = {
    "[]": "array",
    "{}": "object",
}
CLASSIFICATION_EVIDENCE_MAX_ITEMS = 3
CLASSIFICATION_EVIDENCE_MAX_LENGTH = 240
CLASSIFICATION_REASON_MAX_LENGTH = 500
# One named-result delta may cite every sentence in which the user names
# result fields; each name keeps at most NAMED_RESULT_EVIDENCE_MAX_CITATIONS of
# those quotes as provenance. The prompt, the response schema and the parser
# share this bound, and a delta that exceeds it is a malformed delta rather than
# truncated, because a silently dropped quote leaves a name uncited.
NAMED_RESULT_DELTA_CITATION_MAX_ITEMS = 12
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


def user_owned_quoted_text_from_planning_reference(reference: str) -> str | None:
    """The user's own words from a reference, or nothing if they are not theirs.

    An attachment excerpt is cited exactly like a sentence the user wrote, so
    only the source kind separates them. A caller quoting words back to the
    person who wrote them needs that distinction; the rest of the decoding is
    identical, so both readers live here.
    """

    kind = _source_kind_of_planning_reference(reference)
    if kind is None or kind not in _USER_OWNED_CLASSIFICATION_SOURCE_KINDS:
        return None
    return quoted_text_from_planning_reference(reference)


def user_owned_quoted_texts_from_planning_references(
    references: Sequence[str],
) -> list[str]:
    """Every quote among these references that the user themselves supplied.

    There is deliberately no reader that returns every quote regardless of
    source: the callers that quote evidence back are addressing the person who
    wrote it, and an attachment excerpt read out as their own words is a
    misattribution rather than a stylistic slip.
    """

    return [
        text
        for reference in references
        for text in [user_owned_quoted_text_from_planning_reference(reference)]
        if text is not None
    ]


def first_user_owned_quoted_text(references: Sequence[str]) -> str | None:
    """The first quote among these references that the user supplied."""

    return next(
        iter(user_owned_quoted_texts_from_planning_references(references)), None
    )


def quoted_text_from_planning_reference(reference: str) -> str | None:
    """Return the cited words from a persisted evidence reference.

    The decoder lives beside `ClassifiedEvidence.planning_reference` so the
    encoding has one owner. A source id is `<kind>:<identity>` and the identity
    is not one segment for every kind, so the boundary is read from the kind
    rather than guessed: guessing leaked internal ids into user-facing
    remediation text (observed live 2026-08-06), and a hand-kept list of
    "compound" kinds drifted away from the kinds that actually exist.
    """

    kind = _source_kind_of_planning_reference(reference)
    if kind is None:
        return None
    remainder = reference.removeprefix("quote:").partition(":")[2]
    for _ in range(_source_identity_segment_count(kind)):
        _, separator, remainder = remainder.partition(":")
        if not separator:
            return None
    text = remainder.strip()
    return text or None


def _source_kind_of_planning_reference(
    reference: str,
) -> SlotClassificationSourceKind | None:
    if not reference.startswith("quote:"):
        return None
    kind, separator, _ = reference.removeprefix("quote:").partition(":")
    if not separator or kind not in _CLASSIFICATION_SOURCE_KINDS:
        return None
    return cast(SlotClassificationSourceKind, kind)


def _source_identity_segment_count(kind: SlotClassificationSourceKind) -> int:
    """How many colon-separated segments this kind's identity spends.

    Exhaustive on the kind, so adding a source kind fails type checking here
    instead of silently mis-splitting its quotes.
    """

    match kind:
        case "user_message" | "uploaded_file":
            return 1
        case "structured_answer":
            return 2
    assert_never(kind)


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
    evidence_level: SlotClassificationEvidenceLevel = "inferred"


@dataclass(frozen=True, slots=True)
class ClassifiedNamedResultEvidence:
    name: str
    evidence: tuple[ClassifiedEvidence, ...]
    placement: NamedResultPlacement = dataclass_field(
        default_factory=ExactNamedResultPlacement
    )
    declared_shape: NamedResultDeclaredShape | None = None

    @property
    def folded_exact_identity(self) -> tuple[str, ...] | None:
        if not isinstance(self.placement, ExactNamedResultPlacement):
            return None
        return fold_named_result_location(
            self.name,
            segments=self.placement.segments,
        )


@dataclass(frozen=True, slots=True)
class ClassifiedNamedResultDelta:
    operation: Literal["update", "clear"]
    upserts: tuple[ClassifiedNamedResultEvidence, ...]
    confidence: SlotClassificationConfidence
    reason: str
    removals: tuple[ClassifiedNamedResultEvidence, ...] = ()
    evidence: tuple[ClassifiedEvidence, ...] = ()

    def __post_init__(self) -> None:
        changed = (*self.upserts, *self.removals)
        if self.operation == "clear" and changed:
            raise ValueError("clear named-result delta must not carry locations")
        identities = tuple(_classified_named_result_identity(item) for item in changed)
        if len(identities) != len(set(identities)):
            raise ValueError(
                "named-result changes must have unique location identities"
            )
        allowed_evidence = set(self.evidence)
        if any(
            not item.evidence
            or any(citation not in allowed_evidence for citation in item.evidence)
            for item in changed
        ):
            raise ValueError(
                "named-result location citations must belong to delta evidence"
            )


def _classified_named_result_identity(
    item: ClassifiedNamedResultEvidence,
) -> tuple[str, ...]:
    identity = item.folded_exact_identity
    if identity is not None:
        return ("exact", *identity)
    return ("unplaced", *fold_named_result_location(item.name))


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
    raw_upserts = item.get("upserts")
    raw_removals = item.get("removals")
    if not isinstance(raw_upserts, list) or not isinstance(raw_removals, list):
        raise _MalformedNamedResultDelta
    raw_upsert_items = cast(list[object], raw_upserts)
    raw_removal_items = cast(list[object], raw_removals)
    if operation == "update" and not (raw_upsert_items or raw_removal_items):
        raise _MalformedNamedResultDelta
    if operation == "clear" and (raw_upsert_items or raw_removal_items):
        raise _MalformedNamedResultDelta
    confidence = item.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        raise _MalformedNamedResultDelta
    cited_items = item.get("evidence", [])
    if (
        isinstance(cited_items, list)
        and len(cast(list[object], cited_items)) > NAMED_RESULT_DELTA_CITATION_MAX_ITEMS
    ):
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
    upserts = _parse_cited_named_result_locations(
        raw_upsert_items,
        allowed_evidence=user_owned_evidence,
        classification_input=classification_input,
        source_texts=source_texts,
    )
    removals = _parse_cited_named_result_locations(
        raw_removal_items,
        allowed_evidence=user_owned_evidence,
        classification_input=classification_input,
        source_texts=source_texts,
        require_placement_evidence=False,
        require_removal_intent=True,
    )
    if upserts is None or removals is None:
        return None
    identities = [
        _classified_named_result_identity(changed) for changed in (*upserts, *removals)
    ]
    if (
        any(not identity[-1] for identity in identities)
        or len(identities) != len(set(identities))
        or len(identities) > NAMED_RESULT_EVIDENCE_MAX_ITEMS
    ):
        return None
    reason = item.get("reason")
    return ClassifiedNamedResultDelta(
        operation=cast(Literal["update", "clear"], operation),
        upserts=upserts,
        confidence=cast(SlotClassificationConfidence, confidence),
        reason=(
            reason.strip()
            if isinstance(reason, str) and reason.strip()
            else "named-result classification"
        ),
        removals=removals,
        evidence=user_owned_evidence,
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
                evidence_level=_validated_evidence_level(
                    payload.get("evidence_level", "inferred"),
                    evidence,
                    classification_input=classification_input,
                    structured_question_id=None,
                ),
            )
        )
    return tuple(updates)


def _parse_cited_named_result_locations(
    raw_locations: list[object],
    *,
    allowed_evidence: tuple[ClassifiedEvidence, ...],
    classification_input: SlotClassificationInput,
    source_texts: Mapping[str, str],
    require_placement_evidence: bool = True,
    require_removal_intent: bool = False,
) -> tuple[ClassifiedNamedResultEvidence, ...] | None:
    locations: list[ClassifiedNamedResultEvidence] = []
    allowed_evidence_set = set(allowed_evidence)
    for raw_location in raw_locations:
        if not isinstance(raw_location, dict):
            return None
        payload = cast(dict[str, object], raw_location)
        raw_name = payload.get("name")
        explicitly_unplaced = payload.get("unplaced") is True
        has_segments = "segments" in payload
        raw_segments = payload.get("segments")
        if not isinstance(raw_name, str) or not raw_name:
            return None
        if explicitly_unplaced:
            if has_segments or set(payload) != {"name", "unplaced", "evidence"}:
                return None
            segments: list[str] = []
        elif (
            payload.get("unplaced") is not None
            or not has_segments
            or set(payload) != {"name", "segments", "evidence"}
            or not isinstance(raw_segments, list)
            or any(
                not isinstance(segment, str) or not segment
                for segment in cast(list[object], raw_segments)
            )
        ):
            return None
        else:
            segments = cast(list[str], raw_segments)
        evidence = _parse_classification_evidence(
            payload.get("evidence", []),
            classification_input=classification_input,
            max_items=NAMED_RESULT_DELTA_CITATION_MAX_ITEMS,
        )
        if not evidence or any(
            citation not in allowed_evidence_set for citation in evidence
        ):
            return None
        named_evidence = _cited_named_result_evidence(
            raw_name,
            evidence=evidence,
            source_texts=source_texts,
        )
        if named_evidence is None:
            return None
        if require_removal_intent and not _named_result_removal_has_attestation(
            name=named_evidence.name,
            evidence=named_evidence.evidence,
            source_texts=source_texts,
        ):
            return None
        if explicitly_unplaced:
            locations.append(
                ClassifiedNamedResultEvidence(
                    name=named_evidence.name,
                    placement=UnplacedNamedResultPlacement(),
                    evidence=named_evidence.evidence,
                    declared_shape=named_evidence.declared_shape,
                )
            )
            continue
        normalized_segments: list[str] = []
        for segment in segments:
            segment_evidence = _cited_named_result_evidence(
                segment,
                evidence=evidence,
                source_texts=source_texts,
            )
            if segment_evidence is None:
                normalized_segments = []
                break
            normalized_segments.append(segment_evidence.name)
        requested_components = (*normalized_segments, named_evidence.name)
        placement: NamedResultPlacement
        # A removal names an EXISTING location: its full folded identity is
        # what selects the entry to remove, and the evidence proves the
        # user asked for the removal — placement was attested when the
        # entry was admitted, so it is not re-attested here.
        exact_supported = len(normalized_segments) == len(segments) and (
            True
            if not require_placement_evidence
            else _named_result_root_has_attestation(
                name=named_evidence.name,
                evidence=named_evidence.evidence,
                source_texts=source_texts,
            )
            if not normalized_segments
            else all(
                _named_result_edge_has_contiguous_evidence(
                    parent=parent,
                    child=child,
                    evidence=evidence,
                    source_texts=source_texts,
                )
                for parent, child in zip(requested_components, requested_components[1:])
            )
        )
        if exact_supported:
            placement = ExactNamedResultPlacement(segments=tuple(normalized_segments))
        else:
            placement = UnplacedNamedResultPlacement()
        locations.append(
            ClassifiedNamedResultEvidence(
                name=named_evidence.name,
                placement=placement,
                evidence=named_evidence.evidence,
                declared_shape=named_evidence.declared_shape,
            )
        )
    return tuple(locations)


def _named_result_edge_has_contiguous_evidence(
    *,
    parent: str,
    child: str,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> bool:
    for cited in evidence:
        parent_occurrences = _cited_field_occurrences(
            source_text=source_texts[cited.source_id],
            quote=cited.quote,
            field_name=parent,
        )
        child_occurrences = _cited_field_occurrences(
            source_text=source_texts[cited.source_id],
            quote=cited.quote,
            field_name=child,
        )
        if (
            parent_occurrences
            and child_occurrences
            and _spans_attest_named_result_edge(
                source_texts[cited.source_id],
                parent_occurrences=parent_occurrences,
                child_occurrences=child_occurrences,
            )
        ):
            return True
    return False


_REMOVAL_PREFIX_MARKERS = (
    "remove",
    "delete",
    "drop",
    "skip",
    "ta bort",
    "inte längre",
    "skippa",
)
# Generic, context-free negation vocabulary. Contractions are recognized
# structurally (any normalized token ending in "n't"), never enumerated.
# "utan"/"inte längre" have removal-specific meanings handled ONLY inside
# the removal attestation — the generic owner stays context-free.
_NEGATION_WORDS = frozenset(
    {"not", "never", "no", "cannot", "without", "inte", "aldrig", "ej", "utan"}
)
_REMOVAL_IDIOM = "inte längre"
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "\u2032": "'"})


def _negation_tokens(text: str) -> list[str]:
    normalized = text.translate(_APOSTROPHES)
    return [part.strip("[]{}.,:;!?()\"'").casefold() for part in normalized.split()]


def _token_negates(token: str) -> bool:
    return token in _NEGATION_WORDS or token.endswith("n't")


def _text_has_negation(text: str) -> bool:
    return any(_token_negates(token) for token in _negation_tokens(text))


def _placement_negated(source_text: str, occurrence: _FieldOccurrence) -> bool:
    """Strictly conservative: ANY negation in the clause demotes.

    Token rules cannot own natural-language scope; the design's safe state
    is demotion — Unplaced resolves through the card's placement
    affordance, while a falsely admitted location becomes a wrong
    obligation. Deliberate cost: "JSON contains timestamp but not status"
    demotes timestamp too (the user re-places it in one click).
    """

    clause_start, clause_end = _occurrence_clause_bounds(source_text, occurrence)
    return _text_has_negation(source_text[clause_start:clause_end])


def _named_result_removal_has_attestation(
    *,
    name: str,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> bool:
    for cited in evidence:
        source_text = source_texts[cited.source_id]
        occurrences = _cited_field_occurrences(
            source_text=source_text,
            quote=cited.quote,
            field_name=name,
        )
        for occurrence in occurrences:
            clause_start, clause_end = _occurrence_clause_bounds(
                source_text,
                occurrence,
            )
            after = source_text[occurrence.end_index : clause_end].casefold()
            # "{name} inte längre" is the one idiom kept: its span is
            # anchored to the name and unambiguous. Suppress exactly that
            # matched span, then demand the rest of the clause be
            # negation-free.
            idiom = re.match(r"\s+inte\s+längre(?:\W|$)", after)
            before = source_text[clause_start : occurrence.start_index].casefold()
            if idiom is not None:
                remainder = before + after[idiom.end() :]
                if not _text_has_negation(remainder):
                    return True
                continue
            # Strictly conservative otherwise: any negation in the clause
            # (prohibitions, "utan att ta bort", modal negatives) rejects;
            # a missed removal is recoverable on the card, a false removal
            # deletes user state.
            if _text_has_negation(source_text[clause_start:clause_end]):
                continue
            if _prefix_attests_removal(before):
                return True
    return False


def _prefix_attests_removal(text: str) -> bool:
    for marker in _REMOVAL_PREFIX_MARKERS:
        for marker_match in re.finditer(
            rf"(?<!\w){re.escape(marker)}(?!\w)",
            text,
        ):
            suffix = text[marker_match.end() :]
            if re.fullmatch(
                r"(?:\s+[\w-]+(?:\[\]|\{\})?\.)*\s*",
                suffix,
            ):
                return True
    return False


def _occurrence_clause_bounds(
    source_text: str,
    occurrence: _FieldOccurrence,
) -> tuple[int, int]:
    clause_start = occurrence.citation_start_index
    for index in range(occurrence.citation_start_index, occurrence.start_index):
        if source_text[index] in _CLAUSE_DELIMITERS and not (
            source_text[index] == "." and _is_direct_path_separator(source_text, index)
        ):
            clause_start = index + 1
    clause_end = occurrence.citation_end_index
    for index in range(occurrence.end_index, occurrence.citation_end_index):
        if source_text[index] in _CLAUSE_DELIMITERS and not (
            source_text[index] == "." and _is_direct_path_separator(source_text, index)
        ):
            clause_end = index
            break
    return clause_start, clause_end


def _is_direct_path_separator(text: str, index: int) -> bool:
    return (
        index >= 2
        and text[index - 2 : index] in {"[]", "{}"}
        and index + 1 < len(text)
        and _is_identifier_continuation(text[index + 1])
    )


def _spans_attest_named_result_edge(
    source_text: str,
    *,
    parent_occurrences: frozenset[_FieldOccurrence],
    child_occurrences: frozenset[_FieldOccurrence],
) -> bool:
    for parent_occurrence in parent_occurrences:
        for child_occurrence in child_occurrences:
            if not _occurrences_share_citation(
                parent_occurrence,
                child_occurrence,
            ):
                continue
            later = (
                child_occurrence
                if parent_occurrence.start_index <= child_occurrence.start_index
                else parent_occurrence
            )
            if _placement_negated(source_text, later):
                continue
            if parent_occurrence.end_index <= child_occurrence.start_index:
                between = source_text[
                    parent_occurrence.end_index : child_occurrence.start_index
                ]
                if _is_direct_named_result_path(between) or _has_positive_edge_marker(
                    between,
                    markers=_PARENT_BEFORE_CHILD_EDGE_MARKERS,
                ):
                    return True
            elif child_occurrence.end_index <= parent_occurrence.start_index and (
                _has_positive_edge_marker(
                    source_text[
                        child_occurrence.end_index : parent_occurrence.start_index
                    ],
                    markers=_CHILD_BEFORE_PARENT_EDGE_MARKERS,
                )
            ):
                return True
    return False


def _occurrences_share_citation(
    first: _FieldOccurrence,
    second: _FieldOccurrence,
) -> bool:
    return (
        first.citation_start_index == second.citation_start_index
        and first.citation_end_index == second.citation_end_index
    )


_ROOT_ARTIFACT_NAMES = (
    "json output field",
    "json-resultatet",
    "json",
    "output",
    "report",
    "response",
    "result",
    "rapport",
    "resultat",
    "utdata",
)


def _named_result_root_has_attestation(
    *,
    name: str,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> bool:
    for cited in evidence:
        source_text = source_texts[cited.source_id]
        name_occurrences = _cited_field_occurrences(
            source_text=source_text,
            quote=cited.quote,
            field_name=name,
        )
        if not name_occurrences:
            continue
        root_occurrences = frozenset(
            occurrence
            for artifact_name in _ROOT_ARTIFACT_NAMES
            for occurrence in _cited_field_occurrences(
                source_text=source_text,
                quote=cited.quote,
                field_name=artifact_name,
            )
        )
        for root_occurrence in root_occurrences:
            for name_occurrence in name_occurrences:
                if (
                    _occurrences_share_citation(root_occurrence, name_occurrence)
                    and root_occurrence.end_index <= name_occurrence.start_index
                    and not _placement_negated(source_text, name_occurrence)
                    and _has_positive_root_marker(
                        source_text[
                            root_occurrence.end_index : name_occurrence.start_index
                        ]
                    )
                ):
                    return True
    return False


_PARENT_BEFORE_CHILD_EDGE_MARKERS = (
    "contains",
    "contain",
    "includes",
    "include",
    "ska innehålla",
    "innehåller",
)
_CHILD_BEFORE_PARENT_EDGE_MARKERS = (
    "belongs directly to",
    "belongs directly under",
    "belongs to",
    "directly under",
    "ligger direkt under",
    "hör direkt till",
    "tillhör",
)
_ROOT_CONNECTORS = (
    *_PARENT_BEFORE_CHILD_EDGE_MARKERS,
    "med",
    "with",
    "field:",
    ":",
)
_CLAUSE_DELIMITERS = ".;!?"
_EDGE_DETERMINERS = frozenset({"a", "an", "the", "en", "ett", "den", "det", "de"})


def _has_positive_edge_marker(text: str, *, markers: Sequence[str]) -> bool:
    # The entire span between the two names must be the relationship
    # statement itself — a bounded positive template, never a sentence
    # fragment that happens to contain a marker somewhere.
    span = " ".join(text.strip().split())
    # A shape token adjacent to a name mention ("candidate_passages[]")
    # belongs to the mention, not to the relationship statement.
    for shape_token in ("[]", "{}"):
        if span.startswith(shape_token):
            span = span[len(shape_token) :].lstrip()
        if span.endswith(shape_token):
            span = span[: -len(shape_token)].rstrip()
    if any(delimiter in span for delimiter in _CLAUSE_DELIMITERS) or "," in span:
        return False
    if _has_relationship_negation(span):
        return False
    words = span.split()
    for marker in markers:
        marker_words = marker.split()
        if words == marker_words:
            return True
        if (
            len(words) == len(marker_words) + 1
            and words[: len(marker_words)] == marker_words
            and words[-1] in _EDGE_DETERMINERS
        ):
            return True
    return False


def _has_positive_root_marker(text: str) -> bool:
    span = " ".join(text.casefold().strip().split())
    if any(delimiter in span for delimiter in _CLAUSE_DELIMITERS):
        return False
    if _has_relationship_negation(span):
        return False
    for marker in _ROOT_CONNECTORS:
        if span == marker:
            return True
        marker_prefix = f"{marker} "
        if span.startswith(marker_prefix) and _root_list_prefix_is_bounded(
            span[len(marker_prefix) :]
        ):
            return True
    return False


def _root_list_prefix_is_bounded(text: str) -> bool:
    tokens = text.replace(",", " , ").split()
    if not tokens:
        return True
    index = 0
    while index < len(tokens):
        if tokens[index] in _EDGE_DETERMINERS:
            index += 1
            if index == len(tokens):
                return True
        if (
            index == len(tokens)
            or re.fullmatch(r"[\w-]+(?:\[\]|\{\})?", tokens[index]) is None
        ):
            return False
        index += 1
        if index == len(tokens) or tokens[index] not in {",", "and", "och"}:
            return False
        index += 1
    return True


def _has_relationship_negation(text: str) -> bool:
    return _text_has_negation(text)


def _is_direct_named_result_path(text: str) -> bool:
    return text.strip() in {"[].", "{}."}


def _cited_named_result_evidence(
    raw_name: str,
    *,
    evidence: tuple[ClassifiedEvidence, ...],
    source_texts: Mapping[str, str],
) -> ClassifiedNamedResultEvidence | None:
    cited_occurrences: list[tuple[ClassifiedEvidence, frozenset[_FieldOccurrence]]] = []
    for cited in evidence:
        occurrences = _cited_field_occurrences(
            source_text=source_texts[cited.source_id],
            quote=cited.quote,
            field_name=raw_name,
        )
        if occurrences:
            cited_occurrences.append((cited, occurrences))
    occurrences = {occurrence for _, found in cited_occurrences for occurrence in found}
    occurrence_kinds = {occurrence.kind for occurrence in occurrences}
    if occurrence_kinds == {"quoted"}:
        # A quoted mention is a literal key: its brackets are part of the name
        # the user asked for, not a shape declaration.
        name = raw_name
        declared_shape: NamedResultDeclaredShape | None = None
    elif occurrence_kinds == {"unquoted"}:
        phrase = raw_name
        while phrase.endswith(("[]", "{}")):
            phrase = phrase[:-2]
        normalized = _normalize_unquoted_named_result_name(phrase)
        if normalized is None:
            return None
        name = normalized
        # The shape is read from this name's own validated occurrences and
        # nothing else, so every declared_shape is backed by a citation this
        # name actually carries.
        #
        # RESIDUAL: that scope is the model's exact spelling, so a shape
        # declared for the same field under a different spelling is invisible
        # here. `case-id[]` in one sentence and `case id{}` in another fold to
        # one identity, and a name classified as `case-id[]` sees only the
        # array. Detecting it needs a per-name citation contract the model does
        # not emit today; indexing the delta by fold was tried and dropped,
        # because it attached a shape whose citation the name never carried.
        # Left as a documented residual until measured evidence justifies the
        # richer contract.
        declared: set[NamedResultDeclaredShape] = {
            shape
            for occurrence in occurrences
            if (shape := occurrence.declared_shape) is not None
        }
        if len(declared) > 1:
            # This name's own citations declared two shapes. Picking either
            # would invent a contract, and dropping the shape would commit the
            # rest of the delta on evidence the server could not read. The
            # delta is atomic: reject it and keep the prior state.
            return None
        declared_shape = next(iter(declared), None)
    else:
        return None
    return ClassifiedNamedResultEvidence(
        name=name,
        evidence=tuple(cited for cited, _ in cited_occurrences),
        declared_shape=declared_shape,
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


def _cited_field_occurrences(
    *,
    source_text: str,
    quote: str,
    field_name: str,
) -> frozenset[_FieldOccurrence]:
    """Validate quoted field occurrences against their complete source context."""
    occurrences: set[_FieldOccurrence] = set()
    quote_start = 0
    while (quote_index := source_text.find(quote, quote_start)) >= 0:
        for field_match in re.finditer(re.escape(field_name), quote, re.IGNORECASE):
            field_index = field_match.start()
            absolute_start = quote_index + field_index
            occurrence = _valid_field_occurrence(
                source_text,
                start_index=absolute_start,
                end_index=absolute_start + len(field_name),
                citation_start_index=quote_index,
                citation_end_index=quote_index + len(quote),
            )
            if occurrence is not None:
                occurrences.add(occurrence)
        occurrences.update(
            _direct_path_field_occurrences(
                source_text=source_text,
                quote=quote,
                quote_index=quote_index,
                field_name=field_name,
            )
        )
        quote_start = quote_index + 1
    return frozenset(occurrences)


@dataclass(frozen=True, slots=True)
class _FieldOccurrence:
    """One validated literal mention of a field name in its source."""

    kind: Literal["quoted", "unquoted"]
    declared_shape: NamedResultDeclaredShape | None
    start_index: int
    end_index: int
    citation_start_index: int
    citation_end_index: int


_DIRECT_PATH_PATTERN = re.compile(
    r"(?<![\w-])(?:[\w-]+(?:\[\]|\{\})\.)+[\w-]+(?:\[\]|\{\})?(?![\w-])"
)
_DIRECT_PATH_COMPONENT_PATTERN = re.compile(r"(?P<name>[\w-]+)(?P<shape>\[\]|\{\})?")


def _direct_path_field_occurrences(
    *,
    source_text: str,
    quote: str,
    quote_index: int,
    field_name: str,
) -> frozenset[_FieldOccurrence]:
    occurrences: set[_FieldOccurrence] = set()
    folded_field_name = field_name.casefold()
    for path_match in _DIRECT_PATH_PATTERN.finditer(quote):
        absolute_path_start = quote_index + path_match.start()
        path_occurrence = _valid_field_occurrence(
            source_text,
            start_index=absolute_path_start,
            end_index=quote_index + path_match.end(),
            citation_start_index=quote_index,
            citation_end_index=quote_index + len(quote),
        )
        if path_occurrence is None or path_occurrence.kind != "unquoted":
            continue
        for component in _DIRECT_PATH_COMPONENT_PATTERN.finditer(path_match.group()):
            component_name = component.group("name")
            shape_notation = component.group("shape")
            if folded_field_name not in {
                component_name.casefold(),
                f"{component_name}{shape_notation or ''}".casefold(),
            }:
                continue
            component_start = absolute_path_start + component.start("name")
            occurrences.add(
                _FieldOccurrence(
                    kind="unquoted",
                    declared_shape=_DECLARED_SHAPE_BY_NOTATION.get(
                        shape_notation or ""
                    ),
                    start_index=component_start,
                    end_index=component_start + len(component_name),
                    citation_start_index=quote_index,
                    citation_end_index=quote_index + len(quote),
                )
            )
    return frozenset(occurrences)


def _valid_field_occurrence(
    text: str,
    *,
    start_index: int,
    end_index: int,
    citation_start_index: int,
    citation_end_index: int,
) -> _FieldOccurrence | None:
    before = text[start_index - 1] if start_index > 0 else None
    # A cited name may carry JSON shape notation in the source
    # ("applicant_channels[]"): the notation belongs to the mention, not
    # its boundary. The model may name the bare field and leave the notation
    # in the source, or repeat it in the name; either way the marker is the
    # user's literal writing. Judge the boundary after it.
    declared_shape = _DECLARED_SHAPE_BY_NOTATION.get(text[end_index : end_index + 2])
    consumed_source_notation = declared_shape is not None
    if consumed_source_notation:
        end_index += 2
    elif end_index - 2 >= start_index:
        declared_shape = _DECLARED_SHAPE_BY_NOTATION.get(
            text[end_index - 2 : end_index]
        )
    after = text[end_index] if end_index < len(text) else None
    before_is_quote = before is not None and _is_quotation_mark(before)
    after_is_quote = after is not None and _is_quotation_mark(after)
    if before_is_quote != after_is_quote:
        return None
    if before_is_quote and after_is_quote:
        assert before is not None and after is not None
        if not _quotation_marks_form_pair(before, after):
            return None
        if consumed_source_notation:
            # The closing quote was reached only by swallowing notation the
            # classified name leaves out: the user's literal key is
            # `"applicant_channels[]"`, and admitting it as
            # `applicant_channels` would rename it.
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
        return _FieldOccurrence(
            kind="quoted",
            declared_shape=None,
            start_index=start_index,
            end_index=end_index,
            citation_start_index=citation_start_index,
            citation_end_index=citation_end_index,
        )
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
    return _FieldOccurrence(
        kind="unquoted",
        declared_shape=declared_shape,
        start_index=start_index,
        end_index=end_index,
        citation_start_index=citation_start_index,
        citation_end_index=citation_end_index,
    )


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
            "upserts",
            "removals",
            "confidence",
            "reason",
            "evidence",
        ],
        "properties": {
            "operation": {"type": "string", "enum": ["update", "clear"]},
            "upserts": {
                "type": "array",
                "maxItems": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
                "items": _classified_named_result_location_schema(),
            },
            "removals": {
                "type": "array",
                "maxItems": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
                "items": _classified_named_result_location_schema(),
            },
            "confidence": _classification_confidence_schema(),
            "reason": _classification_reason_schema(),
            "evidence": _classification_evidence_array_schema(
                max_items=NAMED_RESULT_DELTA_CITATION_MAX_ITEMS
            ),
        },
    }


def _classified_named_result_location_schema() -> dict[str, object]:
    shared_properties = {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": CLASSIFICATION_EVIDENCE_MAX_LENGTH,
        },
        "evidence": _classification_evidence_array_schema(
            max_items=NAMED_RESULT_DELTA_CITATION_MAX_ITEMS
        ),
    }
    return {
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "segments", "evidence"],
                "properties": {
                    **shared_properties,
                    "segments": {
                        "type": "array",
                        "maxItems": MAX_STRUCTURED_FIELD_DEPTH - 1,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": CLASSIFICATION_EVIDENCE_MAX_LENGTH,
                        },
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "unplaced", "evidence"],
                "properties": {
                    **shared_properties,
                    "unplaced": {"type": "boolean", "enum": [True]},
                },
            },
        ]
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
        "evidence_level": _classification_evidence_level_schema(),
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
                    "evidence_level",
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
                    "evidence_level",
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
