"""Word timings stored beside a transcription step's structured lines.

A transcription service that force-aligns text to audio returns one timed
word per token of every segment. The step result keeps only the segment
lines (they are evidence for a reader and bounded in size); the words live
in their own row so an hour-long recording does not bloat every steps
listing. Words anchor to the stored segment array by ``segment_index`` and
carry the array's content hash so a re-transcription is detectable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# On the ``forced`` alignment rung a word scored exactly 0.0 was interpolated
# (spread evenly over its window) rather than found in the audio.
FORCED_ALIGNMENT = "forced"
INTERPOLATED_WORD_PROBABILITY = 0.0


class FlowStepTranscriptWords(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    segments_hash: str
    alignment: str | None
    # ``[{"segment_index": int, "words": [{"word", "start", "end",
    # "probability"}]}]`` in stored segment order.
    words_json: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


def is_interpolated_word(word: dict[str, Any], *, alignment: str | None) -> bool:
    """True when the service placed ``word`` by interpolation, not alignment."""
    return (
        alignment == FORCED_ALIGNMENT
        and word.get("probability") == INTERPOLATED_WORD_PROBABILITY
    )


def count_interpolated_words(
    words_json: list[dict[str, Any]], *, alignment: str | None
) -> int:
    if alignment != FORCED_ALIGNMENT:
        return 0
    return sum(
        1
        for entry in words_json
        for word in entry.get("words", [])
        if is_interpolated_word(word, alignment=alignment)
    )


_EDGE_PUNCTUATION_RE = re.compile(r"^[^\w]+|[^\w]+$")


@dataclass(frozen=True, slots=True)
class LocatedWord:
    """A stored word placed in its segment's raw text.

    ``char_start``/``char_end`` are ``-1`` when the token could not be found;
    such a word still has a time but anchors to no text range.
    """

    word: str
    start: float
    end: float
    probability: float | None
    char_start: int
    char_end: int

    @property
    def located(self) -> bool:
        return self.char_start >= 0


def locate_words(text: str, words: list[dict[str, Any]]) -> list[LocatedWord]:
    """Place stored words in ``text`` by sequential search.

    Tokens usually appear verbatim; a token the aligner stripped of
    punctuation is retried bare. The frontend mirrors this placement so both
    views agree on which text a word covers.
    """
    cursor = 0
    located: list[LocatedWord] = []
    for entry in words:
        token = str(entry.get("word", ""))
        start = float(entry.get("start", 0.0))
        end = max(start, float(entry.get("end", start)))
        raw_probability = entry.get("probability")
        probability = (
            float(raw_probability)
            if isinstance(raw_probability, (int, float))
            and not isinstance(raw_probability, bool)
            else None
        )
        char_start = char_end = -1
        candidates = [token, _EDGE_PUNCTUATION_RE.sub("", token)]
        for candidate in candidates:
            if not candidate:
                continue
            at = text.find(candidate, cursor)
            if at < 0:
                continue
            char_start, char_end = at, at + len(candidate)
            cursor = char_end
            break
        located.append(
            LocatedWord(
                word=token,
                start=start,
                end=end,
                probability=probability,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return located
