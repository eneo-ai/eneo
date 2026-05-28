"""Detect named output sections requested for generated reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_sectioned_form_intake,
)

OutputSectionConfidence = Literal["high", "low"]

# Four or more named headings is enough evidence for a real report outline, while
# longer lists are usually source material, examples, or pasted instructions.
_MIN_HIGH_CONFIDENCE_SECTIONS = 4
_MAX_HIGH_CONFIDENCE_SECTIONS = 30

_REPORT_OUTPUT_CUES: tuple[str, ...] = (
    "dokument",
    "rapport",
    "slutrapport",
    "slutdokument",
    "document",
    "report",
    "memo",
    "project plan",
)

_SECTION_LIST_CUES: tuple[str, ...] = (
    "följande rubriker",
    "följande avsnitt",
    "rubrikerna",
    "rapporten ska innehålla",
    "slutdokumentet ska innehålla",
    "dokumentet ska innehålla",
    "strukturen nedan",
    "following sections",
    "following headings",
    "sections:",
    "headings:",
    "report should contain",
    "report should include",
    "document should contain",
    "document should include",
)

_EXPLICIT_HEADING_RE = re.compile(
    r"(?im)^\s*(?:rubrik|heading)\s*:\s*(?P<title>.+?)\s*$"
)
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s*#{1,3}\s+(?P<title>[^#\n].*?)\s*$")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+(?P<title>[^\n]+?)\s*$")


@dataclass(frozen=True, slots=True)
class RequestedOutputSections:
    sections: tuple[str, ...] = ()
    confidence: OutputSectionConfidence = "low"

    @classmethod
    def empty(cls) -> "RequestedOutputSections":
        return cls()

    @property
    def high_confidence(self) -> bool:
        return self.confidence == "high"


def extract_requested_output_sections(text: str) -> RequestedOutputSections:
    normalized = text.casefold()
    if not normalized or mentions_sectioned_form_intake(text):
        return RequestedOutputSections.empty()

    explicit_titles = _explicit_heading_titles(text)
    candidates = (
        list(explicit_titles)
        if explicit_titles
        else [
            *_cue_scoped_list_titles(text, normalized),
            *_inline_heading_titles(text, normalized),
            *_markdown_heading_titles(text, normalized),
        ]
    )
    sections = _dedupe_titles(candidates)
    if (
        len(sections) < _MIN_HIGH_CONFIDENCE_SECTIONS
        or len(sections) > _MAX_HIGH_CONFIDENCE_SECTIONS
    ):
        return RequestedOutputSections(sections=sections)
    return RequestedOutputSections(sections=sections, confidence="high")


def _explicit_heading_titles(text: str) -> tuple[str, ...]:
    return tuple(
        title
        for match in _EXPLICIT_HEADING_RE.finditer(text)
        if (title := _clean_title(match.group("title")))
    )


def _cue_scoped_list_titles(text: str, normalized: str) -> tuple[str, ...]:
    if not _has_any(normalized, _SECTION_LIST_CUES):
        return ()
    block = _text_after_first_cue(text, normalized, _SECTION_LIST_CUES)
    if block is None:
        return ()
    titles: list[str] = []
    for match in _LIST_ITEM_RE.finditer(block):
        title = _clean_title(match.group("title"))
        if title:
            titles.append(title)
    return tuple(titles)


def _inline_heading_titles(text: str, normalized: str) -> tuple[str, ...]:
    cue = _first_matching_cue(normalized, ("rubrikerna", "sections:", "headings:"))
    if cue is None:
        return ()
    cue_start = normalized.find(cue)
    line = text[cue_start:].splitlines()[0]
    after_cue = line[len(cue) :]
    if ":" in after_cue:
        after_cue = after_cue.split(":", 1)[1]
    if _looks_like_sentence_after_heading_cue(after_cue):
        return ()

    parts = [part for part in re.split(r",|;", after_cue) if part.strip()]
    if len(parts) > 1:
        tail = parts[-1]
        tail_parts = re.split(r"\boch\b|\band\b", tail, maxsplit=1)
        if len(tail_parts) == 2:
            parts = [*parts[:-1], *tail_parts]
    else:
        parts = re.split(r"\boch\b|\band\b", after_cue)

    return tuple(title for raw in parts if (title := _clean_title(raw)))


def _looks_like_sentence_after_heading_cue(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized.startswith(
        (
            "ska ",
            "ska inte ",
            "should ",
            "must ",
            "not ",
            "är ",
            "are ",
        )
    )


def _markdown_heading_titles(text: str, normalized: str) -> tuple[str, ...]:
    if not _has_any(normalized, _REPORT_OUTPUT_CUES):
        return ()
    return tuple(
        title
        for match in _MARKDOWN_HEADING_RE.finditer(text)
        if (title := _clean_title(match.group("title")))
    )


def _text_after_first_cue(
    text: str,
    normalized: str,
    cues: tuple[str, ...],
) -> str | None:
    cue = _first_matching_cue(normalized, cues)
    if cue is None:
        return None
    start = normalized.find(cue)
    return text[start:]


def _first_matching_cue(normalized: str, cues: tuple[str, ...]) -> str | None:
    matches = ((normalized.find(cue), cue) for cue in cues if cue in normalized)
    ordered = sorted((index, cue) for index, cue in matches if index >= 0)
    return ordered[0][1] if ordered else None


def _dedupe_titles(titles: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for title in titles:
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(title)
    return tuple(deduped)


def _clean_title(raw: str) -> str | None:
    title = raw.strip().strip("`*_")
    title = re.sub(r"\s+", " ", title)
    title = title.rstrip(".:;")
    if len(title) < 3:
        return None
    if "{{" in title or "}}" in title:
        return None
    return title


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


__all__ = [
    "OutputSectionConfidence",
    "RequestedOutputSections",
    "extract_requested_output_sections",
]
