from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    ui_language_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryProfile,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_edit_scope import (
    build_active_request_window,
    resolve_edit_scope,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_unprompted_user_text,
    extract_answer_signals,
    has_explicit_structured_answer,
    resolve_output_intent,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
    resolve_input_intent,
)
from eneo.flows.ai_builder.planning_state import PlanningState, SlotSource
from eneo.flows.ai_builder.planning_state_builder import (
    ChosenPrimaryRuntimeInput,
    build_planning_state_from_conversation,
    chosen_input_question_ids,
    chosen_primary_runtime_input,
    complete_planning_state,
)
from eneo.flows.domain.flow import Flow

# What the user settled, as opposed to what the request was read to imply. An
# accepted requirements summary is authoritative without being a direct choice.
_USER_AUTHORITATIVE_ANSWER_SOURCES: frozenset[SlotSource] = frozenset(
    {
        "requirements_summary",
        "structured_answer",
    }
)
_ACTIVE_REQUEST_ANSWER_SOURCES: frozenset[SlotSource] = (
    _USER_AUTHORITATIVE_ANSWER_SOURCES | (frozenset[SlotSource]({"model"}))
)
_PROFILE_DEFAULT_ANSWER_SOURCES: frozenset[SlotSource] = frozenset(
    {
        "flow_default",
        "policy_default",
    }
)


def build_discovery_profile(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    planning_state: PlanningState | None = None,
) -> DiscoveryProfile:
    full_text = aggregate_unprompted_user_text(conversation)
    capabilities = build_flow_capability_profile(flow)
    flow_defaults = capabilities.to_signal_defaults()
    active_window = (
        build_active_request_window(conversation, flow_defaults=flow_defaults)
        if flow is not None
        else None
    )
    active_conversation = (
        conversation[active_window.start_index :]
        if active_window is not None and active_window.start_index is not None
        else conversation
    )
    if planning_state is None:
        planning_state = build_planning_state_from_conversation(
            active_conversation,
            flow=flow,
        )
        complete_planning_state(planning_state, freeform_text=full_text)
    canonical_planning_state_answers = answer_signals_from_planning_state(
        planning_state,
        accepted_sources=_ACTIVE_REQUEST_ANSWER_SOURCES,
    )
    default_planning_state_answers = answer_signals_from_planning_state(
        planning_state,
        accepted_sources=_PROFILE_DEFAULT_ANSWER_SOURCES,
    )
    answers = _overlay_answer_signals(
        extract_answer_signals(conversation),
        canonical_planning_state_answers,
        fallback_answers=default_planning_state_answers,
    )
    text = (
        active_window.text
        if active_window is not None and active_window.text
        else full_text
    )
    active_answers = _overlay_answer_signals(
        extract_answer_signals(active_conversation),
        canonical_planning_state_answers,
    )
    active_explicit_question_ids = {
        question_id
        for question_id in (
            "comparison_scope",
            "primary_runtime_input",
            "flow_input_architecture",
            "document_material_scope",
            "terminal_output",
            "docx_output_mode",
            "pdf_generation_mode",
            "runtime_metadata_fields",
        )
        if has_explicit_structured_answer(active_conversation, question_id)
    }
    output_intent = resolve_output_intent(
        text,
        active_answers,
        flow_defaults=flow_defaults,
        conversation=active_conversation,
    )
    chosen_input = chosen_primary_runtime_input(active_conversation)
    input_intent = resolve_input_intent(
        text,
        active_answers,
        flow=flow,
        explicit_question_ids=chosen_input_question_ids(chosen_input),
    )
    input_intent = _project_canonical_input_intent(
        input_intent,
        canonical_planning_state_answers,
        # Only an answer the user gave outranks the persisted reading; a value
        # read out of their prose is already in the resolution above.
        answered_input=(
            chosen_input
            if chosen_input is not None and chosen_input.question_id is not None
            else None
        ),
        user_authoritative_answers=answer_signals_from_planning_state(
            planning_state,
            accepted_sources=_USER_AUTHORITATIVE_ANSWER_SOURCES,
        ),
    )
    explicit_output = output_intent.terminal_output
    default_input_modes = flow_defaults.get("primary_runtime_input", set())
    default_output_mode = flow_defaults.get("terminal_output", set())
    edit_scope = resolve_edit_scope(
        edit_mode=flow is not None,
        capabilities=capabilities,
        active_request_text=text,
        active_answer_signals=active_answers,
        active_explicit_question_ids=active_explicit_question_ids,
    )
    return DiscoveryProfile(
        language=resolve_discovery_language(conversation, text),
        text=text,
        answers=answers,
        capabilities=capabilities,
        edit_scope=edit_scope,
        input_intent=input_intent,
        output_intent=output_intent,
        planning_state=planning_state,
        flow=flow,
        edit_mode=flow is not None,
        document_like_input=input_intent.document_runtime_input_requested
        or "documents" in default_input_modes,
        audio_like_input=input_intent.audio_requested or "audio" in default_input_modes,
        final_output_text_or_docx=(
            explicit_output in {"structured_text", "docx_document", "pdf_document"}
            or output_intent.content_shape == "structured_report"
            or bool(default_output_mode)
        ),
    )


def _overlay_answer_signals(
    raw_answers: dict[str, set[str]],
    canonical_answers: dict[str, set[str]],
    *,
    fallback_answers: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    projected = {key: set(values) for key, values in raw_answers.items()}
    for key, values in (fallback_answers or {}).items():
        projected.setdefault(key, set(values))
    for key, values in canonical_answers.items():
        projected[key] = set(values)
    return projected


def answer_signals_from_planning_state(
    planning_state: PlanningState,
    *,
    accepted_sources: frozenset[SlotSource],
) -> dict[str, set[str]]:
    answers: dict[str, set[str]] = {}
    for slot in planning_state.resolved_slots.values():
        if slot.source not in accepted_sources:
            continue
        answers.setdefault(slot.name, set()).add(slot.value)
    return answers


def _project_canonical_input_intent(
    resolved: InputIntentResolution,
    canonical_planning_state_answers: dict[str, set[str]],
    *,
    answered_input: ChosenPrimaryRuntimeInput | None,
    user_authoritative_answers: dict[str, set[str]],
) -> InputIntentResolution:
    # The user's own answer outranks every persisted reading of the request.
    primary_runtime_input = (
        {answered_input.value}
        if answered_input is not None
        else canonical_planning_state_answers.get("primary_runtime_input")
    )
    if not primary_runtime_input:
        return resolved
    if len(primary_runtime_input) != 1:
        raise ValueError(
            "PlanningState primary_runtime_input must contain exactly one value"
        )

    # An accepted primary-input slot owns the whole runtime-input dimension;
    # incidental text must not reconstruct secondary modalities and reopen it.
    canonical = resolve_input_intent(
        "",
        {"primary_runtime_input": primary_runtime_input},
        explicit_question_ids={"primary_runtime_input"},
    )
    if canonical.primary_runtime_input == "unknown":
        raise ValueError(
            "PlanningState primary_runtime_input contains an unsupported value"
        )
    if (
        resolved.needs_architecture_clarification
        and answered_input is None
        and not user_authoritative_answers.get("primary_runtime_input")
    ):
        # The request names two kinds of runtime material and the flow accepts
        # one. Reading the request cannot settle that trade-off, however
        # confidently: the user owns the choice until they make it.
        return resolved
    return canonical


def infer_discovery_language(text: str) -> DiscoveryLanguage:
    if contains_any_phrase(
        text,
        (
            " jag ",
            " ska ",
            " vill ",
            " flöde",
            " dokument",
            " underlag",
            " jämför",
            " rapport",
            " ärende",
            " och ",
            " att ",
            " för ",
        ),
    ) or any(char in text for char in ("å", "ä", "ö")):
        return "sv"
    return "en"


def resolve_discovery_language(
    conversation: list[ConversationMessage],
    text: str,
) -> DiscoveryLanguage:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        ui_language = ui_language_from_metadata(message.metadata)
        if ui_language in {"sv", "en"}:
            return ui_language
    return infer_discovery_language(text)
