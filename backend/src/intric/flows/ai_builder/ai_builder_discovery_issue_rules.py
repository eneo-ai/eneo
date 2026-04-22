from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    implies_single_primary_document,
)
from intric.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryProfile
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import mentions_any
from intric.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    latest_pending_structured_question,
    mentions_output_change,
    mentions_runtime_metadata,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    detect_planner_pattern_signals,
)

_DOCUMENT_PACKAGE_PHRASES: tuple[str, ...] = (
    "dokumentpaket",
    "document package",
    "flera relaterade pdf",
    "multiple related pdf",
    "flera dokument i samma ärende",
    "multiple documents for the same case",
)


def question_category(question_id: str) -> str:
    return {
        "processing_scope": "scope",
        "input_material_mode": "input",
        "flow_input_architecture": "input",
        "document_kind": "input",
        "document_material_scope": "input",
        "comparison_scope": "comparison",
        "final_output_mode": "output",
        "docx_output_mode": "output",
        "pdf_generation_mode": "output",
        "output_reader": "output",
        "final_output_scope": "output",
        "runtime_metadata_fields": "input",
    }.get(question_id, "output")


def latest_pending_question_id(
    conversation: list[ConversationMessage],
) -> str | None:
    payload = latest_pending_structured_question(conversation)
    if not isinstance(payload, dict):
        return None
    question_id = payload.get("question_id")
    return canonical_question_id(question_id) if isinstance(question_id, str) else None


def _family_inactive(profile: DiscoveryProfile, question_id: str) -> bool:
    if not profile.edit_mode:
        return False
    family = family_for_issue(question_id)
    if family is None:
        return False
    return family not in profile.edit_scope.active_families


def looks_like_case_scope_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "processing_scope"):
        return False
    text = profile.text
    answers = profile.answers
    if "processing_scope" in answers:
        return False
    if mentions_any(
        text,
        ("one case at a time", "en fil per körning", "ett ärende", "single case"),
    ):
        return False
    if implies_single_case(text):
        return False
    if mentions_any(text, ("multiple cases", "flera ärenden", "several cases")):
        return False
    return mentions_any(
        text,
        ("case material", "case package", "official material", "case files"),
    )


def looks_like_input_mode_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "input_material_mode"):
        return False
    if "input_material_mode" in profile.answers:
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    return profile.input_intent.primary_runtime_input == "unknown"


def looks_like_output_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "final_output_mode"):
        return False
    text = profile.text
    if profile.output_intent.terminal_output is not None:
        return False
    if mentions_output_change(text):
        return False
    if profile.flow_defaults.get("final_output_mode"):
        return False
    output_intent = mentions_any(
        text,
        (
            "report",
            "rapport",
            "summary",
            "sammanfattning",
            "output",
            "resultat",
            "slutresultat",
            "generate",
            "generera",
        ),
    )
    if not output_intent and not profile.final_output_text_or_docx:
        return False
    if (
        profile.document_like_input
        or profile.audio_like_input
        or profile.case_like_flow
    ):
        return True
    return output_intent


def ultra_vague_output_choice_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "final_output_mode"):
        return False
    if profile.output_intent.terminal_output is not None:
        return False
    if "final_output_mode" in profile.answers:
        return False
    if profile.flow_defaults.get("final_output_mode"):
        return False
    if profile.case_like_flow or profile.comparison_requested:
        return False
    if len(profile.text.split()) > 7:
        return False
    if mentions_any(
        profile.text,
        (
            "pdf",
            "docx",
            "word",
            "json",
            "rapport",
            "report",
            "text summary",
            "textsammanfattning",
            "sammanfattning som text",
            "decision support",
        ),
    ):
        return False
    if not mentions_any(
        profile.text,
        (
            "sammanfatt",
            "summarize",
            "analysera",
            "analyze",
            "extrahera",
            "extract",
            "process",
            "bearbeta",
        ),
    ):
        return False
    return profile.document_like_input or profile.audio_like_input


def needs_docx_mode_choice(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "docx_output_mode"):
        return False
    intent = profile.output_intent
    if intent.terminal_output != "docx_document" or intent.docx_output_mode is not None:
        return False
    return mentions_any(
        profile.text,
        (
            "docx",
            "word",
            "word document",
            "word-dokument",
            "mall",
            "template",
        ),
    )


def needs_pdf_generation_mode_choice(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "pdf_generation_mode"):
        return False
    intent = profile.output_intent
    return (
        intent.terminal_output == "pdf_document"
        and intent.pdf_generation_mode == "pdf_template_requested"
    )


def comparison_architecture_is_clear(text: str, answers: dict[str, set[str]]) -> bool:
    if "comparison_scope" in answers:
        return True
    if mentions_any(
        text,
        (
            "same run",
            "samma körning",
            "earlier saved",
            "tidigare sparade",
            "knowledge base",
            "kunskapsbas",
            "ladda upp flera pdf",
            "ladda upp flera pdf:er",
            "ladda upp flera dokument",
            "upload multiple pdf",
            "upload several pdf",
            "upload multiple documents",
            *_DOCUMENT_PACKAGE_PHRASES,
        ),
    ):
        return True
    return False


def has_same_run_comparison_contradiction(
    text: str,
    answers: dict[str, set[str]],
) -> bool:
    if not mentions_any(text, ("compare", "jämför", "jämföra", "jämförelse")):
        return False

    says_single_file = mentions_any(
        text,
        (
            "one file per run",
            "one pdf per run",
            "en fil per körning",
            "en pdf per körning",
            "1 pdf per run",
            "1 pdf laddas upp vid varje körning",
        ),
    )
    says_same_run_compare = mentions_any(
        text,
        (
            "same run",
            "samma körning",
            "always compare multiple documents",
            "alltid jämföra flera dokument",
            "compare several documents together",
        ),
    )

    answer_texts = " ".join(value for values in answers.values() for value in values)
    if mentions_any(
        answer_texts,
        (
            "same_run_multiple_documents",
            "same_run_compare",
            "multiple_documents_case",
            "flexible_document_case",
            "multiple_pdfs_same_run",
            "single_document_against_previous",
            "remove_direct_comparison",
        ),
    ):
        return False

    if mentions_any(
        text,
        (
            "ladda upp flera pdf",
            "ladda upp flera pdf:er",
            "ladda upp flera dokument",
            "upload multiple pdf",
            "upload several pdf",
            "upload multiple documents",
        ),
    ):
        return False

    return says_single_file and says_same_run_compare


def document_cardinality_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "document_material_scope"):
        return False
    if profile.resolved_requirements.slot("document_material_scope") is not None:
        return False
    answers = profile.answers
    text = profile.text
    if not profile.document_like_input or profile.audio_like_input:
        return False
    if "document_material_scope" in answers:
        return False
    if "document_material_scope" in profile.flow_defaults:
        return False
    if "input_material_mode" in answers and "text" in " ".join(
        answers["input_material_mode"]
    ):
        return False
    if "comparison_scope" in answers:
        return False
    if "processing_scope" in answers and "single_case" in answers["processing_scope"]:
        return False
    if mentions_any(
        text,
        (
            "one document",
            "single document",
            "one pdf",
            "ett dokument",
            "en pdf",
            "multiple documents",
            "several documents",
            "flera dokument",
            "document package",
            "dokumentpaket",
        ),
    ):
        return False
    if implies_single_primary_document(text):
        return False
    return profile.case_like_flow or profile.comparison_requested


def mixed_input_architecture_is_vague(
    profile: DiscoveryProfile,
    *,
    explicit_resolved: bool,
) -> bool:
    if explicit_resolved:
        return False
    if _family_inactive(profile, "flow_input_architecture"):
        return False
    return profile.input_intent.needs_architecture_clarification


def document_kind_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "document_kind"):
        return False
    if not profile.document_like_input or profile.audio_like_input:
        return False
    answers = profile.answers
    text = profile.text
    if "document_kind" in answers:
        return False
    if "comparison_scope" in answers:
        return False
    if all(
        key in answers
        for key in (
            "processing_scope",
            "input_material_mode",
            "final_output_mode",
        )
    ):
        return False
    if "runtime_metadata_fields" in answers and "input_material_mode" in answers:
        return False
    if (
        profile.output_intent.terminal_output is not None
        and not profile.case_like_flow
        and not profile.comparison_requested
    ):
        return False
    if mentions_any(
        text,
        (
            *_DOCUMENT_PACKAGE_PHRASES,
            "case material",
            "underlag",
            "news article",
            "news articles",
            "nyhetsartikel",
            "nyhetsartiklar",
            "contract",
            "contracts",
            "avtal",
            "agreement",
            "agreements",
            "budget",
        ),
    ):
        return False
    if (
        profile.output_intent.terminal_output == "structured_text"
        and not profile.comparison_requested
    ):
        return False
    resolved_document_scope = profile.resolved_requirements.slot(
        "document_material_scope"
    )
    if (
        resolved_document_scope is not None
        and resolved_document_scope.value == "single_document_case"
        and not profile.comparison_requested
    ):
        return False
    return mentions_any(
        text,
        ("pdf", "document", "documents", "dokument", "files", "filer"),
    )


def reader_and_style_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "output_reader"):
        return False
    if not profile.final_output_text_or_docx:
        return False
    answers = profile.answers
    text = profile.text
    if any(key in answers for key in ("output_reader", "output_style", "output_tone")):
        return False
    if mentions_any(
        text,
        (
            "chef",
            "manager",
            "politiker",
            "politician",
            "analyst",
            "analytiker",
            "specialist",
            "public",
            "allmänhet",
        ),
    ):
        return False
    if profile.edit_mode and not mentions_any(
        text,
        (
            "målgrupp",
            "audience",
            "reader",
            "läsare",
            "ton",
            "tone",
            "formal",
            "saklig",
        ),
    ):
        return False
    return mentions_any(text, ("report", "rapport", "memo"))


def final_output_scope_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "final_output_scope"):
        return False
    if not profile.final_output_text_or_docx:
        return False
    answers = profile.answers
    text = profile.text
    if any(
        key in answers
        for key in (
            "final_output_scope",
            "output_style",
            "detail_level",
            "final_pdf_type",
            "structured_analysis_need",
        )
    ):
        return False
    if mentions_any(
        text,
        (
            "summary only",
            "sammanfattning",
            "recommendation",
            "rekommendation",
            "assessment",
            "bedömning",
            "sections",
            "sektioner",
        ),
    ):
        return False
    if profile.edit_mode and not mentions_any(
        text,
        (
            "kortare",
            "längre",
            "summary only",
            "bara sammanfattning",
            "sections",
            "sektioner",
            "more detail",
            "mer detaljerad",
            "less detail",
            "mindre detaljerad",
            "expand",
            "shorten",
        ),
    ):
        return False
    return mentions_any(
        text,
        (
            "report",
            "rapport",
            "memo",
            "analys",
            "analysis",
            "översikt",
            "overview",
            "brief",
            "notat",
            "utlåtande",
        ),
    )


def final_pdf_type_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "final_pdf_type"):
        return False
    answers = profile.answers
    text = profile.text
    if "final_pdf_type" in answers:
        return False
    if "final_output_mode" in answers:
        return False
    output_choice = profile.output_intent.terminal_output
    if output_choice != "pdf_document":
        return False
    if mentions_any(
        text,
        (
            "kort sammanfattning",
            "structured report",
            "strukturerad rapport",
            "faktalista",
            "punktlista",
            "key points",
            "bullet",
        ),
    ):
        return False
    return True


def structured_analysis_need_is_vague(profile: DiscoveryProfile) -> bool:
    if profile.resolved_requirements.slot("structured_analysis_need") is not None:
        return False
    answers = profile.answers
    text = profile.text
    planner_patterns = detect_planner_pattern_signals(text)
    if "structured_analysis_need" in answers:
        return False
    if "structured_json" in answers.get("final_output_mode", set()):
        return False
    if mentions_any(
        text,
        (
            "strukturerad data används",
            "structured data",
            "json",
            "kontrakt",
            "contract",
            "extrahera",
            "risker",
            "möjligheter",
            "rekommendationer",
        ),
    ):
        return True
    if planner_patterns.rich_document_workflow and (
        planner_patterns.needs_form_fields or planner_patterns.prefers_quality_step
    ):
        return True
    return False


def runtime_metadata_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "runtime_metadata_fields"):
        return False
    if not profile.case_like_flow:
        return False
    if profile.resolved_requirements.slot("runtime_metadata_fields") is not None:
        return False
    answers = profile.answers
    text = profile.text
    if "runtime_metadata_fields" in answers:
        return False
    if (
        "runtime_metadata_fields" in profile.flow_defaults
        and not mentions_runtime_metadata(text)
    ):
        return False
    if mentions_runtime_metadata(text):
        return False
    if not _runtime_metadata_prerequisites_resolved(profile):
        return False
    return True


def _runtime_metadata_prerequisites_resolved(profile: DiscoveryProfile) -> bool:
    if looks_like_case_scope_is_vague(profile):
        return False
    if looks_like_input_mode_is_vague(profile):
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    if (
        profile.document_like_input
        and profile.resolved_requirements.slot("document_material_scope") is None
        and "document_material_scope" not in profile.answers
        and "document_material_scope" not in profile.flow_defaults
    ):
        return False
    if document_cardinality_is_vague(profile):
        return False
    if document_kind_is_vague(profile):
        return False
    if looks_like_output_is_vague(profile):
        return False
    if ultra_vague_output_choice_is_vague(profile):
        return False
    if needs_docx_mode_choice(profile):
        return False
    if needs_pdf_generation_mode_choice(profile):
        return False
    if final_pdf_type_is_vague(profile):
        return False
    return True
