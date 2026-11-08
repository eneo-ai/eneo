from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Generic, TypeVar

INLINE_REFERENCE_PATTERN = re.compile(r'<inref id="([0-9a-f]{8})"/>')
# Every tag is this long, so a tag ending in new text starts at most this many
# characters minus one before it.
_TAG_LENGTH = len('<inref id="00000000"/>')

# A citation in every form the chat clients read.
_CITATION = re.compile(r'<inref\s+id="[^"<>]*"\s*/?>|</inref>')

TBlob = TypeVar("TBlob")


def extract_inline_reference_ids(text: str) -> list[str]:
    return list(dict.fromkeys(INLINE_REFERENCE_PATTERN.findall(text)))


def _blob_id(blob: object) -> object:
    return getattr(blob, "id", getattr(blob, "info_blob_id", None))


def _without_citations(text: str) -> str:
    """Citations out, with the spaces before them, so "9–17 <inref/>." reads
    "9–17.". A line break before one stays."""
    kept: list[str] = []
    start = 0
    for citation in _CITATION.finditer(text):
        kept.append(text[start : citation.start()].rstrip(" \t"))
        start = citation.end()
    return "".join(kept) + text[start:]


def _opens_citation(fragment: str) -> bool:
    # No length limit: a tag may hold any spacing and id, and a cap would let
    # a long one out whole.
    return (
        fragment.startswith("<inref")
        and fragment[6:7].isspace()
        and ">" not in fragment
    )


def _may_become_citation(fragment: str) -> bool:
    return (
        "<inref".startswith(fragment)
        or "</inref".startswith(fragment)
        or _opens_citation(fragment)
    )


def strip_inline_references(text: str) -> str:
    """The answer without its citations, also one it was cut off inside, which
    still names the source it was citing."""
    text = _without_citations(text)
    tag = text.rfind("<")
    if tag != -1 and _opens_citation(text[tag:]):
        return text[:tag].rstrip(" \t")
    return text


class InlineReferenceStripper:
    """``strip_inline_references`` for an answer that arrives in chunks.

    An ending that a later chunk could turn into a citation is held back: an
    unfinished tag and the spaces before it. What is released, joined, equals
    ``strip_inline_references`` of the whole answer.
    """

    # One stripper lives for each streaming answer: keep its state small.
    __slots__ = ("_held",)

    def __init__(self) -> None:
        self._held = ""

    def strip(self, text: str) -> str:
        window = _without_citations(self._held + text)
        tag = window.rfind("<")
        end = tag if tag != -1 and _may_become_citation(window[tag:]) else len(window)
        end = len(window[:end].rstrip(" \t"))
        self._held = window[end:]
        return window[:end]

    def flush(self) -> str:
        """What was held back, once no more text follows it."""
        held, self._held = self._held, ""
        return strip_inline_references(held)


class InlineReferenceScanner(Generic[TBlob]):
    """The blobs a streaming answer cites, scanning only what each chunk adds.

    Gives what ``get_references`` gives for the whole answer so far: blobs in
    the order first cited, each once, a cited id resolving to the first blob
    whose id starts with it. A tag cannot start inside another, so rescanning
    from one tag length before the old end finds every tag the new text ends.
    Each cited id is resolved once, the first time it is seen.
    """

    # One scanner lives for each streaming answer: keep its state small.
    __slots__ = ("_blobs", "_cited", "_references", "_scanned")

    def __init__(self, info_blobs: Sequence[TBlob]) -> None:
        self._blobs = info_blobs
        self._cited: dict[str, None] = {}
        self._references: list[TBlob] = []
        self._scanned = 0

    def references(self, answer: str) -> list[TBlob]:
        start = max(0, self._scanned - _TAG_LENGTH + 1)
        for blob_id in INLINE_REFERENCE_PATTERN.findall(answer, start):
            if blob_id in self._cited:
                continue
            self._cited[blob_id] = None
            blob = next(
                (b for b in self._blobs if str(_blob_id(b))[:8] == blob_id), None
            )
            if blob is not None:
                self._references.append(blob)
        self._scanned = len(answer)
        return list(self._references)
