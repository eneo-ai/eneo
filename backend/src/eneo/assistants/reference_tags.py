from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Generic, TypeVar

INLINE_REFERENCE_PATTERN = re.compile(r'<inref id="([0-9a-f]{8})"/>')
# Every tag is this long, so a tag ending in new text starts at most this many
# characters minus one before it.
_TAG_LENGTH = len('<inref id="00000000"/>')

TBlob = TypeVar("TBlob")


def extract_inline_reference_ids(text: str) -> list[str]:
    return list(dict.fromkeys(INLINE_REFERENCE_PATTERN.findall(text)))


def _blob_id(blob: object) -> object:
    return getattr(blob, "id", getattr(blob, "info_blob_id", None))


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
