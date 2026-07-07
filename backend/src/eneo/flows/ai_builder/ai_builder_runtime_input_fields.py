from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, TypeAlias, assert_never

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import BuilderFormFieldType
from eneo.flows.ai_builder.planning_state import SlotConfidence, SlotSource

RuntimeMetadataState: TypeAlias = Literal[
    "no_extra_metadata",
    "basic_case_metadata",
    "detailed_case_metadata",
]
NO_EXTRA_RUNTIME_METADATA: RuntimeMetadataState = "no_extra_metadata"
BASIC_CASE_METADATA: RuntimeMetadataState = "basic_case_metadata"
DETAILED_CASE_METADATA: RuntimeMetadataState = "detailed_case_metadata"
_RUNTIME_METADATA_STATES: frozenset[RuntimeMetadataState] = frozenset(
    (
        NO_EXTRA_RUNTIME_METADATA,
        BASIC_CASE_METADATA,
        DETAILED_CASE_METADATA,
    )
)
_RUNTIME_METADATA_STATES_ALLOWING_FIELDS: frozenset[RuntimeMetadataState] = frozenset(
    (
        BASIC_CASE_METADATA,
        DETAILED_CASE_METADATA,
    )
)


@dataclass(frozen=True, slots=True)
class RuntimeInputFieldHint:
    """A server-derived hint for fields users fill in when a flow runs."""

    variable_name: str
    label: str
    field_type: BuilderFormFieldType = "text"
    required: bool = False
    options: tuple[str, ...] = ()


_RUNTIME_FIELD_DECLARATION_TRIGGERS: tuple[str, ...] = (
    "inmatningsfält",
    "inmatningsfalt",
    "input fields",
    "input variables",
    "runtime fields",
    "fields at runtime",
    "form fields",
    "formulärfält",
    "formularfalt",
    "metadata fields",
    "fält vid körning",
    "falt vid korning",
)
_RUNTIME_METADATA_CONCEPT_TRIGGERS: tuple[str, ...] = (
    "basic metadata",
    "basic input fields",
    "basic form fields",
    "grundläggande metadata",
    "grundlaggande metadata",
    "grundläggande inmatningsfält",
    "grundlaggande inmatningsfalt",
)
_RUNTIME_METADATA_ABSENCE_TRIGGERS = (
    *_RUNTIME_FIELD_DECLARATION_TRIGGERS,
    *_RUNTIME_METADATA_CONCEPT_TRIGGERS,
    "extra fält",
    "extra falt",
    "extra fields",
    "metadatafält",
    "metadatafalt",
    "metadata",
)
_RUNTIME_METADATA_INTENT_TRIGGERS = (
    *_RUNTIME_FIELD_DECLARATION_TRIGGERS,
    *_RUNTIME_METADATA_CONCEPT_TRIGGERS,
)


def _english_action_phrase_forms(phrase: str) -> tuple[str, ...]:
    verb, sep, rest = phrase.partition(" ")
    return tuple(
        dict.fromkeys(
            f"{form}{sep}{rest}" if rest else form for form in _english_verb_forms(verb)
        )
    )


def _english_verb_forms(lemma: str) -> tuple[str, ...]:
    if lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
        stem = lemma[:-1]
        return (lemma, f"{stem}ies", f"{stem}ied", f"{lemma}ing")
    if lemma.endswith("e") and not lemma.endswith(("ee", "ye", "oe")):
        stem = lemma[:-1]
        return (lemma, f"{lemma}s", f"{lemma}d", f"{stem}ing")
    third_person = (
        f"{lemma}es" if lemma.endswith(("s", "x", "z", "ch", "sh")) else f"{lemma}s"
    )
    return (lemma, third_person, f"{lemma}ed", f"{lemma}ing")


_SWEDISH_USER_FIELD_ACTION_PHRASES: tuple[str, ...] = (
    "ange",
    "fylla i",
    "fyller i",
    "mata in",
    "lämna",
    "lamna",
    "uppge",
    "välja",
    "valja",
    "specificera",
    "skriva in",
)
_ENGLISH_USER_FIELD_ACTION_LEMMAS: tuple[str, ...] = (
    "enter",
    "provide",
    "fill in",
    "select",
    "specify",
    "supply",
    "type in",
)
_ENGLISH_USER_FIELD_ACTION_PHRASES: tuple[str, ...] = tuple(
    form
    for phrase in _ENGLISH_USER_FIELD_ACTION_LEMMAS
    for form in _english_action_phrase_forms(phrase)
)
_USER_FIELD_ACTION_PHRASES: tuple[str, ...] = (
    *_SWEDISH_USER_FIELD_ACTION_PHRASES,
    *_ENGLISH_USER_FIELD_ACTION_PHRASES,
)
_SWEDISH_USER_FIELD_ACTOR_TOKENS = frozenset(
    {
        "anvandaren",
        "användaren",
        "anvandare",
        "användare",
        "vi",
        "jag",
        "du",
        "man",
    }
)
_ENGLISH_USER_FIELD_ACTOR_TOKENS = frozenset(
    {
        "user",
        "users",
        "we",
        "i",
        "you",
        "they",
    }
)
_NON_USER_ACTOR_TOKENS = frozenset(
    {
        "flode",
        "flöde",
        "flow",
        "rapport",
        "report",
        "system",
        "systemet",
        "assistant",
        "assistent",
    }
)
_LEADING_CONNECTOR_RE = re.compile(
    r"^\s*(?:for|för|with|med|som|called|named|including|inklusive)\s+",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARIES: tuple[str, ...] = (
    ".",
    "\n",
    ";",
    " och skapar ",
    " och skapa ",
    " och skriver ",
    " och skriv ",
    " och genererar ",
    " och generera ",
    " and creates ",
    " and create ",
    " and writes ",
    " and write ",
    " and generates ",
    " and generate ",
    " then ",
    " and then ",
    " sedan ",
    " och sedan ",
    " innan ",
    " before ",
    " när ",
    " nar ",
    " when ",
    " som slutresultat ",
    " as final output ",
)
_FIELD_SPLIT_RE = re.compile(
    r"\s*(?:,|/|\boch\b|\band\b|\bsamt\b|\beller\b|\bor\b)\s*",
    re.IGNORECASE,
)
_TRAILING_CONTEXT_RE = re.compile(
    r"\s*(?:vid körning|vid korning|at runtime|runtime|som ska användas|som ska anvandas|that should be used|to use)$",
    re.IGNORECASE,
)
_SWEDISH_NAME_OF_RE = re.compile(r"^namn\s+p[åa]\s+(.+)$", re.IGNORECASE)
_ENGLISH_NAME_OF_RE = re.compile(r"^name\s+of\s+(.+)$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_GENERIC_FIELD_LABELS = {
    "field",
    "fields",
    "falt",
    "fält",
    "form field",
    "form fields",
    "input field",
    "input fields",
    "metadata",
}
_NEGATION_TOKENS = frozenset(
    {
        "inga",
        "ingen",
        "inget",
        "inte",
        "no",
        "not",
        "none",
        "utan",
        "without",
    }
)
_OPTIONAL_SCOPE_TOKENS = frozenset(
    {
        "additional",
        "extra",
        "sekundara",
        "sekundära",
        "secondary",
    }
)
_ABSENCE_PREDICATE_TOKENS = frozenset(
    {
        "behovs",
        "behövs",
        "kravs",
        "krävs",
        "needed",
        "required",
    }
)
_POST_TRIGGER_NEGATABLE_ABSENCE_PREDICATE_TOKENS = frozenset(
    {
        "behovs",
        "behövs",
        "kravs",
        "krävs",
        "needed",
    }
)
_ABSENCE_AUXILIARY_TOKENS = frozenset(
    {
        "are",
        "is",
        "be",
        "är",
        "ar",
    }
)


def runtime_input_fields_declared_absent(text: str) -> bool:
    """Return true when the user explicitly says no secondary fields are needed.

    This is intentionally about polarity near the generic runtime-field concept,
    not about domain-specific words. It prevents phrases such as "no extra input
    fields needed" from being parsed as a request for a field named "needed".
    """

    token_spans = _normalized_token_spans(text)
    if not token_spans:
        return False
    tokens = [token for token, _, _ in token_spans]

    trigger_polarities: list[tuple[int, bool]] = []
    for trigger in _RUNTIME_METADATA_ABSENCE_TRIGGERS:
        trigger_tokens = normalize_discovery_text(trigger).split()
        if not trigger_tokens:
            continue
        for start_index in _find_token_sequence_indexes(tokens, trigger_tokens):
            before = tokens[max(0, start_index - 4) : start_index]
            after_start = start_index + len(trigger_tokens)
            after = tokens[after_start : after_start + 4]
            start_char = token_spans[start_index][1]
            trigger_polarities.append(
                (
                    start_index,
                    _field_trigger_has_absence_polarity(
                        before=before,
                        after=after,
                    )
                    or _trigger_clause_has_negated_user_field_action(
                        text,
                        trigger_start_char=start_char,
                    ),
                )
            )
    if not trigger_polarities:
        return False
    return max(trigger_polarities, key=lambda item: item[0])[1]


def runtime_input_fields_requested(text: str) -> bool:
    if runtime_input_fields_declared_absent(text):
        return False
    normalized = normalize_discovery_text(text)
    return contains_any_phrase(
        normalized, _RUNTIME_METADATA_INTENT_TRIGGERS
    ) or _has_user_provided_runtime_field_clause(text)


def extract_runtime_input_field_hints(text: str) -> tuple[RuntimeInputFieldHint, ...]:
    if not runtime_input_fields_requested(text):
        return ()

    hints: list[RuntimeInputFieldHint] = []
    seen: set[str] = set()
    for clause in _candidate_field_clauses(text):
        for label in _candidate_labels(clause):
            variable_name = _variable_name(label)
            if not variable_name or variable_name in seen:
                continue
            hints.append(
                RuntimeInputFieldHint(variable_name=variable_name, label=label)
            )
            seen.add(variable_name)
            if len(hints) >= 8:
                return tuple(hints)
    return tuple(hints)


def normalize_runtime_metadata_state(
    value: str | None,
) -> RuntimeMetadataState | None:
    if value in _RUNTIME_METADATA_STATES:
        return value
    return None


def runtime_metadata_allows_input_fields(
    state: RuntimeMetadataState | None,
) -> bool:
    return state in _RUNTIME_METADATA_STATES_ALLOWING_FIELDS


def runtime_metadata_disables_declared_input_fields(
    *,
    state: RuntimeMetadataState | None,
    source: SlotSource | None,
    confidence: SlotConfidence | None,
) -> bool:
    if state != NO_EXTRA_RUNTIME_METADATA or source is None:
        return False

    match source:
        case "structured_answer" | "requirements_summary":
            return True
        case "heuristic" | "model":
            return confidence == "high"
        case "flow_default" | "policy_default":
            return False
    return assert_never(source)


def infer_runtime_metadata_slot(text: str) -> RuntimeMetadataState | None:
    if runtime_input_fields_declared_absent(text):
        return NO_EXTRA_RUNTIME_METADATA
    if extract_runtime_input_field_hints(text):
        return DETAILED_CASE_METADATA
    if runtime_input_fields_requested(text):
        return BASIC_CASE_METADATA
    return None


def _find_token_sequence_indexes(
    tokens: list[str],
    sequence: list[str],
) -> tuple[int, ...]:
    last_start = len(tokens) - len(sequence)
    if last_start < 0:
        return ()
    indexes: list[int] = []
    for index in range(last_start + 1):
        if tokens[index : index + len(sequence)] == sequence:
            indexes.append(index)
    return tuple(indexes)


def _field_trigger_has_absence_polarity(
    *,
    before: list[str],
    after: list[str],
) -> bool:
    negated = any(token in _NEGATION_TOKENS for token in before)
    if not negated:
        return _post_trigger_clause_has_absence_polarity(after)
    if before and before[-1] in _NEGATION_TOKENS:
        return True
    if not after:
        return True
    if any(token in {"utan", "without"} for token in before):
        return True
    if any(token in _OPTIONAL_SCOPE_TOKENS for token in before):
        return True
    if any(token in {"utan", "without"} for token in after):
        return True
    if any(token in _ABSENCE_PREDICATE_TOKENS for token in after):
        return True
    return _post_trigger_clause_has_absence_polarity(after)


def _trigger_clause_has_negated_user_field_action(
    text: str,
    *,
    trigger_start_char: int,
) -> bool:
    prefix = text[
        _last_clause_boundary_end(text, trigger_start_char) : trigger_start_char
    ]
    tokens = normalize_discovery_text(prefix).split()
    if not tokens or not any(token in _NEGATION_TOKENS for token in tokens):
        return False

    for phrase in _USER_FIELD_ACTION_PHRASES:
        phrase_tokens = normalize_discovery_text(phrase).split()
        if not phrase_tokens:
            continue
        for start_index in _find_token_sequence_indexes(tokens, phrase_tokens):
            if _user_field_action_is_negated(tokens, start_index):
                return True
    return False


def _last_clause_boundary_end(text: str, end_char: int) -> int:
    prefix = text[:end_char]
    indexes = [prefix.rfind(boundary) for boundary in (".", "\n", ";", "!", "?")]
    latest = max(indexes)
    return 0 if latest < 0 else latest + 1


def _post_trigger_clause_has_absence_polarity(after: list[str]) -> bool:
    clause = list(after)
    while clause and clause[0] in _ABSENCE_AUXILIARY_TOKENS:
        clause.pop(0)
    negation_indexes = [
        index for index, token in enumerate(clause) if token in _NEGATION_TOKENS
    ]
    predicate_indexes = [
        index
        for index, token in enumerate(clause)
        if token in _ABSENCE_PREDICATE_TOKENS
    ]
    for negation_index in negation_indexes:
        if any(
            0 < predicate_index - negation_index <= 2
            for predicate_index in predicate_indexes
        ):
            return True
    return any(
        clause[predicate_index] in _POST_TRIGGER_NEGATABLE_ABSENCE_PREDICATE_TOKENS
        and predicate_index + 1 in negation_indexes
        for predicate_index in predicate_indexes
    )


def _clause_starts_with_absence_predicate(clause: str) -> bool:
    tokens = normalize_discovery_text(clause).split()
    return bool(tokens) and tokens[0] in _ABSENCE_PREDICATE_TOKENS


def _candidate_field_clauses(text: str) -> tuple[str, ...]:
    clauses: list[str] = []
    starts = sorted(
        {*_trigger_end_char_indexes(text), *_user_field_action_end_char_indexes(text)}
    )
    for start in starts:
        window = text[start : start + 180]
        clause = _truncate_at_boundary(_LEADING_CONNECTOR_RE.sub("", window))
        if clause and not _clause_starts_with_absence_predicate(clause):
            clauses.append(clause)
    return tuple(clauses)


def _has_user_provided_runtime_field_clause(text: str) -> bool:
    return bool(_user_field_action_end_char_indexes(text))


def _user_field_action_end_char_indexes(text: str) -> tuple[int, ...]:
    """Find user-provided field declarations without treating outputs as inputs.

    The actor gate is deliberate. Phrases such as "the flow should extract name"
    describe output fields, while "the user will enter name" describes runtime
    metadata the run form must collect.
    """

    token_spans = _normalized_token_spans(text)
    tokens = [token for token, _, _ in token_spans]
    indexes: set[int] = set()
    phrase_groups = (
        (
            _SWEDISH_USER_FIELD_ACTION_PHRASES,
            _SWEDISH_USER_FIELD_ACTOR_TOKENS,
        ),
        (
            _ENGLISH_USER_FIELD_ACTION_PHRASES,
            _ENGLISH_USER_FIELD_ACTOR_TOKENS,
        ),
    )
    for phrases, actor_tokens in phrase_groups:
        for phrase in phrases:
            phrase_tokens = normalize_discovery_text(phrase).split()
            if not phrase_tokens:
                continue
            for start_index in _find_token_sequence_indexes(tokens, phrase_tokens):
                if not _has_user_actor_before_action(
                    text,
                    token_spans,
                    start_index,
                    allowed_actors=actor_tokens,
                ):
                    continue
                if _user_field_action_is_negated(tokens, start_index):
                    continue
                end_index = start_index + len(phrase_tokens) - 1
                indexes.add(token_spans[end_index][2])
    return tuple(sorted(indexes))


def _user_field_action_is_negated(
    tokens: list[str],
    action_start_index: int,
) -> bool:
    before = tokens[max(0, action_start_index - 4) : action_start_index]
    return any(token in _NEGATION_TOKENS for token in before)


def _has_user_actor_before_action(
    text: str,
    token_spans: tuple[tuple[str, int, int], ...],
    action_start_index: int,
    *,
    allowed_actors: frozenset[str],
) -> bool:
    action_start_char = token_spans[action_start_index][1]
    clause_start = _last_clause_boundary_end(text, action_start_char)
    before_indexes = range(max(0, action_start_index - 8), action_start_index)
    actor_indexes = [
        index
        for index in before_indexes
        if token_spans[index][1] >= clause_start
        and _is_allowed_user_actor(text, token_spans[index], allowed_actors)
    ]
    if not actor_indexes:
        return False
    last_actor_index = max(actor_indexes)
    last_non_user_index = max(
        (
            index
            for index in before_indexes
            if token_spans[index][1] >= clause_start
            and token_spans[index][0] in _NON_USER_ACTOR_TOKENS
        ),
        default=-1,
    )
    return last_actor_index > last_non_user_index


def _is_allowed_user_actor(
    text: str,
    token_span: tuple[str, int, int],
    allowed_actors: frozenset[str],
) -> bool:
    """Keep English first-person `I` from matching Swedish lowercase `i`."""
    token, start, end = token_span
    if token == "i":
        return "i" in allowed_actors and text[start:end] == "I"
    return token in allowed_actors


def _trigger_end_char_indexes(text: str) -> tuple[int, ...]:
    token_spans = _normalized_token_spans(text)
    tokens = [token for token, _, _ in token_spans]
    indexes: set[int] = set()
    for trigger in _RUNTIME_FIELD_DECLARATION_TRIGGERS:
        trigger_tokens = normalize_discovery_text(trigger).split()
        if not trigger_tokens:
            continue
        for start_index in _find_token_sequence_indexes(tokens, trigger_tokens):
            end_index = start_index + len(trigger_tokens) - 1
            indexes.add(token_spans[end_index][2])
    return tuple(sorted(indexes))


def _normalized_token_spans(text: str) -> tuple[tuple[str, int, int], ...]:
    spans: list[tuple[str, int, int]] = []
    for match in _TOKEN_RE.finditer(text):
        normalized = normalize_discovery_text(match.group(0))
        if normalized:
            spans.append((normalized, match.start(), match.end()))
    return tuple(spans)


def _truncate_at_boundary(value: str) -> str:
    best_index: int | None = None
    folded = value.casefold()
    for boundary in _CLAUSE_BOUNDARIES:
        index = folded.find(boundary.casefold())
        if index >= 0 and (best_index is None or index < best_index):
            best_index = index
    return (
        value[:best_index].strip(" ,:-")
        if best_index is not None
        else value.strip(" ,:-")
    )


def _candidate_labels(clause: str) -> tuple[str, ...]:
    labels: list[str] = []
    for raw_part in _FIELD_SPLIT_RE.split(clause):
        label = _normalize_label(raw_part)
        if not _is_useful_label(label):
            continue
        labels.append(label)
    return tuple(labels)


def _normalize_label(value: str) -> str:
    normalized = _TRAILING_CONTEXT_RE.sub("", value).strip(" .,:;-")
    return _simplify_field_label(" ".join(normalized.split()))


def _simplify_field_label(label: str) -> str:
    normalized = normalize_discovery_text(label)
    tokens = normalized.split()
    if not tokens:
        return label

    name_of = _name_of_label(label)
    if name_of is not None:
        return name_of

    token_set = set(tokens)
    if "nuvarande" in token_set and ("lön" in token_set or "lon" in token_set):
        return "nuvarande lön"
    if "salary" in token_set and {"current", "present"} & token_set:
        return "current salary"

    if tokens[0] in {"vilken", "vilket", "which"}:
        if "roll" in token_set or "role" in token_set:
            return "roll" if "roll" in token_set else "role"
        if (
            "yrke" in token_set
            or "profession" in token_set
            or "occupation" in token_set
        ):
            return "yrke" if "yrke" in token_set else "profession"
        words = label.split()
        if len(words) >= 2:
            return words[1].strip(" .,:;-")

    if tokens[0] in {"vad", "what"} and ("lön" in token_set or "lon" in token_set):
        return "lön"
    if tokens[0] in {"vad", "what"} and "salary" in token_set:
        return "salary"

    return label


def _name_of_label(label: str) -> str | None:
    match = _SWEDISH_NAME_OF_RE.match(label)
    if match is not None:
        subject = _first_subject_token(match.group(1))
        return f"{subject} namn" if subject else None

    match = _ENGLISH_NAME_OF_RE.match(label)
    if match is not None:
        subject = _first_subject_token(match.group(1))
        return f"{subject} name" if subject else None

    return None


def _first_subject_token(value: str) -> str:
    tokens = normalize_discovery_text(value).split()
    if not tokens:
        return ""
    token = tokens[0].removesuffix("'s")
    if token.endswith("en") and len(token) > 4:
        token = token[:-2]
    return token


def _is_useful_label(label: str) -> bool:
    if not label:
        return False
    normalized = normalize_discovery_text(label)
    if normalized in _GENERIC_FIELD_LABELS:
        return False
    if normalized in _ABSENCE_PREDICATE_TOKENS:
        return False
    return len(normalized.split()) <= 4 and len(label) <= 48


def _variable_name(label: str) -> str:
    ascii_label = (
        unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    )
    variable = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_label.casefold()).strip("_")
    if not variable:
        return ""
    if variable[0].isdigit():
        variable = f"field_{variable}"
    return variable[:48].rstrip("_")
