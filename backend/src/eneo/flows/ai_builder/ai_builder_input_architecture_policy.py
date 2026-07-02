from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from eneo.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.step_lineage import existing_step_ref_for_order

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

PrimaryRuntimeInput = Literal[
    "audio", "documents", "json", "text", "text_and_documents", "unknown"
]

_AUDIO_PREFIX_MARKERS: tuple[str, ...] = (
    "audio",
    "ljud",
    "inspelning",
    "recording",
    "samtal",
    "discussion",
    "medarbetarsamtal",
    "möte",
    "meeting",
    "intervju",
    "interview",
    "call",
    "conversation",
)

_DOCUMENT_INPUT_MARKERS: tuple[str, ...] = (
    "document",
    "documents",
    "dokument",
    "bilaga",
    "bilagor",
    "attachment",
    "attachments",
    "word file",
    "word files",
    "docx",
    "uppladdat dokument",
    "uploaded document",
    "uppladdade dokument",
    "uploaded documents",
)

_DOCUMENT_UPLOAD_MARKERS: tuple[str, ...] = (
    "ladda upp",
    "upload",
    "skicka in",
    "send in",
    "ta emot",
    "receive",
    "bifoga",
    "attach",
    "som primär indata",
    "primary input",
    "primär uppladdning",
    "runtime input",
    "vid körning",
    "as usual",
    "som vanligt",
    "behåll dokument",
    "keep documents",
)

_DOCUMENT_REFERENCE_PREFIXES: tuple[str, ...] = (
    "avtal",
    "agreement",
    "contract",
    "pdf",
    "docx",
    "word",
    "dokument",
    "document",
    "underlag",
    "fil",
    "file",
    "bilag",
    "attachment",
)

_SPECIFIC_DOCUMENT_REFERENCE_PREFIXES: tuple[str, ...] = (
    "avtal",
    "agreement",
    "contract",
    "pdf",
    "docx",
    "word",
    "dokument",
    "document",
    "underlag",
)

_JSON_REFERENCE_PREFIXES: tuple[str, ...] = ("json",)

_AUDIO_REFERENCE_PREFIXES: tuple[str, ...] = (
    "audio",
    "ljud",
    "inspelning",
    "recording",
    "samtal",
    "discussion",
    "medarbetarsamtal",
    "möte",
    "mote",
    "meeting",
    "intervju",
    "interview",
    "call",
    "conversation",
)
_STRONG_AUDIO_REFERENCE_PREFIXES: tuple[str, ...] = (
    "audio",
    "ljud",
    "ljudfil",
    "inspel",
    "recording",
    "recorded",
    "mötesinspel",
    "motesinspel",
)
_EVENT_AUDIO_REFERENCE_PREFIXES: tuple[str, ...] = (
    "samtal",
    "discussion",
    "medarbetarsamtal",
    "möte",
    "mote",
    "meeting",
    "intervju",
    "interview",
    "call",
    "conversation",
)
_RECORDING_ACTION_PREFIXES: tuple[str, ...] = (
    "spela",
    "spel",
    "record",
)
_RECORDING_ACTION_PHRASES: tuple[str, ...] = (
    "spela in",
    "spelar in",
    "record",
    "recording",
)

_RUNTIME_FILE_ACTION_PREFIXES: tuple[str, ...] = (
    "uppladd",
    "ladd",
    "upload",
    "bifog",
    "attach",
    "lämn",
    "lamn",
    "läs",
    "las",
    "provide",
    "read",
    "receiv",
    "skick",
)

_RUNTIME_FILE_ACTION_PHRASES: tuple[str, ...] = (
    "ladda upp",
    "skicka in",
    "lämna in",
    "lamna in",
    "läs",
    "las",
    "spela in",
    "spelar in",
    "record",
    "ta emot",
    "tar emot",
    "read",
    "send in",
    "runtime input",
    "primary input",
    "vid körning",
    "lämna underlag",
    "provide source material",
)

_TEXT_INPUT_MARKERS: tuple[str, ...] = (
    "klistra in",
    "paste as text",
    "paste the material as text",
    "textinput",
    "text input",
    "meeting notes",
    "mötesanteckningar",
    "anteckningar",
    "existing transcript",
    "existing transcription",
    "befintlig transkribering",
    "befintligt transkript",
    "befintlig utskrift",
    "already transcribed",
    "already transcribed text",
    "redan transkriberat",
    "redan transkriberad",
    "redan utskrivet",
    "transcript",
    "transkript",
)

_TEXT_REFERENCE_PREFIXES: tuple[str, ...] = (
    "text",
    "fritext",
    "plaintext",
    "transkript",
    "transcript",
    "anteckning",
    "note",
    "notes",
)

_RUNTIME_TEXT_ACTION_PREFIXES: tuple[str, ...] = (
    "paste",
    "klistra",
    "ange",
    "mata",
    "provide",
    "receiv",
)

_RUNTIME_TEXT_ACTION_PHRASES: tuple[str, ...] = (
    "ta emot",
    "tar emot",
    "skriv in",
    "skriva in",
    "text input",
    "runtime input",
    "input field",
)


@dataclass(frozen=True, slots=True)
class InputIntentResolution:
    primary_runtime_input: PrimaryRuntimeInput
    audio_requested: bool
    document_runtime_input_requested: bool
    needs_architecture_clarification: bool


def resolve_input_intent(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    flow: "Flow | None" = None,
    explicit_question_ids: set[str] | None = None,
) -> InputIntentResolution:
    normalized = _normalize_signal_text(text)
    scoped_text = build_role_scoped_text(normalized)
    input_text = (
        " ".join(
            part for part in (scoped_text.input_text, scoped_text.neutral_text) if part
        ).strip()
        or scoped_text.full_text
    )
    defaults = build_flow_discovery_defaults(flow)
    explicit_primary = _resolve_primary_from_answers(answer_signals)
    default_primary = _resolve_primary_from_defaults(defaults)
    inferred_primary = _infer_primary_runtime_input(input_text)

    audio_requested = _audio_requested(answer_signals, defaults, input_text)
    document_requested = _document_requested(answer_signals, defaults, input_text)
    if (
        not audio_requested
        and inferred_primary == "unknown"
        and scoped_text.input_text
        and _document_requested(answer_signals, defaults, scoped_text.full_text)
    ):
        document_requested = True
        inferred_primary = "documents"

    if explicit_primary != "unknown":
        primary = explicit_primary
    elif default_primary != "unknown":
        primary = default_primary
    else:
        primary = inferred_primary

    needs_architecture_clarification = (
        audio_requested
        and document_requested
        and not _has_explicit_input_resolution(explicit_question_ids)
    )

    return InputIntentResolution(
        primary_runtime_input=primary,
        audio_requested=audio_requested,
        document_runtime_input_requested=document_requested,
        needs_architecture_clarification=needs_architecture_clarification,
    )


def has_real_audio_transcription_step(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        and step.output_mode == OutputMode.TRANSCRIBE_ONLY
        and step.output_type == OutputType.TEXT
        for step in spec.steps
    )


def degrades_document_entry_to_generic_file(
    spec: FlowDraftSpecCore,
    *,
    flow: "Flow | None",
) -> bool:
    if flow is None or not spec.steps:
        return False

    first_existing = next(
        iter(sorted(flow.steps, key=lambda step: step.step_order)), None
    )
    if first_existing is None or first_existing.input_type != "document":
        return False

    first_spec = spec.steps[0]
    return (
        first_spec.existing_step_ref == existing_step_ref_for_order(1)
        and first_spec.input_source == InputSource.FLOW_INPUT
        and first_spec.input_type == InputType.FILE
    )


def uses_pseudo_transcription_without_audio_step(spec: FlowDraftSpecCore) -> bool:
    if has_real_audio_transcription_step(spec):
        return False

    for step in spec.steps:
        # Pyright treats this Pydantic member as Unknown in isolated file checks.
        assistant_spec = cast(AssistantSpec, getattr(step, "assistant_spec"))
        instructions = assistant_spec.instructions.casefold()
        if _contains_any(
            instructions, ("transkrib", "transcrib", "samtal", "discussion")
        ):
            return True
    return False


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return contains_any_phrase(text, markers)


def _normalize_signal_text(value: str) -> str:
    return normalize_discovery_text(value)


def _resolve_primary_from_answers(
    answer_signals: dict[str, set[str]],
) -> PrimaryRuntimeInput:
    architecture = answer_signals.get("flow_input_architecture", set())
    if "audio_primary_input" in architecture:
        return "audio"
    if architecture.intersection({"document_primary_input", "generic_file_input"}):
        return "documents"

    input_modes = answer_signals.get("input_material_mode", set())
    if "text_and_documents" in input_modes:
        return "text_and_documents"
    if "json" in input_modes:
        return "json"
    if "audio" in input_modes:
        return "audio"
    if "documents" in input_modes:
        return "documents"
    if "text" in input_modes:
        return "text"
    return "unknown"


def _resolve_primary_from_defaults(
    defaults: dict[str, set[str]],
) -> PrimaryRuntimeInput:
    input_modes = defaults.get("input_material_mode", set())
    if "json" in input_modes:
        return "json"
    if "audio" in input_modes:
        return "audio"
    if "text_and_documents" in input_modes:
        return "text_and_documents"
    if "documents" in input_modes:
        return "documents"
    if "text" in input_modes:
        return "text"
    return "unknown"


def _infer_primary_runtime_input(text: str) -> PrimaryRuntimeInput:
    if not text:
        return "unknown"

    text_requested = _text_runtime_input_requested(text)
    json_requested = _json_runtime_input_requested(text)
    audio_requested = _audio_runtime_input_requested(text)
    document_requested = _document_runtime_input_requested(text)
    specific_document_requested = _specific_document_runtime_input_requested(text)

    if json_requested and document_requested and specific_document_requested:
        return "documents"
    if json_requested and not audio_requested:
        return "json"
    if audio_requested and not document_requested and not text_requested:
        return "audio"
    if document_requested and text_requested and not audio_requested:
        return "text_and_documents"
    if document_requested and not audio_requested:
        return "documents"
    if text_requested and not audio_requested:
        return "text"
    return "unknown"


def _audio_requested(
    answer_signals: dict[str, set[str]],
    defaults: dict[str, set[str]],
    text: str,
) -> bool:
    if "audio" in answer_signals.get("input_material_mode", set()):
        return True
    if "audio_primary_input" in answer_signals.get("flow_input_architecture", set()):
        return True
    if "audio" in defaults.get("input_material_mode", set()):
        return True
    return _audio_runtime_input_requested(text)


def _document_requested(
    answer_signals: dict[str, set[str]],
    defaults: dict[str, set[str]],
    text: str,
) -> bool:
    if answer_signals.get("flow_input_architecture", set()).intersection(
        {"document_primary_input", "generic_file_input"}
    ):
        return True
    if answer_signals.get("input_material_mode", set()).intersection(
        {"documents", "text_and_documents"}
    ):
        return True
    if defaults.get("input_material_mode", set()).intersection(
        {"documents", "text_and_documents"}
    ):
        return True
    return _document_runtime_input_requested(text)


def _audio_runtime_input_requested(text: str) -> bool:
    if not text:
        return False
    # The literal output-mode name appears in support questions and developer
    # discussions; it is not evidence that the user will upload audio.
    if "transcribe_only" in text:
        return False
    if _mentions_runtime_audio_input(text):
        return True
    if _text_runtime_input_requested(text):
        return False
    has_transcription_semantics = contains_any_token_prefix(
        text,
        ("transkrib", "transcrib"),
    ) or _contains_any(text, ("speech to text", "tal till text"))
    if not has_transcription_semantics:
        return _contains_any(
            text, ("ljudfil", "audio file", "upload audio", "ladda upp ljud")
        )
    if contains_any_token_prefix(
        text, _DOCUMENT_REFERENCE_PREFIXES
    ) and not contains_any_token_prefix(text, _AUDIO_REFERENCE_PREFIXES):
        return False
    # In a build request, transcription is itself evidence of audio input once
    # existing text/transcript and document-source wording have been ruled out.
    return True


def _mentions_runtime_audio_input(text: str) -> bool:
    if _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_STRONG_AUDIO_REFERENCE_PREFIXES,
        action_prefixes=_RUNTIME_FILE_ACTION_PREFIXES,
        action_phrases=_RUNTIME_FILE_ACTION_PHRASES,
    ):
        return True
    return _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_EVENT_AUDIO_REFERENCE_PREFIXES,
        action_prefixes=_RECORDING_ACTION_PREFIXES,
        action_phrases=_RECORDING_ACTION_PHRASES,
    )


def _document_runtime_input_requested(text: str) -> bool:
    if not text:
        return False
    if _contains_any(
        text,
        (
            "behåll dokument",
            "keep documents",
            "documents as primary",
            "dokument som primär",
            "documents as usual",
            "dokument som vanligt",
        ),
    ):
        return True
    # Document-like words such as "underlag" can describe derived step outputs.
    # They imply runtime document input only when paired with a nearby file action.
    return _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_DOCUMENT_REFERENCE_PREFIXES,
        action_prefixes=_RUNTIME_FILE_ACTION_PREFIXES,
        action_phrases=_RUNTIME_FILE_ACTION_PHRASES,
    )


def _specific_document_runtime_input_requested(text: str) -> bool:
    if not text:
        return False
    return _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_SPECIFIC_DOCUMENT_REFERENCE_PREFIXES,
        action_prefixes=_RUNTIME_FILE_ACTION_PREFIXES,
        action_phrases=_RUNTIME_FILE_ACTION_PHRASES,
    )


def _json_runtime_input_requested(text: str) -> bool:
    if not text:
        return False
    return _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_JSON_REFERENCE_PREFIXES,
        action_prefixes=_RUNTIME_FILE_ACTION_PREFIXES + _RUNTIME_TEXT_ACTION_PREFIXES,
        action_phrases=_RUNTIME_FILE_ACTION_PHRASES + _RUNTIME_TEXT_ACTION_PHRASES,
        # Keep JSON tighter than document references so a later phrase like
        # "returnera JSON" does not turn an uploaded document into JSON input.
        window=3,
    )


def _text_runtime_input_requested(text: str) -> bool:
    if _contains_any(text, _TEXT_INPUT_MARKERS):
        return True
    if _looks_like_audio_transcription_output_text(text):
        return False
    return _mentions_runtime_text_input(text)


def _looks_like_audio_transcription_output_text(text: str) -> bool:
    if not contains_any_token_prefix(text, ("transkrib", "transcrib")):
        return False
    if not contains_any_token_prefix(text, _AUDIO_REFERENCE_PREFIXES):
        return False
    return _contains_any(
        text,
        (
            "till text",
            "till svensk text",
            "till skriven text",
            "to text",
            "to swedish text",
            "into text",
            "speech to text",
            "tal till text",
        ),
    )


def _mentions_runtime_text_input(text: str) -> bool:
    return _reference_has_nearby_runtime_action(
        text,
        reference_prefixes=_TEXT_REFERENCE_PREFIXES,
        action_prefixes=_RUNTIME_TEXT_ACTION_PREFIXES,
        action_phrases=_RUNTIME_TEXT_ACTION_PHRASES,
    )


def _has_explicit_input_resolution(explicit_question_ids: set[str] | None) -> bool:
    if explicit_question_ids is None:
        return False
    return bool(
        explicit_question_ids.intersection(
            {"flow_input_architecture", "input_material_mode"}
        )
    )


def _reference_has_nearby_runtime_action(
    text: str,
    *,
    reference_prefixes: tuple[str, ...],
    action_prefixes: tuple[str, ...],
    action_phrases: tuple[str, ...],
    window: int = 6,
) -> bool:
    tokens = text.split()
    if not tokens:
        return False

    reference_indexes = tuple(
        index
        for index, token in enumerate(tokens)
        if _token_matches_any_prefix(token, reference_prefixes)
    )
    if not reference_indexes:
        return False

    action_indexes = tuple(
        index
        for index, token in enumerate(tokens)
        if _token_matches_any_prefix(token, action_prefixes)
    )
    for reference_index in reference_indexes:
        if any(
            abs(reference_index - action_index) <= window
            for action_index in action_indexes
        ):
            return True
        if _has_nearby_action_phrase(
            tokens,
            reference_index=reference_index,
            action_phrases=action_phrases,
            window=window,
        ):
            return True
    return False


def _has_nearby_action_phrase(
    tokens: list[str],
    *,
    reference_index: int,
    action_phrases: tuple[str, ...],
    window: int,
) -> bool:
    for phrase in action_phrases:
        phrase_tokens = normalize_discovery_text(phrase).split()
        if not phrase_tokens:
            continue
        for start_index in _find_token_sequence_indexes(tokens, phrase_tokens):
            end_index = start_index + len(phrase_tokens) - 1
            if start_index - window <= reference_index <= end_index + window:
                return True
    return False


def _find_token_sequence_indexes(
    tokens: list[str],
    needle: list[str],
) -> tuple[int, ...]:
    if not tokens or not needle or len(needle) > len(tokens):
        return ()
    last_start = len(tokens) - len(needle)
    return tuple(
        start
        for start in range(last_start + 1)
        if tokens[start : start + len(needle)] == needle
    )


def _token_matches_any_prefix(token: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        normalized_prefix and token.startswith(normalized_prefix)
        for normalized_prefix in (
            normalize_discovery_text(prefix) for prefix in prefixes
        )
    )
