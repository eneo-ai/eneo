from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    implies_single_primary_document,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryProfile,
    SemanticAdjudicationResult,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import localized_text
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    has_explicit_structured_answer,
    resolve_output_intent,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
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


def build_discovery_profile(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    supplemental_answers: dict[str, set[str]] | None = None,
) -> DiscoveryProfile:
    text = aggregate_freeform_user_text(conversation)
    answers = merge_answer_signals(
        extract_answer_signals(conversation),
        supplemental_answers,
    )
    flow_defaults = build_flow_discovery_defaults(flow)
    output_intent = resolve_output_intent(
        text,
        answers,
        flow_defaults=flow_defaults,
    )
    explicit_input_question_ids = {
        question_id
        for question_id in ("input_material_mode", "flow_input_architecture")
        if has_explicit_structured_answer(conversation, question_id)
    }
    input_intent = resolve_input_intent(
        text,
        answers,
        flow=flow,
        explicit_question_ids=explicit_input_question_ids,
    )
    explicit_output = output_intent.terminal_output
    default_input_modes = flow_defaults.get("input_material_mode", set())
    default_output_mode = flow_defaults.get("final_output_mode", set())
    return DiscoveryProfile(
        language=resolve_discovery_language(conversation, text),
        text=text,
        answers=answers,
        flow_defaults=flow_defaults,
        input_intent=input_intent,
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
                "kommunärende",
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
        and not any("ärende åt gången" in assumption for assumption in existing_assumptions)
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
        and not any("huvuddokument" in assumption for assumption in existing_assumptions)
    ):
        assumptions.append(
            localized_text(
                profile.language,
                "Antar ett huvuddokument per körning tills du säger att ett dokumentpaket ska stödjas.",
                "Assuming one primary document per run unless you later say a document package must be supported.",
            )
        )
    return assumptions


def text_has_task_verbs(text: str) -> bool:
    return mentions_any(text, _TASK_VERBS_SV) or mentions_any(text, _TASK_VERBS_EN)


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
