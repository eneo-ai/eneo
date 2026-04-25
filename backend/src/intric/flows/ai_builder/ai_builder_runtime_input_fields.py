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


def runtime_input_fields_requested(text: str) -> bool:
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


def infer_runtime_metadata_slot(text: str) -> str | None:
    if extract_runtime_input_field_hints(text):
        return "detailed_case_metadata"
    if runtime_input_fields_requested(text):
        return "basic_case_metadata"
    return None


def _candidate_field_clauses(text: str) -> tuple[str, ...]:
    lower_text = text.casefold()
    clauses: list[str] = []
    for trigger in _RUNTIME_FIELD_TRIGGERS:
        trigger_index = lower_text.find(trigger.casefold())
        if trigger_index < 0:
            continue
        start = trigger_index + len(trigger)
        window = text[start : start + 180]
        clause = _truncate_at_boundary(_LEADING_CONNECTOR_RE.sub("", window))
        if clause:
            clauses.append(clause)
    return tuple(clauses)


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
