"""Speaker labels in diarized transcripts.

The external transcription service renders one line per segment:
``[HH:MM:SS - HH:MM:SS] SPEAKER_00: text``. Labels are assigned per audio
file, so a multi-file transcript must be renumbered before any label can be
treated as one person. Everything here is pure text processing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        TranscriptSegment,
    )

SPEAKER_LINE_RE = re.compile(
    r"^(?P<prefix>\[\d{2}:\d{2}:\d{2} - \d{2}:\d{2}:\d{2}\] )"
    r"(?P<label>SPEAKER_\d{2,}): (?P<text>.*)$"
)
SPEAKER_LABEL_RE = re.compile(r"^SPEAKER_\d{2,}$")

INVENTORY_SAMPLE_LINES = 3
INVENTORY_SAMPLE_CHARS = 160

# Fixed JSON contract for a speaker-mapping step's structured output. Set on
# the runtime step by the definition parser so typed-output processing, the
# review checkpoint and review edits all validate against the same schema.
SPEAKER_MAPPING_OUTPUT_CONTRACT: dict[str, Any] = {
    "type": "object",
    "required": ["speakers"],
    "additionalProperties": False,
    "properties": {
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "name", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string", "pattern": "^SPEAKER_\\d{2,}$"},
                    "name": {"type": ["string", "null"]},
                    "confidence": {"enum": ["low", "medium", "high"]},
                    "evidence": {"type": "string"},
                },
            },
        }
    },
}


def _format_label(index: int) -> str:
    return f"SPEAKER_{index:02d}"


def build_label_renumbering(text: str, offset: int) -> dict[str, str]:
    """This file's labels mapped to ``SPEAKER_{offset + n}`` in order of first
    appearance in the text."""
    mapping: dict[str, str] = {}
    for line in text.split("\n"):
        match = SPEAKER_LINE_RE.match(line)
        if match is None:
            continue
        label = match.group("label")
        if label not in mapping:
            mapping[label] = _format_label(offset + len(mapping))
    return mapping


def renumber_speaker_labels(text: str, offset: int) -> tuple[str, int]:
    """Rewrite this file's labels to ``SPEAKER_{offset + n}`` in order of first
    appearance. Returns the text and how many distinct labels it had."""
    mapping = build_label_renumbering(text, offset)
    lines: list[str] = []
    for line in text.split("\n"):
        match = SPEAKER_LINE_RE.match(line)
        if match is None:
            lines.append(line)
            continue
        label = mapping[match.group("label")]
        lines.append(f"{match.group('prefix')}{label}: {match.group('text')}")
    return "\n".join(lines), len(mapping)


def renumber_segment_speakers(
    segments: Sequence["TranscriptSegment"], mapping: Mapping[str, str]
) -> list["TranscriptSegment"]:
    """The same renumbering applied to the structured segments behind the text,
    so a label means the same person in both views. Labels the text never
    showed (the service's text is the contract) stay as they are."""
    return [
        replace(segment, speaker=mapping.get(segment.speaker, segment.speaker))
        if segment.speaker is not None
        else segment
        for segment in segments
    ]


def build_speaker_inventory(
    text: str,
    *,
    file_index: int = 0,
    file_id: str | None = None,
) -> list[dict[str, Any]]:
    """One entry per label, in order of first appearance, with sample lines."""
    entries: dict[str, dict[str, Any]] = {}
    for line in text.split("\n"):
        match = SPEAKER_LINE_RE.match(line)
        if match is None:
            continue
        label = match.group("label")
        entry = entries.setdefault(
            label,
            {
                "label": label,
                "file_index": file_index,
                "file_id": file_id,
                "line_count": 0,
                "samples": [],
            },
        )
        entry["line_count"] += 1
        samples: list[str] = entry["samples"]
        sample = match.group("text").strip()
        if sample and len(samples) < INVENTORY_SAMPLE_LINES:
            samples.append(sample[:INVENTORY_SAMPLE_CHARS])
    return list(entries.values())


def speaker_labels_in(text: str) -> list[str]:
    return [entry["label"] for entry in build_speaker_inventory(text)]


def apply_speaker_names(text: str, names: Mapping[str, str]) -> str:
    """Replace the ``SPEAKER_NN:`` token on matching lines; unmapped labels stay."""
    lines: list[str] = []
    for line in text.split("\n"):
        match = SPEAKER_LINE_RE.match(line)
        if match is None:
            lines.append(line)
            continue
        name = names.get(match.group("label"))
        if not name:
            lines.append(line)
            continue
        lines.append(f"{match.group('prefix')}{name}: {match.group('text')}")
    return "\n".join(lines)


def parse_participants(value: object) -> list[str]:
    """Names from a form field: a list of strings, or free text split on
    newlines, commas and semicolons. Stripped and deduplicated, order kept."""
    raw: Sequence[object]
    if isinstance(value, str):
        raw = re.split(r"[\n,;]+", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw = cast(Sequence[object], value)
    else:
        return []
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in names:
            names.append(name)
    return names


def format_clock(seconds: float) -> str:
    """``HH:MM:SS`` (floored) as the rendered transcript lines carry it."""
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_line_prefix(start: float, end: float) -> str:
    """The ``[HH:MM:SS - HH:MM:SS] `` prefix ``SPEAKER_LINE_RE`` recognises."""
    return f"[{format_clock(start)} - {format_clock(end)}] "
