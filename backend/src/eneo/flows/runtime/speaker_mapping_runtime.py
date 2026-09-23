"""Prompting and validation for the speaker-mapping step (no I/O)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, cast

from eneo.flows.domain.one_line_text import ONE_LINE_TEXT_MAX_CHARS, breaks_one_line
from eneo.flows.domain.speaker_labels import SPEAKER_LABEL_RE, parse_participants
from eneo.flows.domain.speaker_mapping_config import (
    speaker_mapping_speaker_count_field,
)
from eneo.flows.flow_run_input_envelope import read_semantic_flow_input_payload

_SPEAKER_MAPPING_RESPONSE_FORMAT = (
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
) + _SPEAKER_MAPPING_RESPONSE_FORMAT

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
) + _SPEAKER_MAPPING_RESPONSE_FORMAT


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
    """The frozen model input. ``opening`` is included only when given, so a
    step without name inference sends exactly what it always has."""
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


def resolve_participants(
    run_input_payload: Mapping[str, Any] | None,
    participants_field: str | None,
) -> list[str]:
    if participants_field is None:
        return []
    semantic = read_semantic_flow_input_payload(dict(run_input_payload or {}))
    return parse_participants(semantic.get(participants_field))


class SpeakerMappingValidationError(ValueError):
    pass


def clean_proposed_speaker_name(name: str) -> str | None:
    """A model's proposed name made one short line: whitespace, line breaks
    included, collapses to single spaces and other control or format
    characters go. A name left empty or over the bound is dropped, so the
    label stays for the reviewer to name."""
    visible = "".join(
        char for char in name if char.isspace() or not breaks_one_line(char)
    )
    cleaned = " ".join(visible.split())
    return cleaned if 0 < len(cleaned) <= ONE_LINE_TEXT_MAX_CHARS else None


def validate_speaker_mapping(
    structured: object,
    *,
    inventory: Sequence[Mapping[str, Any]],
    participants: Sequence[str],
    allow_free_text: bool,
    split_labels: Sequence[str] = (),
    model_proposal: bool = False,
) -> dict[str, Any]:
    """Normalize a mapping to the inventory: every known label exactly once,
    and at most once a label the transcript's own speaker edits split off
    after the inventory was taken. Names are restricted to participants
    unless free text is allowed. A reviewer's name that is not one short line
    is refused; a model's proposed name is cleaned to one instead."""
    if not isinstance(structured, Mapping):
        raise SpeakerMappingValidationError("Speaker mapping must be an object.")
    raw_speakers = cast(Mapping[str, object], structured).get("speakers")
    if not isinstance(raw_speakers, list):
        raise SpeakerMappingValidationError("Speaker mapping needs a speakers list.")
    known_labels = [str(entry.get("label")) for entry in inventory]
    optional_labels = [label for label in split_labels if label not in known_labels]
    by_label: dict[str, dict[str, Any]] = {}
    for item in cast(list[object], raw_speakers):
        if not isinstance(item, Mapping):
            raise SpeakerMappingValidationError("Each speaker entry must be an object.")
        entry = cast(Mapping[str, object], item)
        label = entry.get("label")
        if not isinstance(label, str) or not SPEAKER_LABEL_RE.match(label):
            raise SpeakerMappingValidationError("Each speaker entry needs a label.")
        if label not in known_labels and label not in optional_labels:
            raise SpeakerMappingValidationError(
                f"Unknown speaker label '{label}' in mapping."
            )
        if label in by_label:
            raise SpeakerMappingValidationError(f"Duplicate speaker label '{label}'.")
        name = entry.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise SpeakerMappingValidationError(
                    "Speaker name must be text or null."
                )
            if model_proposal:
                name = clean_proposed_speaker_name(name)
            else:
                name = name.strip() or None
                if name is not None and (
                    len(name) > ONE_LINE_TEXT_MAX_CHARS
                    or any(breaks_one_line(char) for char in name)
                ):
                    raise SpeakerMappingValidationError(
                        f"The name for '{label}' must be one line of at most "
                        f"{ONE_LINE_TEXT_MAX_CHARS} characters."
                    )
        if name is not None and not allow_free_text and name not in participants:
            raise SpeakerMappingValidationError(
                f"'{name}' is not one of the participants."
            )
        confidence = entry.get("confidence")
        if confidence not in ("low", "medium", "high"):
            confidence = "low"
        evidence = entry.get("evidence")
        by_label[label] = {
            "label": label,
            "name": name,
            "confidence": confidence,
            "evidence": evidence if isinstance(evidence, str) else "",
        }
    missing = [label for label in known_labels if label not in by_label]
    if missing:
        raise SpeakerMappingValidationError(
            f"Mapping is missing speaker labels: {', '.join(missing)}."
        )
    return {
        "speakers": [
            by_label[label]
            for label in [*known_labels, *optional_labels]
            if label in by_label
        ]
    }


def ground_speaker_mapping_proposal(
    structured: Mapping[str, Any],
    *,
    inventory: Sequence[Mapping[str, Any]],
    participants: Sequence[str],
    opening: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Discard machine-proposed identities absent from the actual model input.

    Presence is necessary, not proof that a mentioned person is a speaker.
    The prompt handles that relationship and a person reviews the result.
    Human edits deliberately use validate_speaker_mapping without this gate.
    """
    passages = [
        sample
        for entry in inventory
        for sample in entry.get("samples", [])
        if isinstance(sample, str)
    ]
    passages.extend(line.partition(": ")[2] for line in opening or [])
    normalized_passages = [_normalize_name_evidence(text) for text in passages]
    speakers: list[dict[str, Any]] = []
    for entry in structured["speakers"]:
        proposed = dict(entry)
        name = proposed["name"]
        if name is not None and name not in participants:
            pattern = re.compile(
                r"(?<!\w)" + re.escape(_normalize_name_evidence(name)) + r"(?!\w)"
            )
            if not any(pattern.search(text) for text in normalized_passages):
                # Do not retain the model's explanation of an unsupported identity.
                proposed.update(name=None, confidence="low", evidence="")
        speakers.append(proposed)
    return {**structured, "speakers": speakers}


def _normalize_name_evidence(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def resolve_max_speakers(
    steps: Sequence[Any],
    run_input_payload: Mapping[str, Any] | None,
) -> int | None:
    """Upper bound on speakers for diarization, from the first speaker-mapping
    step's optional speaker-count number field. The participant list is
    deliberately not used: it is "who I know was there", not a complete roster,
    and a cap below the real speaker count would merge unlisted voices into
    the wrong person. None when no count is given, so the diarizer chooses."""
    for step in steps:
        if getattr(step, "output_mode", None) != "speaker_mapping":
            continue
        count_field = speaker_mapping_speaker_count_field(
            getattr(step, "output_config", None)
        )
        if count_field is None:
            return None
        semantic = read_semantic_flow_input_payload(dict(run_input_payload or {}))
        return _positive_int(semantic.get(count_field))
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        count = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        count = int(value.strip())
    else:
        return None
    return count if count >= 1 else None


def mapping_to_names(structured: Mapping[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for entry in structured.get("speakers", []):
        label = entry.get("label")
        name = entry.get("name")
        if isinstance(label, str) and isinstance(name, str) and name:
            names[label] = name
    return names
