from __future__ import annotations

import re
from typing import Final

from eneo.flows.ai_builder.ai_builder_discovery_decision_engine import (
    implies_single_case,
    implies_single_primary_document,
)
from eneo.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryProfile
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    expresses_task_intent,
    mentions_any,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_post_processing_goal,
    infer_structured_io_contract,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    latest_pending_structured_question,
    mentions_output_change,
    mentions_runtime_metadata,
)
from eneo.flows.ai_builder.planning_state import ResolvedSlot

EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID: Final = "external_delivery_unsupported"

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
        "primary_runtime_input": "input",
        "flow_input_architecture": "input",
        "document_kind": "input",
        "document_material_scope": "input",
        "post_processing_goal": "outcome",
        "structured_io_contract": "outcome",
        "comparison_scope": "comparison",
        "terminal_output": "output",
        "docx_output_mode": "output",
        "pdf_generation_mode": "output",
        "output_reader": "output",
        "final_output_scope": "output",
        "runtime_metadata_fields": "input",
    }.get(question_id, "output")


_EXTERNAL_DELIVERY_ACTION_RE = re.compile(
    r"(?<![\w-])(?:"
    r"anropa|anropar|skicka|skickar|posta|postar|"
    r"send|sends|deliver|delivers|post|posts"
    r")(?![\w-])",
    re.IGNORECASE,
)
_EXTERNAL_DELIVERY_DESTINATION_RE = re.compile(
    r"(?<![\w-])(?:api|webhook)(?![\w-])|"
    r"\bexternal\s+(?:system|api|integration)\b|"
    r"\bexternt\s+(?:system|api)\b|"
    r"\bextern\s+integration\b",
    re.IGNORECASE,
)


def external_delivery_requested(profile: DiscoveryProfile) -> bool:
    return bool(
        _EXTERNAL_DELIVERY_ACTION_RE.search(profile.text)
        and _EXTERNAL_DELIVERY_DESTINATION_RE.search(profile.text)
    )


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
        (
            "case material",
            "case package",
            "official material",
            "case files",
            "kommunärende",
            "municipal case",
        ),
    )


def primary_runtime_input_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "primary_runtime_input"):
        return False
    if "primary_runtime_input" in profile.answers:
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    return profile.input_intent.primary_runtime_input == "unknown"


def terminal_output_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "terminal_output"):
        return False
    text = profile.text
    if profile.output_intent.terminal_output is not None:
        return False
    if external_delivery_requested(profile):
        return False
    if mentions_output_change(text):
        return False
    if profile.flow_defaults.get("terminal_output"):
        return False
    if (
        profile.document_like_input
        or profile.audio_like_input
        or profile.case_like_flow
        or profile.final_output_text_or_docx
    ):
        return True
    if "terminal_output" not in profile.answers and expresses_task_intent(text):
        return True
    return mentions_any(
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


def ultra_vague_terminal_output_choice_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "terminal_output"):
        return False
    if profile.output_intent.terminal_output is not None:
        return False
    if "terminal_output" in profile.answers:
        return False
    if profile.flow_defaults.get("terminal_output"):
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


def post_processing_goal_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "post_processing_goal"):
        return False
    resolved_goal = _resolved_slot(profile, "post_processing_goal")
    if resolved_goal is not None and resolved_goal.source != "model":
        return False
    if resolved_goal is None and "post_processing_goal" in profile.answers:
        return False
    if _explicit_post_processing_goal_present(profile.text):
        return False
    if needs_pdf_generation_mode_choice(profile):
        return False
    if _json_to_json_semantic_flow(profile):
        return False
    if _outcome_wording_is_vague(profile):
        return True
    return (
        profile.audio_like_input
        or profile.document_like_input
        or profile.case_like_flow
        or profile.final_output_text_or_docx
    )


def _explicit_post_processing_goal_present(text: str) -> bool:
    return infer_post_processing_goal(text) is not None


def _resolved_slot(profile: DiscoveryProfile, slot_name: str) -> ResolvedSlot | None:
    return profile.resolved_slot(slot_name)


def structured_io_contract_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "structured_io_contract"):
        return False
    if not _json_to_json_semantic_flow(profile):
        return False
    if profile.resolved_slot("structured_io_contract") is not None:
        return False
    if "structured_io_contract" in profile.answers:
        return False
    return infer_structured_io_contract(profile.text) is None


def _json_to_json_semantic_flow(profile: DiscoveryProfile) -> bool:
    return (
        profile.input_intent.primary_runtime_input == "json"
        and profile.output_intent.terminal_output == "structured_json"
    )


def _outcome_wording_is_vague(profile: DiscoveryProfile) -> bool:
    return mentions_any(
        profile.text,
        (
            "något användbart",
            "nagot anvandbart",
            "something useful",
            "dela vidare",
            "share afterwards",
            "professionellt",
            "professional",
            "process documents",
            "processa dokument",
            "bearbeta dokument",
        ),
    )


def needs_docx_mode_choice(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "docx_output_mode"):
        return False
    intent = profile.output_intent
    if intent.terminal_output != "docx_document":
        return False
    if profile.planning_state.has_template_file_role():
        docx_mode_slot = profile.resolved_slot("docx_output_mode")
        return docx_mode_slot is None or docx_mode_slot.source == "policy_default"
    if intent.docx_output_mode is not None:
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
    if profile.resolved_slot("document_material_scope") is not None:
        return False
    answers = profile.answers
    text = profile.text
    if not profile.document_like_input or profile.audio_like_input:
        return False
    if "document_material_scope" in answers:
        return False
    if "document_material_scope" in profile.flow_defaults:
        return False
    if "primary_runtime_input" in answers and "text" in " ".join(
        answers["primary_runtime_input"]
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
            "primary_runtime_input",
            "terminal_output",
        )
    ):
        return False
    if "runtime_metadata_fields" in answers and "primary_runtime_input" in answers:
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
            "kommunärende",
            "municipal case",
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
            "remiss",
            "tjänsteskrivelse",
        ),
    ):
        return False
    if (
        profile.output_intent.terminal_output == "structured_text"
        and not profile.comparison_requested
    ):
        return False
    resolved_document_scope = profile.resolved_slot("document_material_scope")
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
    if "terminal_output" in answers:
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


def runtime_metadata_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "runtime_metadata_fields"):
        return False
    if profile.resolved_slot("runtime_metadata_fields") is not None:
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
    if primary_runtime_input_is_vague(profile):
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    if (
        profile.document_like_input
        and profile.resolved_slot("document_material_scope") is None
        and "document_material_scope" not in profile.answers
        and "document_material_scope" not in profile.flow_defaults
    ):
        return False
    if document_cardinality_is_vague(profile):
        return False
    if document_kind_is_vague(profile):
        return False
    if terminal_output_is_vague(profile):
        return False
    if ultra_vague_terminal_output_choice_is_vague(profile):
        return False
    if needs_docx_mode_choice(profile):
        return False
    if needs_pdf_generation_mode_choice(profile):
        return False
    if final_pdf_type_is_vague(profile):
        return False
    return True
