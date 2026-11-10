"""Bounded timed delta collection for a session's authoritative done text."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from eneo.flows.runtime.live_transcription.upstream import UpstreamEvent

_SENTENCE_END = re.compile(r"[.!?…][\"'”’)]*\s*$")


@dataclass
class TimedPieces:
    max_bytes: int
    _pieces: list[tuple[float, float, str]] = field(
        default_factory=list[tuple[float, float, str]]
    )
    _bytes: int = 0
    _complete: bool = True

    def append(self, event: UpstreamEvent) -> None:
        if not self._complete:
            return
        start, end = event.audio_start, event.audio_end
        # Charge per-piece overhead too, so empty deltas cannot grow the list.
        self._bytes += len(event.text.encode("utf-8")) + 64
        if (
            start is None
            or end is None
            or end < start
            or (self._pieces and start < self._pieces[-1][0])
            or self._bytes > self.max_bytes
        ):
            self._complete = False
            self._pieces.clear()
            return
        self._pieces.append((start, end, event.text))

    def passages(
        self, done_text: str, *, breaks: Sequence[float] = ()
    ) -> list[dict[str, str | float]] | None:
        """The done text in timed passages. A passage ends before a piece that
        starts at or after one of ``breaks`` (where a new part of the recording
        began), so no passage spans two parts."""
        if not self._complete or not self._pieces:
            return None
        if "".join(text for _, _, text in self._pieces) != done_text:
            return None
        passages: list[dict[str, str | float]] = []
        texts: list[str] = []
        start = end = 0.0
        upcoming = sorted(breaks)
        for piece_start, piece_end, text in self._pieces:
            crossed = False
            while upcoming and piece_start >= upcoming[0]:
                upcoming.pop(0)
                crossed = True
            if texts and (crossed or piece_end - start > 30):
                passages.append({"start": start, "end": end, "text": "".join(texts)})
                texts = []
            if not texts:
                start = piece_start
            end = max(end, piece_end)
            texts.append(text)
            if end - start >= 30 or _SENTENCE_END.search(text):
                passages.append({"start": start, "end": end, "text": "".join(texts)})
                texts = []
        if texts:
            passages.append({"start": start, "end": end, "text": "".join(texts)})
        return passages
