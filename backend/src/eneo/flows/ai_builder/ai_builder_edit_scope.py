from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_confirmation_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_families import (
    ALL_DISCOVERY_FAMILIES,
    DiscoveryFamily,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    FlowCapabilityProfile,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    extract_freeform_user_messages,
    mentions_runtime_metadata,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
    resolve_input_intent,
)

# Architecture note:
# Prefer structural signals from the current flow state, typed discovery state,
# and explicit user deltas over expanding phrase lists. Small generic phrase
# sets are acceptable as guardrails, but new behavior should come primarily
# from typed contracts and flow-aware scope resolution, not keyword sprawl.

_CHANGE_SEMANTIC_PHRASES: tuple[str, ...] = (
    "ändra",
    "byt",
    "ersätt",
    "konvertera",
    "uppdatera",
    "lägg till",
    "ta bort",
    "aktivera",
    "avaktivera",
    "i stället för",
    "istället för",
    "change",
    "switch",
    "replace",
    "convert",
    "update",
    "add",
    "remove",
    "enable",
    "disable",
    "instead of",
)

_ELLIPTICAL_CAPABILITY_HINTS: tuple[str, ...] = (
    "citation",
    "citations",
    "källhänvis",
    "kunskapsbas",
    "knowledge base",
    "contract",
    "kontrakt",
    "step",
    "steg",
)

_INPUT_CHANGE_TARGET_PHRASES: tuple[str, ...] = (
    "ändra indata",
    "change input",
    "input architecture",
    "indataarkitektur",
    "ta emot",
    "tar emot",
    "accept",
    "ladda upp",
    "upload",
)

_CASE_SCOPE_CHANGE_PHRASES: tuple[str, ...] = (
    "flera ärenden",
    "multiple cases",
    "compare",
    "jämför",
    "jämföra",
)

_OUTPUT_STYLE_HINTS: tuple[str, ...] = (
    "kortare",
    "längre",
    "formal",
    "saklig",
    "reader",
    "läsare",
    "målgrupp",
    "sections",
    "sektioner",
    "summary only",
    "bara sammanfattning",
)


@dataclass(frozen=True, slots=True)
class ActiveRequestWindow:
    text: str
    start_index: int | None
    merged_previous_request: bool = False


@dataclass(frozen=True, slots=True)
class EditScopeResolution:
    """Higher-confidence edit scope for AI Builder discovery.

    Low-level keyword intent remains intentionally broad for create mode and
    incomplete flows. In edit mode, this resolution is the authoritative
    override: settled flow state takes precedence over incidental keyword hits,
    and a family is activated only when the current request creates a real
    change signal for that family.
    """

    settled_families: frozenset[DiscoveryFamily]
    active_families: frozenset[DiscoveryFamily]
    requested_output_artifact: str | None = None
    requested_output_generation_mode: str | None = None
    merged_previous_request: bool = False


def has_change_semantics(text: str) -> bool:
    normalized = normalize_discovery_text(text)
    if not normalized:
        return False
    return contains_any_phrase(normalized, _CHANGE_SEMANTIC_PHRASES)


def build_active_request_window(
    conversation: Sequence[ConversationMessage],
    *,
    flow_defaults: dict[str, set[str]],
) -> ActiveRequestWindow:
    freeform_messages = extract_freeform_user_messages(conversation)
    if not freeform_messages:
        return ActiveRequestWindow(text="", start_index=None)

    start_index, latest_text = freeform_messages[-1]
    if len(freeform_messages) > 1 and _is_requirements_confirmation_turn(
        conversation[start_index]
    ):
        previous_index, previous_text = freeform_messages[-2]
        return ActiveRequestWindow(
            text="\n".join(part for part in (previous_text, latest_text) if part),
            start_index=previous_index,
            merged_previous_request=True,
        )

    if len(freeform_messages) == 1 or not _is_elliptical_request(
        latest_text,
        flow_defaults=flow_defaults,
    ):
        return ActiveRequestWindow(text=latest_text, start_index=start_index)

    previous_index, previous_text = freeform_messages[-2]
    return ActiveRequestWindow(
        text="\n".join(part for part in (previous_text, latest_text) if part),
        start_index=previous_index,
        merged_previous_request=True,
    )


def _is_requirements_confirmation_turn(message: ConversationMessage) -> bool:
    return bool(
        message.role == "user"
        and requirements_confirmation_from_metadata(message.metadata) is not None
    )


def resolve_edit_scope(
    *,
    edit_mode: bool,
    capabilities: FlowCapabilityProfile,
    active_request_text: str,
    active_answer_signals: dict[str, set[str]],
    active_explicit_question_ids: set[str] | None = None,
    merged_previous_request: bool = False,
) -> EditScopeResolution:
    settled_families = capabilities.settled_families
    if not edit_mode:
        return EditScopeResolution(
            settled_families=settled_families,
            active_families=ALL_DISCOVERY_FAMILIES,
            merged_previous_request=merged_previous_request,
        )

    normalized_text = normalize_discovery_text(active_request_text)
    if not normalized_text:
        return EditScopeResolution(
            settled_families=settled_families,
            active_families=frozenset(),
            merged_previous_request=merged_previous_request,
        )

    flow_defaults = capabilities.to_signal_defaults()
    output_intent = resolve_output_intent(
        active_request_text,
        active_answer_signals,
        flow_defaults=flow_defaults,
    )
    input_intent = resolve_input_intent(
        normalized_text,
        active_answer_signals,
    )

    active_families: set[DiscoveryFamily] = set()

    output_changed = _output_family_changed(capabilities, output_intent)
    if output_changed:
        active_families.add("output_artifact")

    if (
        mentions_runtime_metadata(normalized_text)
        or active_answer_signals.get("runtime_metadata_fields")
        or (
            active_explicit_question_ids is not None
            and "runtime_metadata_fields" in active_explicit_question_ids
        )
    ):
        active_families.add("runtime_metadata")

    if _mentions_output_style_change(
        normalized_text,
        active_explicit_question_ids or set(),
    ):
        active_families.add("output_style")

    if _mentions_case_scope_change(
        normalized_text,
        active_explicit_question_ids or set(),
    ):
        active_families.add("case_scope")

    if _input_family_changed(
        normalized_text=normalized_text,
        capabilities=capabilities,
        input_intent=input_intent,
        active_explicit_question_ids=active_explicit_question_ids or set(),
        output_changed=output_changed,
    ):
        active_families.add("input_shape")

    requested_generation_mode = (
        output_intent.docx_output_mode or output_intent.pdf_generation_mode
    )
    return EditScopeResolution(
        settled_families=settled_families,
        active_families=frozenset(active_families),
        requested_output_artifact=output_intent.terminal_output,
        requested_output_generation_mode=requested_generation_mode,
        merged_previous_request=merged_previous_request,
    )


def _is_elliptical_request(
    text: str,
    *,
    flow_defaults: dict[str, set[str]],
) -> bool:
    normalized = normalize_discovery_text(text)
    if not normalized or len(normalized) > 30:
        return False
    output_intent = resolve_output_intent(normalized, {}, flow_defaults=None)
    if output_intent.terminal_output is not None:
        return False
    input_intent = resolve_input_intent(normalized, {})
    if input_intent.primary_runtime_input != "unknown":
        return False
    if input_intent.needs_architecture_clarification:
        return False
    if mentions_runtime_metadata(normalized):
        return False
    if contains_any_phrase(normalized, _ELLIPTICAL_CAPABILITY_HINTS):
        return False
    return len(normalized.split()) <= 4


def _output_family_changed(
    capabilities: FlowCapabilityProfile,
    output_intent: OutputIntentResolution,
) -> bool:
    if output_intent.terminal_output is None:
        return False
    if output_intent.terminal_output != capabilities.final_output_mode:
        return True
    if output_intent.docx_output_mode is not None:
        current_mode = (
            "template_fill_docx"
            if capabilities.final_output_generation_mode == "template_fill"
            else "generated_docx"
            if capabilities.final_output_type == "docx"
            else None
        )
        return output_intent.docx_output_mode != current_mode
    if output_intent.pdf_generation_mode is not None:
        current_mode = (
            "generated_pdf" if capabilities.final_output_type == "pdf" else None
        )
        return output_intent.pdf_generation_mode != current_mode
    return False


def _input_family_changed(
    *,
    normalized_text: str,
    capabilities: FlowCapabilityProfile,
    input_intent: InputIntentResolution,
    active_explicit_question_ids: set[str],
    output_changed: bool,
) -> bool:
    if any(
        key in active_explicit_question_ids
        for key in (
            "primary_runtime_input",
            "flow_input_architecture",
            "document_material_scope",
            "comparison_scope",
        )
    ):
        return True
    if input_intent.needs_architecture_clarification:
        return True
    if not capabilities.runtime_input_settled:
        return input_intent.primary_runtime_input != "unknown"
    if output_changed and not contains_any_phrase(
        normalized_text, _INPUT_CHANGE_TARGET_PHRASES
    ):
        return False
    if not has_change_semantics(normalized_text):
        return False
    return contains_any_phrase(normalized_text, _INPUT_CHANGE_TARGET_PHRASES)


def _mentions_case_scope_change(
    text: str,
    active_explicit_question_ids: set[str],
) -> bool:
    if (
        "comparison_scope" in active_explicit_question_ids
        or "processing_scope" in active_explicit_question_ids
    ):
        return True
    return has_change_semantics(text) and contains_any_phrase(
        text, _CASE_SCOPE_CHANGE_PHRASES
    )


def _mentions_output_style_change(
    text: str,
    active_explicit_question_ids: set[str],
) -> bool:
    if any(
        key in active_explicit_question_ids
        for key in ("final_pdf_type", "output_reader", "final_output_scope")
    ):
        return True
    return has_change_semantics(text) and contains_any_phrase(text, _OUTPUT_STYLE_HINTS)
