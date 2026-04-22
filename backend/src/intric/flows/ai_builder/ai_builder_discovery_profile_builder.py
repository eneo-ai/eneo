from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    implies_single_primary_document,
)
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryProfile,
    SemanticAdjudicationResult,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import localized_text
from intric.flows.ai_builder.ai_builder_edit_scope import (
    build_active_request_window,
    resolve_edit_scope,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_structured_answer,
    resolve_output_intent,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_resolved_requirements import (
    build_resolved_requirements_state,
)
from intric.flows.domain.flow import Flow

_TASK_VERBS_SV = (
    "sammanfatta",
    "analysera",
    "extrahera",
    "transkribera",
    "jämför",
    "granska",
    "generera",
    "bedöm",
    "skriv",
    "producera",
    "klassificera",
)
_TASK_VERBS_EN = (
    "summarize",
    "analyze",
    "extract",
    "transcribe",
    "compare",
    "review",
    "generate",
    "assess",
    "write",
    "produce",
    "triage",
    "classify",
    "categorize",
    "draft",
)

_STRUCTURED_INTERMEDIATE_FORCE_HINTS = (
    "json",
    "kontrakt",
    "contract",
    "extrahera",
    "extract",
    "risker",
    "risks",
    "rekommendationer",
    "recommendations",
)

_STRUCTURED_INTERMEDIATE_OPTOUT_HINTS = (
    "håll analysen som vanlig text",
    "keep the analysis as plain text",
    "undvik extra struktur",
    "avoid extra structure",
    "plain text only",
    "text only",
)

_STRUCTURED_REPORT_HINTS = (
    "rapport",
    "report",
    "pdf",
    "docx",
    "structured report",
    "strukturerad",
)

_ANALYSIS_STAGE_HINTS = (
    "analys",
    "analysis",
    "sociologisk",
    "psykologisk",
    "psychological",
    "comparison",
    "jämförelse",
)


def build_discovery_profile(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    supplemental_answers: dict[str, set[str]] | None = None,
) -> DiscoveryProfile:
    full_text = aggregate_freeform_user_text(conversation)
    answers = merge_answer_signals(
        extract_answer_signals(conversation),
        supplemental_answers,
    )
    capabilities = build_flow_capability_profile(flow)
    flow_defaults = capabilities.to_signal_defaults()
    active_window = (
        build_active_request_window(conversation, flow_defaults=flow_defaults)
        if flow is not None
        else None
    )
    text = (
        active_window.text
        if active_window is not None and active_window.text
        else full_text
    )
    active_answers = merge_answer_signals(
        extract_answer_signals(
            conversation[active_window.start_index :]
            if active_window is not None and active_window.start_index is not None
            else conversation
        ),
        supplemental_answers,
    )
    active_conversation = (
        conversation[active_window.start_index :]
        if active_window is not None and active_window.start_index is not None
        else conversation
    )
    active_explicit_question_ids = {
        question_id
        for question_id in (
            "processing_scope",
            "comparison_scope",
            "input_material_mode",
            "flow_input_architecture",
            "document_kind",
            "document_material_scope",
            "final_output_mode",
            "docx_output_mode",
            "pdf_generation_mode",
            "final_pdf_type",
            "output_reader",
            "final_output_scope",
            "structured_analysis_need",
            "runtime_metadata_fields",
        )
        if has_explicit_structured_answer(active_conversation, question_id)
    }
    output_intent = resolve_output_intent(
        text,
        active_answers,
        flow_defaults=flow_defaults,
    )
    explicit_input_question_ids = {
        question_id
        for question_id in ("input_material_mode", "flow_input_architecture")
        if has_explicit_structured_answer(conversation, question_id)
    }
    input_intent = resolve_input_intent(
        text,
        active_answers,
        flow=flow,
        explicit_question_ids=explicit_input_question_ids,
    )
    explicit_output = output_intent.terminal_output
    default_input_modes = flow_defaults.get("input_material_mode", set())
    default_output_mode = flow_defaults.get("final_output_mode", set())
    edit_scope = resolve_edit_scope(
        edit_mode=flow is not None,
        capabilities=capabilities,
        active_request_text=text,
        active_answer_signals=active_answers,
        active_explicit_question_ids=active_explicit_question_ids,
        merged_previous_request=(
            active_window.merged_previous_request
            if active_window is not None
            else False
        ),
    )
    prefer_structured_intermediate = should_prefer_structured_intermediate(
        text=text,
        input_intent=input_intent,
        output_intent=output_intent,
        flow_defaults=flow_defaults,
        answers=answers,
    )
    resolved_requirements = build_resolved_requirements_state(
        active_conversation,
        flow=flow,
    )
    return DiscoveryProfile(
        language=resolve_discovery_language(conversation, text),
        text=text,
        active_request_text=text,
        answers=answers,
        flow_defaults=flow_defaults,
        capabilities=capabilities,
        edit_scope=edit_scope,
        input_intent=input_intent,
        output_intent=output_intent,
        resolved_requirements=resolved_requirements,
        flow=flow,
        edit_mode=flow is not None,
        comparison_requested=mentions_any(
            text,
            (
                "compare",
                "comparison",
                "jämför",
                "jämföra",
                "jämförelse",
                "contradiction",
                "motsägelser",
                "skillnader",
            ),
        ),
        document_like_input=input_intent.document_runtime_input_requested
        or "documents" in default_input_modes,
        case_like_flow=mentions_any(
            text,
            (
                "case",
                "case material",
                "case package",
                "underlag",
                "ticket",
                "tickets",
                "support ticket",
                "support tickets",
                "inquiry",
                "inquiries",
                "triage",
            ),
        )
        or bool(flow_defaults.get("runtime_metadata_fields")),
        audio_like_input=input_intent.audio_requested or "audio" in default_input_modes,
        final_output_text_or_docx=(
            explicit_output in {"structured_text", "docx_document", "pdf_document"}
            or output_intent.content_shape == "structured_report"
            or bool(default_output_mode)
        ),
        prefer_structured_intermediate=prefer_structured_intermediate,
    )


def merge_answer_signals(
    primary: dict[str, set[str]],
    supplemental: dict[str, set[str]] | None,
) -> dict[str, set[str]]:
    merged = {key: set(values) for key, values in primary.items()}
    if supplemental is None:
        return merged
    for key, values in supplemental.items():
        merged.setdefault(key, set()).update(values)
    return merged


def semantic_answers(
    semantic_result: SemanticAdjudicationResult | None,
) -> dict[str, set[str]] | None:
    if semantic_result is None:
        return None
    merged: dict[str, set[str]] = {}
    for signal in semantic_result.signals:
        if signal.confidence == "low":
            continue
        merged.setdefault(signal.question_id, set()).add(signal.value)
    return merged or None


def default_discovery_assumptions(
    *,
    profile: DiscoveryProfile,
    selected_question_ids: list[str],
    existing_assumptions: list[str],
) -> list[str]:
    assumptions: list[str] = []
    if (
        "processing_scope" not in profile.answers
        and "processing_scope" not in selected_question_ids
        and implies_single_case(profile.text)
        and not any(
            "ärende åt gången" in assumption for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar ett ärende åt gången per körning tills du säger att flera ärenden ska hanteras tillsammans.",
                "Assuming one case per run unless you later say multiple cases should be handled together.",
            )
        )
    if (
        "document_material_scope" not in profile.answers
        and "document_material_scope" not in selected_question_ids
        and profile.document_like_input
        and implies_single_primary_document(profile.text)
        and not any(
            "huvuddokument" in assumption for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar ett huvuddokument per körning tills du säger att ett dokumentpaket ska stödjas.",
                "Assuming one primary document per run unless you later say a document package must be supported.",
            )
        )
    if (
        profile.prefer_structured_intermediate
        and "structured_analysis_need" not in selected_question_ids
        and not any(
            "mellanliggande strukturerad data" in assumption.casefold()
            for assumption in existing_assumptions
        )
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar att mellanliggande strukturerad data används i analyssteg där det förbättrar kvalitet och återanvändning.",
                "Assuming intermediate structured data is used in analysis steps where it improves quality and reuse.",
            )
        )
    return assumptions


def text_has_task_verbs(text: str) -> bool:
    return mentions_any(text, _TASK_VERBS_SV) or mentions_any(text, _TASK_VERBS_EN)


def count_distinct_task_verbs(text: str) -> int:
    matches = {verb for verb in (*_TASK_VERBS_SV, *_TASK_VERBS_EN) if verb in text}
    return len(matches)


def should_prefer_structured_intermediate(
    *,
    text: str,
    input_intent: InputIntentResolution,
    output_intent: OutputIntentResolution,
    flow_defaults: dict[str, set[str]],
    answers: dict[str, set[str]],
) -> bool:
    structured_answer = answers.get("structured_analysis_need", set())
    if "text_only_analysis" in structured_answer:
        return False
    if "use_structured_analysis" in structured_answer:
        return True
    if mentions_any(text, _STRUCTURED_INTERMEDIATE_OPTOUT_HINTS):
        return False
    if mentions_any(text, _STRUCTURED_INTERMEDIATE_FORCE_HINTS):
        return True

    document_like_input = (
        input_intent.document_runtime_input_requested
        or "documents"
        in flow_defaults.get(
            "input_material_mode",
            set(),
        )
    )
    if not document_like_input:
        return False

    structured_deliverable = (
        output_intent.terminal_output in {"pdf_document", "docx_document"}
        or output_intent.content_shape == "structured_report"
        or mentions_any(text, _STRUCTURED_REPORT_HINTS)
    )
    if not structured_deliverable:
        return False

    task_verb_count = count_distinct_task_verbs(text)
    if task_verb_count >= 3:
        return True
    return task_verb_count >= 2 and mentions_any(text, _ANALYSIS_STAGE_HINTS)


def mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def infer_discovery_language(text: str) -> DiscoveryLanguage:
    if mentions_any(
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
        metadata = message.metadata if isinstance(message.metadata, dict) else None
        ui_language = metadata.get("ui_language") if metadata else None
        if ui_language in {"sv", "en"}:
            return ui_language
    return infer_discovery_language(text)
