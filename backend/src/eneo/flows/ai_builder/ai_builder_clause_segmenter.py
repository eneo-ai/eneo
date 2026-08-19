from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_phrase,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_intent_markers import (
    INPUT_ROLE_MARKERS,
    OUTPUT_ROLE_MARKERS,
    REPLACEMENT_PHRASES,
    TERMINAL_OUTPUT_ARTIFACT_FILLER_TOKENS,
    TERMINAL_OUTPUT_ARTIFACT_MARKERS,
    TERMINAL_OUTPUT_POSITION_MARKERS,
    TERMINAL_OUTPUT_PRECEDING_ARTIFACT_LEAD_IN_MARKERS,
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
        return _split_terminal_output_clauses([IntentClause(role="neutral", text=text)])

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
    return _split_terminal_output_clauses(clauses)


# Keep terminal-position pairing local to a short phrase; longer spans usually
# mean the input and output requests share a clause but are separate ideas.
_TERMINAL_ARTIFACT_MAX_GAP = 48
# Lead-ins can include polite filler before the artifact: "jag vill ha en kort
# sammanfattande Word-fil i slutet" should still move the artifact to output.
_TERMINAL_OUTPUT_LEAD_IN_LOOKBEHIND = 80


def _split_terminal_output_clauses(
    clauses: list[IntentClause],
) -> list[IntentClause]:
    scoped: list[IntentClause] = []
    for clause in clauses:
        scoped.extend(_split_terminal_output_clause(clause))
    return scoped


def _split_terminal_output_clause(clause: IntentClause) -> list[IntentClause]:
    if clause.role == "output":
        return [clause]

    output_start = _terminal_output_start(clause)
    if output_start is None:
        return [clause]

    before = clause.text[:output_start].strip()
    output = clause.text[output_start:].strip()
    split_clauses: list[IntentClause] = []
    if before:
        split_clauses.append(IntentClause(role=clause.role, text=before))
    if output:
        split_clauses.append(IntentClause(role="output", text=output))
    return split_clauses


def _terminal_output_start(clause: IntentClause) -> int | None:
    text = clause.text
    terminal_spans = _phrase_spans_for_markers(
        text,
        TERMINAL_OUTPUT_POSITION_MARKERS,
    )
    artifact_spans = _phrase_spans_for_markers(
        text,
        TERMINAL_OUTPUT_ARTIFACT_MARKERS,
    )
    if not terminal_spans or not artifact_spans:
        return None

    for terminal_start, terminal_end in terminal_spans:
        following_artifact = _first_nearby_following_artifact(
            artifact_spans,
            terminal_end=terminal_end,
        )
        if following_artifact is not None:
            return terminal_start

        # A preceding artifact in an input clause may be the uploaded file itself,
        # so it needs an output lead-in such as "vill ha" before it can move.
        preceding_artifact = _nearest_preceding_artifact(
            text,
            artifact_spans,
            terminal_start=terminal_start,
            role=clause.role,
        )
        if preceding_artifact is not None:
            return preceding_artifact[0]
    return None


def _phrase_spans_for_markers(
    text: str,
    markers: tuple[str, ...],
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for marker in markers:
        spans.extend(_find_phrase_spans(text, marker))
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))

    filtered: list[tuple[int, int]] = []
    for span in spans:
        if any(_span_contains(existing, span) for existing in filtered):
            continue
        filtered = [
            existing for existing in filtered if not _span_contains(span, existing)
        ]
        filtered.append(span)
    return filtered


def _span_contains(container: tuple[int, int], candidate: tuple[int, int]) -> bool:
    return container[0] <= candidate[0] and candidate[1] <= container[1]


def _first_nearby_following_artifact(
    artifact_spans: list[tuple[int, int]],
    *,
    terminal_end: int,
) -> tuple[int, int] | None:
    for artifact_start, artifact_end in artifact_spans:
        if artifact_start < terminal_end:
            continue
        if artifact_start - terminal_end <= _TERMINAL_ARTIFACT_MAX_GAP:
            return (artifact_start, artifact_end)
        return None
    return None


def _nearest_preceding_artifact(
    text: str,
    artifact_spans: list[tuple[int, int]],
    *,
    terminal_start: int,
    role: ClauseRole,
) -> tuple[int, int] | None:
    preceding = [
        span
        for span in artifact_spans
        if span[1] <= terminal_start
        and terminal_start - span[1] <= _TERMINAL_ARTIFACT_MAX_GAP
        and _preceding_artifact_can_be_output(
            text,
            artifact_start=span[0],
            artifact_end=span[1],
            terminal_start=terminal_start,
            role=role,
        )
    ]
    if not preceding:
        return None
    return max(preceding, key=lambda span: (span[1], span[1] - span[0]))


def _preceding_artifact_can_be_output(
    text: str,
    *,
    artifact_start: int,
    artifact_end: int,
    terminal_start: int,
    role: ClauseRole,
) -> bool:
    if not _between_artifact_and_terminal_is_output_filler(
        text[artifact_end:terminal_start]
    ):
        return False
    if role != "input":
        return True
    return _has_output_lead_in_before_artifact(text, artifact_start=artifact_start)


def _between_artifact_and_terminal_is_output_filler(text: str) -> bool:
    normalized = normalize_discovery_text(text)
    if not normalized:
        return True
    allowed_tokens = set(TERMINAL_OUTPUT_ARTIFACT_FILLER_TOKENS)
    return all(token in allowed_tokens for token in normalized.split())


def _has_output_lead_in_before_artifact(text: str, *, artifact_start: int) -> bool:
    lookbehind_start = max(0, artifact_start - _TERMINAL_OUTPUT_LEAD_IN_LOOKBEHIND)
    lead_in_text = text[lookbehind_start:artifact_start]
    return contains_any_phrase(
        lead_in_text,
        TERMINAL_OUTPUT_PRECEDING_ARTIFACT_LEAD_IN_MARKERS,
    )


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
                if role == "output" and _looks_like_non_output_anchor(
                    text,
                    marker=marker,
                    start=start,
                    end=end,
                ):
                    continue
                candidates.append(_RoleAnchor(role=role, start=start, end=end))

    candidates.sort(key=lambda anchor: (anchor.start, -(anchor.end - anchor.start)))
    anchors: list[_RoleAnchor] = []
    for candidate in candidates:
        if anchors and candidate.start < anchors[-1].end:
            continue
        anchors.append(candidate)
    return anchors


_FLOW_CREATION_OUTPUT_ANCHOR_PHRASES: tuple[str, ...] = (
    "skapa flöde",
    "skapa ett flöde",
    "skapa en flöde",
    "skapa flow",
    "skapa ett flow",
    "skapa en flow",
)
_RECEIVE_AS_INPUT_OUTPUT_ANCHORS: frozenset[str] = frozenset(
    {
        "få en",
        "få ett",
        "får en",
        "får ett",
    }
)
_FOLLOWING_INPUT_SCOPE_MARKERS: tuple[str, ...] = (
    "uppladdad",
    "uppladdat",
    "uppladdade",
    "som input",
    "som indata",
    "input",
    "indata",
)
# Keep this symmetric with the output lead-in lookbehind window.
_FOLLOWING_INPUT_SCOPE_WINDOW = 80


def _looks_like_non_output_anchor(
    text: str,
    *,
    marker: str,
    start: int,
    end: int,
) -> bool:
    if any(
        text.startswith(phrase, start)
        for phrase in _FLOW_CREATION_OUTPUT_ANCHOR_PHRASES
    ):
        return True
    if marker in _RECEIVE_AS_INPUT_OUTPUT_ANCHORS:
        following = text[end : end + _FOLLOWING_INPUT_SCOPE_WINDOW]
        return contains_any_phrase(following, _FOLLOWING_INPUT_SCOPE_MARKERS)
    return False


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
