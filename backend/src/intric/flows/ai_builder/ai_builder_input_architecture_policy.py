from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from intric.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_any_token_prefix,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

PrimaryRuntimeInput = Literal[
    "audio", "documents", "text", "text_and_documents", "unknown"
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
    "pdf",
    "docx",
    "word",
    "dokument",
    "document",
    "fil",
    "file",
    "bilag",
    "attachment",
)

_RUNTIME_FILE_ACTION_PREFIXES: tuple[str, ...] = (
    "uppladd",
    "upload",
    "bifog",
    "attach",
    "receiv",
)

_RUNTIME_FILE_ACTION_PHRASES: tuple[str, ...] = (
    "ladda upp",
    "skicka in",
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
    "skriv",
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
    "text input",
    "runtime input",
    "vid körning",
    "vid korning",
    "input field",
)

_OUTPUT_ONLY_EDIT_INPUT_CHANGE_MARKERS: tuple[str, ...] = (
    (
        "ändra indata",
        "change input",
        "ny indata",
        "new input",
        "input architecture",
        "indataarkitektur",
        "flow_input",
        "upload",
        "ladda upp",
        "runtime input",
        "filtyp",
        "file type",
        "document package",
        "dokumentpaket",
    )
    + _AUDIO_PREFIX_MARKERS
    + _DOCUMENT_INPUT_MARKERS
    + _DOCUMENT_UPLOAD_MARKERS
    + _TEXT_INPUT_MARKERS
)


@dataclass(frozen=True, slots=True)
class InputIntentResolution:
    primary_runtime_input: PrimaryRuntimeInput
    audio_requested: bool
    document_runtime_input_requested: bool
    needs_architecture_clarification: bool


def mixed_audio_document_input_requested(
    text: str,
    *,
    flow: "Flow | None" = None,
) -> bool:
    return resolve_input_intent(text, {}, flow=flow).needs_architecture_clarification


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


def infer_mixed_input_architecture_choice(text: str) -> str | None:
    normalized = _normalize_signal_text(text)
    if not normalized:
        return None
    if _contains_any(
        normalized,
        (
            "behåll dokument",
            "keep documents",
            "documents as primary",
            "dokument som primär",
            "keep the document flow",
            "documents as usual",
            "dokument som vanligt",
        ),
    ):
        return "document_primary_input"
    if _contains_any(
        normalized,
        (
            "byt till ljud",
            "switch to audio",
            "audio as primary",
            "ljud som primär",
            "transcribe first",
            "transkribera först",
        ),
    ):
        return "audio_primary_input"
    if _contains_any(
        normalized,
        (
            "blandade filer",
            "mixed files",
            "all file types",
            "alla typer",
            "generic file",
            "fil alla typer",
        ),
    ):
        return "generic_file_input"
    return None


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
        first_spec.existing_step_ref == "existing_step_1"
        and first_spec.input_source == InputSource.FLOW_INPUT
        and first_spec.input_type == InputType.FILE
    )


def uses_pseudo_transcription_without_audio_step(spec: FlowDraftSpecCore) -> bool:
    if has_real_audio_transcription_step(spec):
        return False

    for step in spec.steps:
        instructions = step.assistant_spec.instructions.casefold()
        if _contains_any(
            instructions, ("transkrib", "transcrib", "samtal", "discussion")
        ):
            return True
    return False


def is_narrow_output_edit_request(
    text: str,
    *,
    flow: "Flow | None" = None,
    flow_defaults: dict[str, set[str]] | None = None,
) -> bool:
    from intric.flows.ai_builder.ai_builder_framework_policy import (
        mentions_output_change,
        mentions_runtime_metadata,
    )

    if flow is None:
        return False

    normalized = _normalize_signal_text(text)
    if not normalized or not mentions_output_change(normalized):
        return False
    if mentions_runtime_metadata(normalized):
        return False

    defaults = (
        flow_defaults
        if flow_defaults is not None
        else build_flow_discovery_defaults(flow)
    )
    if not _flow_has_defined_input_architecture(defaults):
        return False

    return not _contains_any(normalized, _OUTPUT_ONLY_EDIT_INPUT_CHANGE_MARKERS)


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
    if "audio" in input_modes:
        return "audio"
    if "documents" in input_modes:
        return "documents"
    if "text" in input_modes:
        return "text"
    return "unknown"


def _flow_has_defined_input_architecture(flow_defaults: dict[str, set[str]]) -> bool:
    return bool(flow_defaults.get("input_material_mode")) or bool(
        flow_defaults.get("document_material_scope")
    )


def _resolve_primary_from_defaults(
    defaults: dict[str, set[str]],
) -> PrimaryRuntimeInput:
    input_modes = defaults.get("input_material_mode", set())
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
    audio_requested = _audio_runtime_input_requested(text)
    document_requested = _document_runtime_input_requested(text)

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
    if not text or _text_runtime_input_requested(text):
        return False
    has_transcription_semantics = contains_any_token_prefix(
        text,
        ("transkrib", "transcrib"),
    ) or _contains_any(text, ("speech to text", "tal till text"))
    if not has_transcription_semantics:
        return _contains_any(
            text, ("ljudfil", "audio file", "upload audio", "ladda upp ljud")
        )
    return contains_any_token_prefix(text, _AUDIO_PREFIX_MARKERS) or _contains_any(
        text,
        ("one on one",),
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
    if _mentions_runtime_document_input(text):
        return True
    if _mentions_source_material_underlag(text):
        return True
    if "underlag" in text and _contains_any(
        text,
        (
            "ladda upp",
            "upload",
            "skicka in",
            "send in",
            "ta emot",
            "receive",
            "lämna underlag",
            "provide source material",
        ),
    ):
        return True
    if _contains_any(text, _DOCUMENT_INPUT_MARKERS):
        return True
    return _contains_any(text, _DOCUMENT_UPLOAD_MARKERS) and _contains_any(
        text,
        (
            "pdf",
            "docx",
            "word",
            "document",
            "documents",
            "dokument",
        ),
    )


def _mentions_runtime_document_input(text: str) -> bool:
    """Detect file/document runtime input without enumerating every phrasing.

    The discovery layer only needs to know whether the user's text implies
    uploaded/provided source files. Exact business-domain document kinds belong
    elsewhere; this helper intentionally combines generic file-action prefixes
    with generic document/file references.
    """

    if not _mentions_document_reference(text):
        return False
    if contains_any_token_prefix(text, _RUNTIME_FILE_ACTION_PREFIXES):
        return True
    if _contains_any(text, _RUNTIME_FILE_ACTION_PHRASES):
        return True
    tokens = text.split()
    return "emot" in tokens and any(token in {"ta", "tar"} for token in tokens)


def _mentions_document_reference(text: str) -> bool:
    return contains_any_token_prefix(text, _DOCUMENT_REFERENCE_PREFIXES)


def _text_runtime_input_requested(text: str) -> bool:
    if _contains_any(text, _TEXT_INPUT_MARKERS):
        return True
    return _mentions_runtime_text_input(text)


def _mentions_runtime_text_input(text: str) -> bool:
    if not contains_any_token_prefix(text, _TEXT_REFERENCE_PREFIXES):
        return False
    if contains_any_token_prefix(text, _RUNTIME_TEXT_ACTION_PREFIXES):
        return True
    return _contains_any(text, _RUNTIME_TEXT_ACTION_PHRASES)


def _has_explicit_input_resolution(explicit_question_ids: set[str] | None) -> bool:
    if explicit_question_ids is None:
        return False
    return bool(
        explicit_question_ids.intersection(
            {"flow_input_architecture", "input_material_mode"}
        )
    )


def _mentions_source_material_underlag(text: str) -> bool:
    return contains_any_phrase(text, ("underlag",))
