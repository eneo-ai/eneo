"""Speaker labels in diarized transcripts, and the prompt that names them.

A diarized transcript renders one line per segment,
``[HH:MM:SS - HH:MM:SS] SPEAKER_00: text``. Labels are assigned per audio
file, so a multi-file transcript renumbers them before a label can be
treated as one person. The speaker-mapping prompt turns labels into names
from a participant list or from what the conversation itself says; its
answer is validated against a fixed JSON contract. Everything here is pure
text processing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

import jsonschema

from eneo.files.transcript import TranscriptSegment

SPEAKER_LINE_RE = re.compile(
    r"^(?P<prefix>\[\d{2}:\d{2}:\d{2} - \d{2}:\d{2}:\d{2}\] )"
    r"(?P<label>SPEAKER_\d{2,}): (?P<text>.*)$"
)
SPEAKER_LABEL_RE = re.compile(r"^SPEAKER_\d{2,}$")

INVENTORY_SAMPLE_LINES = 3
INVENTORY_SAMPLE_CHARS = 160
OPENING_EXCERPT_LINES = 40
OPENING_EXCERPT_CHARS = 6000
OPENING_EXCERPT_LINE_CHARS = 600
NAME_MAX_CHARS = 120

# The fixed JSON contract of a speaker-mapping answer.
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
                    "evidence": {"type": ["string", "null"]},
                },
            },
        }
    },
}

_RESPONSE_FORMAT = (
    "Respond with JSON only. Include every supplied label exactly once, copied "
    "unchanged. A name is text when supported, otherwise JSON null, not the "
    'string "null". Evidence may be empty or null when no supporting words are '
    "available; do not invent a reason.\n"
    "Example with an unknown identity (use the actual labels from the input):\n"
    '{"speakers": [{"label": "SPEAKER_00", "name": null, '
    '"confidence": "low", "evidence": ""}]}'
)

SPEAKER_MAPPING_INSTRUCTIONS = (
    "You map diarized speaker labels in a transcript to the people who took part.\n"
    "You receive each speaker label with sample lines it spoke, and the list of "
    "participants.\n"
    "Rules:\n"
    "- Map each label to exactly one participant from the list, or to null when "
    "the evidence is insufficient.\n"
    "- Never invent a name that is not in the participant list.\n"
    "- Two labels may map to the same participant (for example when the same "
    "person appears in several recordings).\n"
    "- Use introductions, being addressed by name, roles and context as evidence.\n"
    "- For every label give a confidence (low, medium, high) and one short "
    "sentence of evidence in the language of the transcript.\n"
) + _RESPONSE_FORMAT

# With name inference on, the participant list is a hint rather than a
# closed set: the conversation itself may name or describe the speakers.
SPEAKER_MAPPING_INFER_INSTRUCTIONS = (
    "You identify who each diarized speaker label in a transcript is.\n"
    "You receive each speaker label with sample lines it spoke, the opening of "
    "the conversation in order, and a list of participants that may be empty "
    "or incomplete.\n"
    "Rules:\n"
    "- When the evidence matches a participant from the list, use that "
    "participant's name exactly as listed.\n"
    "- Otherwise propose only a name explicitly present in the supplied "
    "conversation, exactly as transcribed. Never invent a name, add a surname, "
    "correct a heard name, or identify a public figure from world knowledge, "
    "politics, subject matter, or a role.\n"
    "- Mentioning someone in the third person does not establish that they "
    "are a speaker. Require a clear link between the named person and the "
    "speaker label, such as an introduction or direct address and response.\n"
    "- People are usually named by others, not by themselves. Read the opening "
    "as a dialogue: when one speaker addresses or hands over to someone by name "
    "(for example 'Anna, du är på plats' or 'jag står här med Anna'), the "
    "speaker who answers next, or the person described, is that person. A clue "
    "in another speaker's lines is as strong as one in the speaker's own.\n"
    "- When only a role is evident (for example the person who says they work "
    "as a case officer), propose the role as the transcript words it, in the "
    "language of the transcript. The reviewer confirms every proposal.\n"
    "- Use null whenever the name or its connection to the speaker is "
    "unsupported or ambiguous. A plausible identity is not evidence.\n"
    "- Two labels may map to the same person (for example when the same "
    "person appears in several recordings).\n"
    "- Confidence (low, medium, high) reflects how strongly the transcript "
    "supports the proposal. An empty or incomplete participant list never "
    "lowers it.\n"
    "- For every label give one short sentence of evidence in the language of "
    "the transcript, quoting the supplied words that support the identity and "
    "its link to the speaker. Do not invent a quote.\n"
) + _RESPONSE_FORMAT


def _format_label(index: int) -> str:
    return f"SPEAKER_{index:02d}"


def renumber_segment_speakers(
    segments: Sequence[TranscriptSegment], offset: int
) -> tuple[list[TranscriptSegment], int]:
    """This file's labels rewritten to ``SPEAKER_{offset + n}`` in order of
    first appearance, so labels of several files never collide. Returns the
    segments and how many distinct labels the file had."""
    mapping: dict[str, str] = {}
    for segment in segments:
        if segment.speaker and segment.speaker not in mapping:
            mapping[segment.speaker] = _format_label(offset + len(mapping))
    renumbered = [
        replace(segment, speaker=mapping[segment.speaker])
        if segment.speaker in mapping
        else segment
        for segment in segments
    ]
    return renumbered, len(mapping)


def build_speaker_inventory(
    segments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One entry per label, in order of first appearance, with sample lines."""
    entries: dict[str, dict[str, Any]] = {}
    for segment in segments:
        label = segment.get("speaker")
        text = str(segment.get("text") or "").strip()
        if not label:
            continue
        entry = entries.setdefault(
            label,
            {
                "label": label,
                "file_index": segment.get("file_index", 0),
                "line_count": 0,
                "samples": [],
            },
        )
        entry["line_count"] += 1
        samples = cast(list[str], entry["samples"])
        if text and len(samples) < INVENTORY_SAMPLE_LINES:
            samples.append(text[:INVENTORY_SAMPLE_CHARS])
    return list(entries.values())


def build_opening_excerpt(segments: Sequence[Mapping[str, Any]]) -> list[str]:
    """The conversation's first lines in order, as ``SPEAKER_NN: text``."""
    lines: list[str] = []
    total = 0
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        line = f"{segment.get('speaker') or '?'}: {text[:OPENING_EXCERPT_LINE_CHARS]}"
        if (
            len(lines) >= OPENING_EXCERPT_LINES
            or total + len(line) > OPENING_EXCERPT_CHARS
        ):
            break
        lines.append(line)
        total += len(line)
    return lines


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


def speaker_mapping_instructions(*, infer_names: bool) -> str:
    return (
        SPEAKER_MAPPING_INFER_INSTRUCTIONS
        if infer_names
        else SPEAKER_MAPPING_INSTRUCTIONS
    )


def build_speaker_mapping_question(
    *,
    inventory: Sequence[Mapping[str, Any]],
    participants: Sequence[str],
    opening: Sequence[str] | None = None,
) -> str:
    """The frozen model input; ``opening`` only with name inference."""
    payload: dict[str, Any] = {
        "participants": list(participants),
        "speakers": [
            {
                "label": entry.get("label"),
                "file_index": entry.get("file_index"),
                "line_count": entry.get("line_count"),
                "samples": entry.get("samples"),
            }
            for entry in inventory
        ],
    }
    if opening is not None:
        payload["opening"] = list(opening)
    return json.dumps(payload, ensure_ascii=False, indent=2)


class SpeakerMappingInvalid(ValueError):
    """The model's answer does not fit the contract or names an unknown person."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_speaker_mapping(
    text: str,
    *,
    inventory: Sequence[Mapping[str, Any]],
    participants: Sequence[str],
    allow_free_text: bool,
) -> dict[str, str | None]:
    """Label to name from the model's answer, checked against the contract.

    Every inventory label must be answered once. Without free text a name
    must be one of ``participants`` (case-insensitive, returned as listed);
    with it, any one-line name is accepted. An unsupported label is null.
    """
    try:
        value = json.loads(_FENCE.sub("", text).strip())
        jsonschema.validate(value, SPEAKER_MAPPING_OUTPUT_CONTRACT)
    except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise SpeakerMappingInvalid(f"not a speaker mapping: {exc}") from exc
    expected = [str(entry.get("label")) for entry in inventory]
    by_lower = {name.lower(): name for name in participants}
    names: dict[str, str | None] = {}
    for entry in cast(list[dict[str, Any]], value["speakers"]):
        label = str(entry["label"])
        if label not in expected or label in names:
            raise SpeakerMappingInvalid(f"unexpected or repeated label {label}")
        raw = entry.get("name")
        name = str(raw).strip() if isinstance(raw, str) else ""
        if not name or name.lower() == "null":
            names[label] = None
            continue
        listed = by_lower.get(name.lower())
        if listed is not None:
            names[label] = listed
        elif allow_free_text and len(name) <= NAME_MAX_CHARS and "\n" not in name:
            names[label] = name
        elif allow_free_text:
            raise SpeakerMappingInvalid(f"name for {label} is not one line")
        else:
            names[label] = None
    missing = [label for label in expected if label not in names]
    if missing:
        raise SpeakerMappingInvalid(f"labels not answered: {', '.join(missing)}")
    return names


def format_clock(seconds: float) -> str:
    """``HH:MM:SS`` (floored) as the rendered transcript lines carry it."""
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_line_prefix(start: float, end: float) -> str:
    return f"[{format_clock(start)} - {format_clock(end)}] "


def render_segments(
    segments: Sequence[Mapping[str, Any]],
    names: Mapping[str, str | None] | None = None,
) -> str:
    """One line per segment: the window, the speaker (named when a name is
    known, else its label) and the text. Segments without a speaker render
    as window and text only."""
    lines: list[str] = []
    for segment in segments:
        prefix = render_line_prefix(
            float(segment.get("start") or 0), float(segment.get("end") or 0)
        )
        label = segment.get("speaker")
        text = str(segment.get("text") or "")
        if label:
            name = (names or {}).get(str(label)) or str(label)
            lines.append(f"{prefix}{name}: {text}")
        else:
            lines.append(f"{prefix}{text}")
    return "\n".join(lines)
