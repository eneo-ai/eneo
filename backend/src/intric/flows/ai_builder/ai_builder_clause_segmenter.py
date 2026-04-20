from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_phrase,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_intent_markers import (
    INPUT_ROLE_MARKERS,
    OUTPUT_ROLE_MARKERS,
    REPLACEMENT_PHRASES,
)

ClauseRole = Literal[
    "input",
    "output",
    "replacement_target",
    "replacement_source",
    "neutral",
]


@dataclass(frozen=True, slots=True)
class IntentClause:
    role: ClauseRole
    text: str


@dataclass(frozen=True, slots=True)
class RoleScopedText:
    clauses: tuple[IntentClause, ...]

    @property
    def input_text(self) -> str:
        return self.text_for("input")

    @property
    def output_text(self) -> str:
        return self.text_for("output")

    @property
    def replacement_target_text(self) -> str:
        return self.text_for("replacement_target")

    @property
    def replacement_source_text(self) -> str:
        return self.text_for("replacement_source")

    @property
    def neutral_text(self) -> str:
        return self.text_for("neutral")

    @property
    def full_text(self) -> str:
        return " ".join(clause.text for clause in self.clauses).strip()

    def text_for(self, *roles: ClauseRole) -> str:
        return " ".join(
            clause.text for clause in self.clauses if clause.role in roles
        ).strip()

    def preferred_input_text(self) -> str:
        return self.input_text or self.neutral_text or self.full_text

    def preferred_output_text(self) -> str:
        return (
            self.replacement_target_text
            or self.output_text
            or self.neutral_text
            or self.full_text
        )


def build_role_scoped_text(text: str) -> RoleScopedText:
    normalized = normalize_discovery_text(text)
    if not normalized:
        return RoleScopedText(())

    replacement_phrase = _first_matching_phrase(normalized, REPLACEMENT_PHRASES)
    if replacement_phrase is not None:
        before, _, after = normalized.partition(replacement_phrase)
        replacement_clauses = list(_extract_role_clauses(before.strip()))
        clauses: list[IntentClause] = []
        replacement_target_found = False
        for clause in replacement_clauses:
            if clause.role == "output":
                replacement_target_found = True
                clauses.append(
                    IntentClause(role="replacement_target", text=clause.text)
                )
            else:
                clauses.append(clause)
        if before.strip() and not replacement_target_found:
            clauses.append(IntentClause(role="replacement_target", text=before.strip()))
        if after.strip():
            clauses.append(IntentClause(role="replacement_source", text=after.strip()))
        return RoleScopedText(tuple(clauses))

    return RoleScopedText(tuple(_extract_role_clauses(normalized)))


def _extract_role_clauses(text: str) -> list[IntentClause]:
    anchors = _collect_role_anchors(text)
    if not anchors:
        return [IntentClause(role="neutral", text=text)]

    clauses: list[IntentClause] = []
    cursor = 0
    for index, anchor in enumerate(anchors):
        if anchor.start > cursor:
            neutral = text[cursor : anchor.start].strip()
            if neutral:
                clauses.append(IntentClause(role="neutral", text=neutral))
        end = anchors[index + 1].start if index + 1 < len(anchors) else len(text)
        role_text = text[anchor.start : end].strip()
        if role_text:
            clauses.append(IntentClause(role=anchor.role, text=role_text))
        cursor = end

    if cursor < len(text):
        trailing = text[cursor:].strip()
        if trailing:
            clauses.append(IntentClause(role="neutral", text=trailing))
    return clauses


@dataclass(frozen=True, slots=True)
class _RoleAnchor:
    role: Literal["input", "output"]
    start: int
    end: int


def _collect_role_anchors(text: str) -> list[_RoleAnchor]:
    candidates: list[_RoleAnchor] = []
    role_entries: tuple[tuple[Literal["input", "output"], tuple[str, ...]], ...] = (
        ("input", INPUT_ROLE_MARKERS),
        ("output", OUTPUT_ROLE_MARKERS),
    )
    for role, markers in role_entries:
        for marker in markers:
            for start, end in _find_phrase_spans(text, marker):
                candidates.append(_RoleAnchor(role=role, start=start, end=end))

    candidates.sort(key=lambda anchor: (anchor.start, -(anchor.end - anchor.start)))
    anchors: list[_RoleAnchor] = []
    for candidate in candidates:
        if anchors and candidate.start < anchors[-1].end:
            continue
        anchors.append(candidate)
    return anchors


def _find_phrase_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    normalized_phrase = normalize_discovery_text(phrase)
    if not normalized_phrase:
        return []

    spans: list[tuple[int, int]] = []
    search_from = 0
    while search_from < len(text):
        index = text.find(normalized_phrase, search_from)
        if index == -1:
            break
        candidate = text[index : index + len(normalized_phrase)]
        if contains_phrase(text, candidate):
            before_ok = index == 0 or text[index - 1] == " "
            after_index = index + len(normalized_phrase)
            after_ok = after_index == len(text) or text[after_index] == " "
            if before_ok and after_ok:
                spans.append((index, after_index))
        search_from = index + len(normalized_phrase)
    return spans


def _first_matching_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        normalized = normalize_discovery_text(phrase)
        if normalized and contains_phrase(text, normalized):
            return normalized
    return None
