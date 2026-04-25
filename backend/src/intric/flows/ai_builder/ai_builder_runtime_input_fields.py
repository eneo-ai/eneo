from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    normalize_discovery_text,
)


@dataclass(frozen=True, slots=True)
class RuntimeInputFieldHint:
    """A server-derived hint for fields users fill in when a flow runs."""

    variable_name: str
    label: str
    field_type: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()


_RUNTIME_FIELD_TRIGGERS: tuple[str, ...] = (
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
    " och genererar ",
    " och generera ",
    " and creates ",
    " and create ",
    " and generates ",
    " and generate ",
    " then ",
    " and then ",
    " sedan ",
    " och sedan ",
    " som slutresultat ",
    " as final output ",
)
_FIELD_SPLIT_RE = re.compile(r"\s*(?:,|/|\boch\b|\band\b|\bsamt\b)\s*", re.IGNORECASE)
_TRAILING_CONTEXT_RE = re.compile(
    r"\s*(?:vid körning|vid korning|at runtime|runtime)$",
    re.IGNORECASE,
)
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


def runtime_input_fields_declared_absent(text: str) -> bool:
    """Return true when the user explicitly says no secondary fields are needed.

    This is intentionally about polarity near the generic runtime-field concept,
    not about domain-specific words. It prevents phrases such as "no extra input
    fields needed" from being parsed as a request for a field named "needed".
    """

    tokens = normalize_discovery_text(text).split()
    if not tokens:
        return False

    trigger_polarities: list[tuple[int, bool]] = []
    for trigger in _RUNTIME_FIELD_TRIGGERS:
        trigger_tokens = normalize_discovery_text(trigger).split()
        if not trigger_tokens:
            continue
        for start_index in _find_token_sequence_indexes(tokens, trigger_tokens):
            before = tokens[max(0, start_index - 4) : start_index]
            after_start = start_index + len(trigger_tokens)
            after = tokens[after_start : after_start + 4]
            trigger_polarities.append(
                (
                    start_index,
                    _field_trigger_has_absence_polarity(
                        before=before,
                        after=after,
                    ),
                )
            )
    if not trigger_polarities:
        return False
    return max(trigger_polarities, key=lambda item: item[0])[1]


def runtime_input_fields_requested(text: str) -> bool:
    if runtime_input_fields_declared_absent(text):
        return False
    return contains_any_phrase(normalize_discovery_text(text), _RUNTIME_FIELD_TRIGGERS)


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


def extract_runtime_input_field_hints_for_metadata_state(
    text: str,
    *,
    runtime_metadata_state: str | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    """Extract field hints only when the server policy allows secondary fields."""

    if runtime_metadata_state == "no_extra_metadata":
        return ()
    return extract_runtime_input_field_hints(text)


def infer_runtime_metadata_slot(text: str) -> str | None:
    if runtime_input_fields_declared_absent(text):
        return "no_extra_metadata"
    if extract_runtime_input_field_hints(text):
        return "detailed_case_metadata"
    if runtime_input_fields_requested(text):
        return "basic_case_metadata"
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
        return False
    if not after:
        return True
    if any(token in {"utan", "without"} for token in before):
        return True
    if any(token in _OPTIONAL_SCOPE_TOKENS for token in before):
        return True
    if any(token in {"utan", "without"} for token in after):
        return True
    return any(token in _ABSENCE_PREDICATE_TOKENS for token in after)


def _clause_starts_with_absence_predicate(clause: str) -> bool:
    tokens = normalize_discovery_text(clause).split()
    return bool(tokens) and tokens[0] in _ABSENCE_PREDICATE_TOKENS


def _candidate_field_clauses(text: str) -> tuple[str, ...]:
    clauses: list[str] = []
    for start in _trigger_end_char_indexes(text):
        window = text[start : start + 180]
        clause = _truncate_at_boundary(_LEADING_CONNECTOR_RE.sub("", window))
        if clause and not _clause_starts_with_absence_predicate(clause):
            clauses.append(clause)
    return tuple(clauses)


def _trigger_end_char_indexes(text: str) -> tuple[int, ...]:
    token_spans = _normalized_token_spans(text)
    tokens = [token for token, _, _ in token_spans]
    indexes: set[int] = set()
    for trigger in _RUNTIME_FIELD_TRIGGERS:
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
    return " ".join(normalized.split())


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
